"""Persist final-window popularity decisions for monitored works."""

from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.detector import evaluate_public_metrics
from backend.models.content_monitor import (
    ContentAccount,
    ContentWork,
    DetectionResult,
    EngagementSnapshot,
)


FINAL_WINDOW = timedelta(days=7)
DETECTOR_VERSION = "v1-final-7d"
OBSERVED_DETECTOR_VERSION = "v1-observed"

_METRIC_ATTRIBUTES = {
    "view_count": "view_count",
    "like_count": "like_count",
    "comment_count": "comment_count",
    "favorite_count": "favorite_count",
    "share_count": "share_count",
}

DEFAULT_MONITORING_RULES = {
    "reference_work_count": 20,
    "hot_multiple": 3.0,
    "very_hot_multiple": 5.0,
    "interval_hours": 4,
    "inherit_global": True,
}
MINIMUM_REFERENCE_WORKS = 5


def monitoring_rules_for_account(account: ContentAccount | None) -> dict[str, Any]:
    rules = dict(DEFAULT_MONITORING_RULES)
    raw_profile = account.raw_profile if account and isinstance(account.raw_profile, dict) else {}
    stored = raw_profile.get("monitoring_rules")
    if isinstance(stored, dict):
        rules.update(stored)
    rules["reference_work_count"] = max(5, min(50, int(rules["reference_work_count"])))
    rules["hot_multiple"] = max(1.5, min(10.0, float(rules["hot_multiple"])))
    rules["very_hot_multiple"] = max(2.0, min(20.0, float(rules["very_hot_multiple"])))
    if rules["very_hot_multiple"] <= rules["hot_multiple"]:
        rules["very_hot_multiple"] = min(20.0, rules["hot_multiple"] + 0.5)
    rules["interval_hours"] = int(rules["interval_hours"])
    rules["inherit_global"] = bool(rules.get("inherit_global", True))
    return rules


def _prior_work_filter(work: ContentWork):
    return or_(
        ContentWork.published_at < work.published_at,
        and_(
            ContentWork.published_at == work.published_at,
            ContentWork.created_at < work.created_at,
        ),
    )


def configured_metrics(source_config: dict[str, Any]) -> list[str] | None:
    """Read explicitly verified metrics, or enable all supported public metrics."""
    monitoring = source_config.get("content_monitoring")
    if not isinstance(monitoring, dict):
        return None
    if "metric_name" in monitoring:
        metric_name = monitoring.get("metric_name")
        return [str(metric_name)] if metric_name in _METRIC_ATTRIBUTES else None
    if "metric_names" in monitoring:
        metric_names = monitoring.get("metric_names")
        if not isinstance(metric_names, list):
            return None
        valid = [str(name) for name in metric_names if name in _METRIC_ATTRIBUTES]
        return valid or None
    return list(_METRIC_ATTRIBUTES)


def configured_metric(source_config: dict[str, Any]) -> str | None:
    """Backward-compatible single-metric accessor for older callers."""
    metrics = configured_metrics(source_config)
    return metrics[0] if metrics and len(metrics) == 1 else None


def _snapshot_metrics(snapshot: EngagementSnapshot | None, metric_names: list[str]) -> dict[str, int | None]:
    if snapshot is None:
        return {name: None for name in metric_names}
    return {name: getattr(snapshot, _METRIC_ATTRIBUTES[name]) for name in metric_names}


