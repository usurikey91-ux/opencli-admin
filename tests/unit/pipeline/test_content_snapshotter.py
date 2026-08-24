"""Tests for content identity and time-series metric snapshots."""

import pytest
from sqlalchemy import func, select

from backend.models.content_monitor import ContentAccount, ContentWork, EngagementSnapshot
from backend.models.record import CollectedRecord
from backend.pipeline.content_snapshotter import extract_metrics, parse_public_count
from backend.pipeline.normalizer import normalize_items
from backend.pipeline.storer import store_records


def test_parse_public_count_formats():
    assert parse_public_count("1.2K") == 1_200
    assert parse_public_count("3.5万") == 35_000
    assert parse_public_count("4,500+") == 4_500
    assert parse_public_count("--") is None


def test_extract_metrics_preserves_missing_fields():
    metrics = extract_metrics({"views": "1.2万", "likes": 800, "comments": "42"})

    assert metrics == {
        "view_count": 12_000,
        "like_count": 800,
        "comment_count": 42,
        "favorite_count": None,
        "share_count": None,
    }


@pytest.mark.asyncio
async def test_repeated_work_creates_snapshots_without_duplicate_records(db_session):
    from backend.models.source import DataSource
    from backend.models.task import CollectionTask

    source = DataSource(
        name="Public creator",
        channel_type="opencli",
        channel_config={"site": "example", "command": "user-posts", "args": {"uid": "u-1"}},
    )
    db_session.add(source)
    await db_session.flush()

    task1 = CollectionTask(source_id=source.id, trigger_type="manual", parameters={})
    task2 = CollectionTask(source_id=source.id, trigger_type="scheduled", parameters={})
    db_session.add_all([task1, task2])
    await db_session.flush()

    first_raw = {
        "post_id": "work-1",
        "author_id": "u-1",
        "author": "Creator",
        "title": "Same public work",
        "url": "https://example.com/work-1",
        "likes": 100,
        "comments": 10,
    }
    second_raw = {**first_raw, "likes": 250, "comments": 25}

    first_records, first_skipped, first_snapshots = await store_records(
        db_session, task1.id, source.id, normalize_items([first_raw], source.id)
    )
    second_records, second_skipped, second_snapshots = await store_records(
        db_session, task2.id, source.id, normalize_items([second_raw], source.id)
    )

    assert len(first_records) == 1
    assert first_skipped == 0
    assert second_records == []
    assert second_skipped == 1
    assert first_snapshots == 1
    assert second_snapshots == 1

    record_count = await db_session.scalar(select(func.count()).select_from(CollectedRecord))
    account_count = await db_session.scalar(select(func.count()).select_from(ContentAccount))
    work_count = await db_session.scalar(select(func.count()).select_from(ContentWork))
    snapshots = (
        await db_session.execute(
            select(EngagementSnapshot).order_by(EngagementSnapshot.collected_at)
        )
    ).scalars().all()

    assert record_count == 1
    assert account_count == 1
    assert work_count == 1
    assert len(snapshots) == 2
    assert [snapshot.like_count for snapshot in snapshots] == [100, 250]
    assert [snapshot.comment_count for snapshot in snapshots] == [10, 25]
