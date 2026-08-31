from datetime import datetime, timezone

import pytest

from backend.models.content_monitor import ContentAccount, ContentWork, DetectionResult, EngagementSnapshot
from backend.services.content_monitor_service import list_monitored_works


@pytest.mark.asyncio
async def test_list_monitored_works_filters_priority_queue(db_session):
    account = ContentAccount(
        platform="example",
        external_account_id="account-1",
        handle="creator",
        display_name="Creator",
        raw_profile={},
    )
    db_session.add(account)
    await db_session.flush()

    works = []
    for index, (status, priority) in enumerate((("very_hot", True), ("hot", False), ("observing", False))):
        work = ContentWork(
            account_id=account.id,
            external_work_id=f"work-{index}",
            title=f"Work {index}",
            published_at=datetime(2026, 8, 1 + index, tzinfo=timezone.utc),
            first_seen_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            raw_identity={},
        )
        db_session.add(work)
        await db_session.flush()
        snapshot = EngagementSnapshot(
            work_id=work.id,
            collected_at=datetime(2026, 8, 8 + index, tzinfo=timezone.utc),
            like_count=100 * (index + 1),
            metrics={"like_count": 100 * (index + 1)},
            raw_data={},
        )
        db_session.add(snapshot)
        await db_session.flush()
        db_session.add(
            DetectionResult(
                work_id=work.id,
                snapshot_id=snapshot.id,
                detector_version="v1-final-7d",
                metric_name="like_count",
                current_value=100 * (index + 1),
                baseline_value=100,
                baseline_size=20,
                baseline_missing_count=0,
                relative_multiple=5 if priority else (3 if status == "hot" else 1),
                hot_multiple=3,
                very_hot_multiple=5,
                enters_analysis=status in {"hot", "very_hot"},
                priority_analysis=priority,
                status=status,
                evidence={},
                evaluated_at=snapshot.collected_at,
            )
        )
        works.append(work)

    await db_session.flush()
    priority, total = await list_monitored_works(db_session, queue="priority")
    assert total == 1
    assert priority[0].external_work_id == "work-0"

    ordered, total = await list_monitored_works(db_session, queue="all")
    assert total == 3
    assert [item.external_work_id for item in ordered] == ["work-0", "work-1", "work-2"]
