"""Pipeline Step 3: persist first-seen records and time-series snapshots."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.record import CollectedRecord


async def store_records(
    session: AsyncSession,
    task_id: str,
    source_id: str,
    normalized_triples: list[tuple[dict, dict, str]],
) -> tuple[list[CollectedRecord], int, int]:
    """Insert first-seen records and always persist a per-task metrics snapshot.

    ``CollectedRecord`` remains deduplicated for compatibility. Repeated works
    are preserved in ``EngagementSnapshot`` by the content snapshotter.
    """
    if not normalized_triples:
        return [], 0, 0

    # Collect all hashes to check for duplicates in one query
    hashes = [h for _, _, h in normalized_triples]
    result = await session.execute(
        select(CollectedRecord).where(
            CollectedRecord.source_id == source_id,
            CollectedRecord.content_hash.in_(hashes),
        )
    )
    existing_hashes = {record.content_hash for record in result.scalars()}

    new_records: list[CollectedRecord] = []
    skipped = 0

    for raw, normalized, content_hash in normalized_triples:
        if content_hash in existing_hashes:
            skipped += 1
            continue

        record = CollectedRecord(
            task_id=task_id,
            source_id=source_id,
            raw_data=raw,
            normalized_data=normalized,
            content_hash=content_hash,
            status="normalized",
        )
        session.add(record)
        new_records.append(record)
        existing_hashes.add(content_hash)

    from backend.pipeline.content_snapshotter import store_content_snapshots

    snapshots_stored = await store_content_snapshots(
        session=session,
        task_id=task_id,
        source_id=source_id,
        normalized_triples=normalized_triples,
    )

    await session.flush()
    return new_records, skipped, snapshots_stored