async def _final_snapshot_for_work(
    session: AsyncSession,
    work: ContentWork,
) -> EngagementSnapshot | None:
    if work.published_at is None:
        return None
    final_at = work.published_at + FINAL_WINDOW
    result = await session.execute(
        select(EngagementSnapshot)
        .where(
            EngagementSnapshot.work_id == work.id,
            EngagementSnapshot.collected_at >= final_at,
        )
        .order_by(EngagementSnapshot.collected_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def evaluate_final_snapshot(
    session: AsyncSession,
    *,
    snapshot_id: str,
    metric_name: str | None = None,
    metric_names: list[str] | None = None,
) -> DetectionResult | None:
    """Evaluate one work only after its final seven-day snapshot exists.

    The baseline contains only prior works and explicitly excludes the current
    work. Accounts with 5..N prior works are evaluated with an actual-sample
    marker; fewer than 5 remain insufficient.
    """
    selected_metrics = metric_names or ([metric_name] if metric_name else list(_METRIC_ATTRIBUTES))
    if not selected_metrics or any(name not in _METRIC_ATTRIBUTES for name in selected_metrics):
        raise ValueError(f"Unsupported content metrics: {selected_metrics}")

    snapshot = await session.get(EngagementSnapshot, snapshot_id)
    if snapshot is None:
        return None
    work = await session.get(ContentWork, snapshot.work_id)
    if work is None or work.published_at is None:
        return None
    if snapshot.collected_at < work.published_at + FINAL_WINDOW:
        return None
    account = await session.get(ContentAccount, work.account_id)
    rules = monitoring_rules_for_account(account)

    works_result = await session.execute(
        select(ContentWork)
        .where(
            ContentWork.account_id == work.account_id,
            ContentWork.id != work.id,
            _prior_work_filter(work),
        )
        .order_by(ContentWork.published_at.desc().nullslast(), ContentWork.created_at.desc())
        .limit(rules["reference_work_count"])
    )
    baseline_works = list(works_result.scalars().all())
    baseline_values: list[dict[str, int | None]] = []
    for baseline_work in baseline_works:
        baseline_snapshot = await _final_snapshot_for_work(session, baseline_work)
        baseline_values.append(_snapshot_metrics(baseline_snapshot, selected_metrics))
    decision = evaluate_public_metrics(
        metric_names=selected_metrics,
        current_values=_snapshot_metrics(snapshot, selected_metrics),
        baseline_values=baseline_values,
        finalized=True,
        baseline_window=rules["reference_work_count"],
        minimum_baseline=MINIMUM_REFERENCE_WORKS,
        hot_multiple=rules["hot_multiple"],
        very_hot_multiple=rules["very_hot_multiple"],
    )

    existing_result = await session.execute(
        select(DetectionResult).where(
            DetectionResult.snapshot_id == snapshot.id,
            DetectionResult.detector_version == DETECTOR_VERSION,
        )
    )
    detection = existing_result.scalar_one_or_none()
    if detection is None:
        detection = DetectionResult(
            work_id=work.id,
            snapshot_id=snapshot.id,
            detector_version=DETECTOR_VERSION,
        )
        session.add(detection)

    detection.metric_name = decision.metric_name
    detection.current_value = decision.current_value
    detection.baseline_value = decision.baseline_value
    detection.baseline_size = decision.baseline_size
    detection.baseline_missing_count = decision.baseline_missing_count
    detection.relative_multiple = decision.relative_multiple
    detection.hot_multiple = decision.hot_multiple
    detection.very_hot_multiple = decision.very_hot_multiple
    detection.enters_analysis = decision.enters_analysis
    detection.priority_analysis = decision.priority_analysis
    detection.status = decision.status
    evidence = decision.evidence()
    evidence["configured_reference_work_count"] = rules["reference_work_count"]
    evidence["sample_shortfall"] = max(0, rules["reference_work_count"] - decision.baseline_size)
    detection.evidence = evidence
    await session.flush()
    return detection


async def evaluate_observed_snapshot(
    session: AsyncSession,
    *,
    snapshot_id: str,
    metric_names: list[str] | None = None,
) -> DetectionResult | None:
    """Classify an early snapshot against the account's configured prior works.

    This is the fast path for the product goal: a newly discovered work can
    enter the analysis queue as soon as its current public metrics are clearly
    above the creator's normal level. The result is explicitly marked as an
    early observation in ``evidence`` and is replaced by the final seven-day
    evaluation when that window is available.
    """
    selected_metrics = metric_names or list(_METRIC_ATTRIBUTES)
    if not selected_metrics or any(name not in _METRIC_ATTRIBUTES for name in selected_metrics):
        raise ValueError(f"Unsupported content metrics: {selected_metrics}")

    snapshot = await session.get(EngagementSnapshot, snapshot_id)
    if snapshot is None:
        return None
    work = await session.get(ContentWork, snapshot.work_id)
    if work is None or work.published_at is None:
        return None
    account = await session.get(ContentAccount, work.account_id)
    rules = monitoring_rules_for_account(account)

    works_result = await session.execute(
        select(ContentWork)
        .where(
            ContentWork.account_id == work.account_id,
            ContentWork.id != work.id,
            _prior_work_filter(work),
        )
        .order_by(ContentWork.published_at.desc().nullslast(), ContentWork.created_at.desc())
        .limit(rules["reference_work_count"])
    )
    baseline_works = list(works_result.scalars().all())
    baseline_values: list[dict[str, int | None]] = []
    for baseline_work in baseline_works:
        latest_result = await session.execute(
            select(EngagementSnapshot)
            .where(EngagementSnapshot.work_id == baseline_work.id)
            .order_by(EngagementSnapshot.collected_at.desc())
            .limit(1)
        )
        baseline_values.append(
            _snapshot_metrics(latest_result.scalar_one_or_none(), selected_metrics)
        )
    decision = evaluate_public_metrics(
        metric_names=selected_metrics,
        current_values=_snapshot_metrics(snapshot, selected_metrics),
        baseline_values=baseline_values,
        finalized=True,
        baseline_window=rules["reference_work_count"],
        minimum_baseline=MINIMUM_REFERENCE_WORKS,
        hot_multiple=rules["hot_multiple"],
        very_hot_multiple=rules["very_hot_multiple"],
    )
    existing_result = await session.execute(
        select(DetectionResult).where(
            DetectionResult.snapshot_id == snapshot.id,
            DetectionResult.detector_version == OBSERVED_DETECTOR_VERSION,
        )
    )
    detection = existing_result.scalar_one_or_none()
    if detection is None:
        detection = DetectionResult(
            work_id=work.id,
            snapshot_id=snapshot.id,
            detector_version=OBSERVED_DETECTOR_VERSION,
        )
        session.add(detection)

    detection.metric_name = decision.metric_name
    detection.current_value = decision.current_value
    detection.baseline_value = decision.baseline_value
    detection.baseline_size = decision.baseline_size
    detection.baseline_missing_count = decision.baseline_missing_count
    detection.relative_multiple = decision.relative_multiple
    detection.hot_multiple = decision.hot_multiple
    detection.very_hot_multiple = decision.very_hot_multiple
    detection.enters_analysis = decision.enters_analysis
    detection.priority_analysis = decision.priority_analysis
    detection.status = decision.status
    evidence = decision.evidence()
    evidence["finalized"] = False
    evidence["observation_stage"] = "early_snapshot"
    evidence["configured_reference_work_count"] = rules["reference_work_count"]
    evidence["sample_shortfall"] = max(0, rules["reference_work_count"] - decision.baseline_size)
    evidence["reasons"] = [
        "基于当前公开数据快照的早期筛选，满 7 天后会用最终快照复核",
        *evidence.get("reasons", []),
    ]
    detection.evidence = evidence
    await session.flush()
    return detection


async def recalculate_account_detections(
    session: AsyncSession, account_id: str, metric_names: list[str] | None = None
) -> int:
    """Re-evaluate every work from stored snapshots after a rule change."""
    result = await session.execute(
        select(ContentWork)
        .where(ContentWork.account_id == account_id)
        .order_by(ContentWork.published_at.asc().nullsfirst(), ContentWork.created_at.asc())
    )
    recalculated = 0
    for work in result.scalars().all():
        latest_result = await session.execute(
            select(EngagementSnapshot)
            .where(EngagementSnapshot.work_id == work.id)
            .order_by(EngagementSnapshot.collected_at.desc())
            .limit(1)
        )
        snapshot = latest_result.scalar_one_or_none()
        if snapshot is None:
            continue
        if await evaluate_observed_snapshot(
            session, snapshot_id=snapshot.id, metric_names=metric_names
        ):
            recalculated += 1
        if work.published_at and snapshot.collected_at >= work.published_at + FINAL_WINDOW:
            await evaluate_final_snapshot(
                session, snapshot_id=snapshot.id, metric_names=metric_names
            )
    return recalculated
