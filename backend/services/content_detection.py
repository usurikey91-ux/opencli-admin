"""Persist final-window popularity decisions for monitored works."""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.detector import evaluate_public_metric
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


def configured_metric(source_config: dict[str, Any]) -> str | None:
    """Read a verified primary public metric without guessing a platform field."""
    monitoring = source_config.get("content_monitoring")
    if not isinstance(monitoring, dict):
        return None
    metric_name = monitoring.get("metric_name")
    if metric_name not in _METRIC_ATTRIBUTES:
        return None
    return str(metric_name)


def _snapshot_metric(snapshot: EngagementSnapshot, metric_name: str) -> int | None:
    return getattr(snapshot, _METRIC_ATTRIBUTES[metric_name])


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
    metric_name: str,
) -> DetectionResult | None:
    """Evaluate one work only after its final seven-day snapshot exists.

    The baseline is the account's 20 most recent prior works by publication
    time. Every one of those works must have a final snapshot and the selected
    metric; no content-type or suspected-promotion filter is applied.
    """
    if metric_name not in _METRIC_ATTRIBUTES:
        raise ValueError(f"Unsupported content metric: {metric_name}")

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
    baseline_values: list[int | None] = []
    for baseline_work in baseline_works:
        baseline_snapshot = await _final_snapshot_for_work(session, baseline_work)
        baseline_values.append(
            _snapshot_metric(baseline_snapshot, metric_name)
            if baseline_snapshot is not None
            else None
        )

    decision = evaluate_public_metric(
        metric_name=metric_name,
        current_value=_snapshot_metric(snapshot, metric_name),
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
