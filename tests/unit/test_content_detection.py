from datetime import datetime, timedelta, timezone

import pytest

from backend.models.content_monitor import ContentAccount, ContentWork, EngagementSnapshot
from backend.models.source import DataSource
from backend.models.task import CollectionTask
from backend.services.content_detection import evaluate_observed_snapshot


@pytest.mark.asyncio
async def test_early_snapshot_enters_queue_after_twenty_prior_works(db_session):
    account = ContentAccount(
        platform="douyin",
        external_account_id="sec-user-1",
        display_name="Benchmark creator",
    )
    source = DataSource(
        name="Douyin public works",
        channel_type="opencli",
        channel_config={"site": "douyin", "command": "user-videos"},
    )
    db_session.add_all([account, source])
    await db_session.flush()

    for index in range(20):
        work = ContentWork(
            account_id=account.id,
            source_id=source.id,
            external_work_id=f"baseline-{index}",
            title=f"Baseline {index}",
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(days=index),
            first_seen_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            raw_identity={},
        )
        db_session.add(work)
        await db_session.flush()
        db_session.add(
            EngagementSnapshot(
                work_id=work.id,
                task_id=None,
                collected_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                like_count=100,
                metrics={"like_count": 100},
                raw_data={},
            )
        )
    await db_session.flush()

    task = CollectionTask(source_id=source.id, trigger_type="manual", parameters={})
    db_session.add(task)
    await db_session.flush()
    current_work = ContentWork(
        account_id=account.id,
        source_id=source.id,
        external_work_id="new-work",
        title="New work",
        published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        first_seen_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        raw_identity={},
    )
    db_session.add(current_work)
    await db_session.flush()
    snapshot = EngagementSnapshot(
        work_id=current_work.id,
        task_id=task.id,
        collected_at=datetime(2026, 8, 20, 1, tzinfo=timezone.utc),
        like_count=300,
        metrics={"like_count": 300},
        raw_data={},
    )
    db_session.add(snapshot)
    await db_session.flush()

    detection = await evaluate_observed_snapshot(
        db_session, snapshot_id=snapshot.id, metric_names=["like_count"]
    )

    assert detection is not None
    assert detection.status == "hot"
    assert detection.enters_analysis is True
    assert detection.detector_version == "v1-observed"
    assert detection.evidence["finalized"] is False
    assert detection.evidence["observation_stage"] == "early_snapshot"
