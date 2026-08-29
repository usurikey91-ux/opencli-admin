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
async def test_work_without_publish_time_keeps_scheduled_snapshots(db_session):
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


@pytest.mark.asyncio
async def test_recent_work_respects_fixed_four_hour_snapshot_interval(
    db_session, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    from backend.models.source import DataSource
    from backend.models.task import CollectionTask
    from backend.pipeline import content_snapshotter

    observed_at = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(content_snapshotter, "_utcnow", lambda: observed_at)

    source = DataSource(
        name="Public creator",
        channel_type="opencli",
        channel_config={"site": "example", "command": "user-posts"},
    )
    db_session.add(source)
    await db_session.flush()

    raw = {
        "post_id": "recent-work",
        "author_id": "u-1",
        "author": "Creator",
        "url": "https://example.com/recent-work",
        "published_at": (observed_at - timedelta(hours=1)).isoformat(),
        "likes": 100,
    }

    task1 = CollectionTask(source_id=source.id, trigger_type="scheduled", parameters={})
    db_session.add(task1)
    await db_session.flush()
    _, _, first_snapshots = await store_records(
        db_session, task1.id, source.id, normalize_items([raw], source.id)
    )

    observed_at += timedelta(hours=3)
    task2 = CollectionTask(source_id=source.id, trigger_type="scheduled", parameters={})
    db_session.add(task2)
    await db_session.flush()
    _, _, early_snapshots = await store_records(
        db_session, task2.id, source.id, normalize_items([{**raw, "likes": 200}], source.id)
    )

    observed_at += timedelta(hours=1)
    task3 = CollectionTask(source_id=source.id, trigger_type="scheduled", parameters={})
    db_session.add(task3)
    await db_session.flush()
    _, _, due_snapshots = await store_records(
        db_session, task3.id, source.id, normalize_items([{**raw, "likes": 300}], source.id)
    )

    assert first_snapshots == 1
    assert early_snapshots == 0
    assert due_snapshots == 1
