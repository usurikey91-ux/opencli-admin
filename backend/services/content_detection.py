"""Persist final-window popularity decisions for monitored works."""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.detector import evaluate_public_metrics
from backend.models.content_monitor import ContentWork, DetectionResult, EngagementSnapshot


FINAL_WINDOW = timedelta(days=7)
DETECTOR_VERSION = "v1-final-7d"

_METRIC_ATTRIBUTES = {
    "view_count": "view_count",
    "like_count": "like_count",
    "comment_count": "comment_count",
    "favorite_count": "favorite_count",
    "share_count": "share_count",
}


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

    The baseline is the account's 20 most recent prior works by publication
    time. Every one of those works must have a final snapshot and the selected
    metric; no content-type or suspected-promotion filter is applied.
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

    works_result = await session.execute(
        select(ContentWork)
        .where(
            ContentWork.account_id == work.account_id,
            ContentWork.id != work.id,
        )
        .order_by(ContentWork.published_at.desc().nullslast(), ContentWork.created_at.desc())
        .limit(20)
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
    detection.evidence = decision.evidence()
    await session.flush()
    return detection
