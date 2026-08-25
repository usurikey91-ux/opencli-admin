"""Read models for the content-monitoring and analysis queue UI."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.content_monitor import ContentWork


QUEUE_VALUES = {"all", "normal", "priority"}


def _latest_snapshot(work: ContentWork):
    return max(work.snapshots, key=lambda item: item.collected_at, default=None)


def _latest_detection(work: ContentWork):
    return max(work.detections, key=lambda item: item.evaluated_at, default=None)


def work_status(work: ContentWork) -> str:
    detection = _latest_detection(work)
    if detection is not None:
        return detection.status
    return "observing" if work.snapshots else "not_seen"


async def list_monitored_works(
    session: AsyncSession,
    *,
    status: Optional[str] = None,
    queue: str = "all",
    source_id: Optional[str] = None,
    account_id: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[ContentWork], int]:
    """List works with their latest snapshot/detection available to consumers.

    The MVP intentionally performs status filtering after loading the small
    monitored set. This keeps the query portable across SQLite/PostgreSQL and
    makes the latest-per-work semantics explicit; a SQL window query can be
    introduced once the monitor volume requires it.
    """
    if queue not in QUEUE_VALUES:
        raise ValueError(f"Unsupported analysis queue: {queue}")

    query = (
        select(ContentWork)
        .options(
            selectinload(ContentWork.account),
            selectinload(ContentWork.snapshots),
            selectinload(ContentWork.detections),
        )
        .order_by(ContentWork.published_at.desc().nullslast(), ContentWork.created_at.desc())
    )
    if source_id:
        query = query.where(ContentWork.source_id == source_id)
    if account_id:
        query = query.where(ContentWork.account_id == account_id)

    works = list((await session.execute(query)).scalars().unique().all())
    filtered = []
    for work in works:
        detection = _latest_detection(work)
        current_status = work_status(work)
        if status and current_status != status:
            continue
        if queue == "priority" and not (detection and detection.priority_analysis):
            continue
        if queue == "normal" and not (detection and detection.enters_analysis and not detection.priority_analysis):
            continue
        filtered.append(work)

    # Analysis order is driven by heat, not publication time: very-hot works
    # come first, then higher relative multiples, with newer works as a stable
    # tie-breaker. This is the product rule that "particularly hot" changes
    # processing order only; it does not change the detector's conclusion.
    def analysis_sort_key(work: ContentWork) -> tuple[int, float, float]:
        detection = _latest_detection(work)
        multiple = detection.relative_multiple if detection else None
        published_timestamp = work.published_at.timestamp() if work.published_at else 0.0
        return (
            -int(bool(detection and detection.priority_analysis)),
            -float(multiple if multiple is not None else 0.0),
            -published_timestamp,
        )

    filtered.sort(key=analysis_sort_key)
    total = len(filtered)
    offset = (page - 1) * limit
    return filtered[offset : offset + limit], total
