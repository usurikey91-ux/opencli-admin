"""Branch coverage for the content-monitoring read and detection services."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.content_monitor import (
    ContentAccount,
    ContentWork,
    DetectionResult,
    EngagementSnapshot,
)
from backend.models.source import DataSource
from backend.models.task import CollectionTask
from backend.services import content_detection, content_monitor_service


UTC = timezone.utc


def _account(**kwargs) -> ContentAccount:
    return ContentAccount(
        platform="douyin",
        external_account_id=kwargs.pop("external_account_id", "edge-account"),
        raw_profile=kwargs.pop("raw_profile", {}),
        **kwargs,
    )


async def _work_with_snapshot(
    db_session,
    account: ContentAccount,
    *,
    work_id: str,
    published_at: datetime | None,
    collected_at: datetime,
    likes: int | None,
    source_id: str | None = None,
    task_id: str | None = None,
):
    work = ContentWork(
        account_id=account.id,
        source_id=source_id,
        external_work_id=work_id,
        title=work_id,
        published_at=published_at,
        first_seen_at=collected_at,
        last_seen_at=collected_at,
        raw_identity={},
    )
    db_session.add(work)
    await db_session.flush()
    snapshot = EngagementSnapshot(
        work_id=work.id,
        task_id=task_id,
        collected_at=collected_at,
        like_count=likes,
        metrics={"like_count": likes} if likes is not None else {},
        raw_data={},
    )
    db_session.add(snapshot)
    await db_session.flush()
    return work, snapshot


def test_monitoring_rules_and_metric_configuration_are_normalized():
    assert content_detection.monitoring_rules_for_account(None) == {
        **content_detection.DEFAULT_MONITORING_RULES
    }
    account = _account(
        raw_profile={
            "monitoring_rules": {
                "reference_work_count": 1,
                "hot_multiple": 99,
                "very_hot_multiple": 1,
                "interval_hours": "8",
                "inherit_global": 0,
            }
        }
    )
    rules = content_detection.monitoring_rules_for_account(account)
    assert rules["reference_work_count"] == 5
    assert rules["hot_multiple"] == 10.0
    assert rules["very_hot_multiple"] == 10.5
    assert rules["interval_hours"] == 8
    assert rules["inherit_global"] is False

    assert content_detection.configured_metrics({}) is None
    assert content_detection.configured_metrics({"content_monitoring": {}}) == [
        "view_count",
        "like_count",
        "comment_count",
        "favorite_count",
        "share_count",
    ]
    assert content_detection.configured_metrics(
        {"content_monitoring": {"metric_name": "like_count"}}
    ) == ["like_count"]
    assert content_detection.configured_metrics(
        {"content_monitoring": {"metric_name": "nope"}}
    ) is None
    assert content_detection.configured_metrics(
        {"content_monitoring": {"metric_names": "like_count"}}
    ) is None
    assert content_detection.configured_metrics(
        {"content_monitoring": {"metric_names": ["like_count", "nope"]}}
    ) == ["like_count"]
    assert content_detection.configured_metrics(
        {"content_monitoring": {"metric_names": ["nope"]}}
    ) is None
    assert content_detection.configured_metric(
        {"content_monitoring": {"metric_names": ["like_count"]}}
    ) == "like_count"
    assert content_detection.configured_metric(
        {"content_monitoring": {"metric_names": ["like_count", "share_count"]}}
    ) is None


@pytest.mark.asyncio
async def test_final_detection_waits_for_window_and_upserts_result(db_session):
    account = _account(
        raw_profile={"monitoring_rules": {"reference_work_count": 5, "hot_multiple": 2}}
    )
    db_session.add(account)
    await db_session.flush()
    published = datetime(2026, 8, 1, tzinfo=UTC)

    prior = []
    for index in range(5):
        work, snapshot = await _work_with_snapshot(
            db_session,
            account,
            work_id=f"prior-{index}",
            published_at=published - timedelta(days=index + 1),
            collected_at=published + timedelta(days=8),
            likes=100,
        )
        prior.append((work, snapshot))

    current, early = await _work_with_snapshot(
        db_session,
        account,
        work_id="current",
        published_at=published,
        collected_at=published + timedelta(days=1),
        likes=600,
    )
    assert await content_detection.evaluate_final_snapshot(
        db_session, snapshot_id=early.id, metric_names=["like_count"]
    ) is None

    final = EngagementSnapshot(
        work_id=current.id,
        collected_at=published + timedelta(days=7),
        like_count=600,
        metrics={"like_count": 600},
        raw_data={},
    )
    db_session.add(final)
    await db_session.flush()
    detection = await content_detection.evaluate_final_snapshot(
        db_session, snapshot_id=final.id, metric_names=["like_count"]
    )
    assert detection is not None
    assert detection.status == "very_hot"
    assert detection.detector_version == content_detection.DETECTOR_VERSION
    assert detection.evidence["configured_reference_work_count"] == 5
    assert detection.evidence["sample_shortfall"] == 0

    same = await content_detection.evaluate_final_snapshot(
        db_session, snapshot_id=final.id, metric_names=["like_count"]
    )
    assert same.id == detection.id

    with pytest.raises(ValueError, match="Unsupported"):
        await content_detection.evaluate_final_snapshot(
            db_session, snapshot_id=final.id, metric_names=["invalid"]
        )


@pytest.mark.asyncio
async def test_detection_handles_missing_entities_and_recalculates(db_session):
    assert await content_detection.evaluate_final_snapshot(
        db_session, snapshot_id="missing"
    ) is None
    assert await content_detection.evaluate_observed_snapshot(
        db_session, snapshot_id="missing"
    ) is None
    with pytest.raises(ValueError, match="Unsupported"):
        await content_detection.evaluate_observed_snapshot(
            db_session, snapshot_id="missing", metric_names=["invalid"]
        )

    account = _account(external_account_id="recalculate")
    db_session.add(account)
    await db_session.flush()
    unpublished, _ = await _work_with_snapshot(
        db_session,
        account,
        work_id="unpublished",
        published_at=None,
        collected_at=datetime(2026, 8, 1, tzinfo=UTC),
        likes=100,
    )
    published, snapshot = await _work_with_snapshot(
        db_session,
        account,
        work_id="published",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        collected_at=datetime(2026, 8, 2, tzinfo=UTC),
        likes=100,
    )
    assert await content_detection.evaluate_observed_snapshot(
        db_session, snapshot_id=(await db_session.get(EngagementSnapshot, snapshot.id)).id,
        metric_names=["like_count"],
    ) is not None
    assert await content_detection.recalculate_account_detections(
        db_session, account.id, metric_names=["like_count"]
    ) == 1
    assert unpublished.id != published.id


@pytest.mark.asyncio
async def test_detection_returns_none_for_unpublished_and_handles_missing_metrics(db_session):
    account = _account(external_account_id="detection-missing")
    db_session.add(account)
    await db_session.flush()
    unpublished, unpublished_snapshot = await _work_with_snapshot(
        db_session,
        account,
        work_id="unpublished-detection",
        published_at=None,
        collected_at=datetime(2026, 8, 1, tzinfo=UTC),
        likes=10,
    )
    assert await content_detection.evaluate_final_snapshot(
        db_session, snapshot_id=unpublished_snapshot.id
    ) is None
    assert content_detection._snapshot_metrics(None, ["like_count", "share_count"]) == {
        "like_count": None,
        "share_count": None,
    }

    current, snapshot = await _work_with_snapshot(
        db_session,
        account,
        work_id="missing-current-metric",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        collected_at=datetime(2026, 8, 8, tzinfo=UTC),
        likes=None,
    )
    detection = await content_detection.evaluate_final_snapshot(
        db_session, snapshot_id=snapshot.id, metric_names=["like_count"]
    )
    assert detection is not None
    assert detection.status == "insufficient_data"
    assert detection.current_value is None
    assert detection.evidence["sample_shortfall"] == 20
    assert current.id != unpublished.id

    no_snapshot = ContentWork(
        account_id=account.id,
        external_work_id="no-snapshot",
        published_at=datetime(2026, 8, 2, tzinfo=UTC),
        first_seen_at=datetime(2026, 8, 2, tzinfo=UTC),
        last_seen_at=datetime(2026, 8, 2, tzinfo=UTC),
        raw_identity={},
    )
    db_session.add(no_snapshot)
    await db_session.flush()
    assert await content_detection.recalculate_account_detections(
        db_session, account.id, metric_names=["like_count"]
    ) == 1


@pytest.mark.asyncio
async def test_monitor_service_status_filters_and_pagination(db_session):
    account = _account(external_account_id="monitor-filter")
    source = DataSource(
        name="monitor-source", channel_type="opencli", channel_config={"site": "douyin"}
    )
    db_session.add_all([account, source])
    await db_session.flush()
    work, snapshot = await _work_with_snapshot(
        db_session,
        account,
        work_id="observing-work",
        published_at=datetime(2026, 8, 2, tzinfo=UTC),
        collected_at=datetime(2026, 8, 3, tzinfo=UTC),
        likes=10,
        source_id=source.id,
    )
    db_session.add(
        DetectionResult(
            work_id=work.id,
            snapshot_id=snapshot.id,
            detector_version="v1",
            metric_name="like_count",
            status="hot",
            enters_analysis=True,
            priority_analysis=False,
            relative_multiple=3.0,
            evidence={},
        )
    )
    no_snapshot = ContentWork(
        account_id=account.id,
        source_id=source.id,
        external_work_id="not-seen",
        published_at=None,
        first_seen_at=datetime(2026, 8, 4, tzinfo=UTC),
        last_seen_at=datetime(2026, 8, 4, tzinfo=UTC),
        raw_identity={},
    )
    no_snapshot.snapshots = []
    no_snapshot.detections = []
    db_session.add(no_snapshot)
    await db_session.flush()

    assert content_monitor_service.work_status(no_snapshot) == "not_seen"
    with pytest.raises(ValueError, match="Unsupported"):
        await content_monitor_service.list_monitored_works(db_session, queue="bad")
    rows, total = await content_monitor_service.list_monitored_works(
        db_session,
        status="hot",
        source_id=source.id,
        account_id=account.id,
        queue="normal",
        page=1,
        limit=1,
    )
    assert total == 1
    assert rows[0].id == work.id

    # A normal-queue query excludes works that are not analysis candidates.
    normal_rows, normal_total = await content_monitor_service.list_monitored_works(
        db_session, queue="normal", status="not_seen", page=1, limit=20
    )
    assert normal_rows == []
    assert normal_total == 0


@pytest.mark.asyncio
async def test_final_baseline_skips_unpublished_prior_work(db_session):
    account = _account(external_account_id="unpublished-baseline")
    db_session.add(account)
    await db_session.flush()
    unpublished, _ = await _work_with_snapshot(
        db_session,
        account,
        work_id="prior-without-publish-date",
        published_at=None,
        collected_at=datetime(2026, 8, 1, tzinfo=UTC),
        likes=100,
    )
    current, current_snapshot = await _work_with_snapshot(
        db_session,
        account,
        work_id="current-final",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        collected_at=datetime(2026, 8, 8, tzinfo=UTC),
        likes=100,
    )
    detection = await content_detection.evaluate_final_snapshot(
        db_session, snapshot_id=current_snapshot.id, metric_names=["like_count"]
    )
    assert detection is not None
    assert detection.status == "insufficient_data"
    assert unpublished.id != current.id


@pytest.mark.asyncio
async def test_monitor_service_keeps_early_hot_result_when_final_recheck_is_insufficient(
    db_session,
):
    account = _account(external_account_id="early-hot")
    db_session.add(account)
    await db_session.flush()
    work, snapshot = await _work_with_snapshot(
        db_session,
        account,
        work_id="early-hot-work",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        collected_at=datetime(2026, 8, 2, tzinfo=UTC),
        likes=500,
    )
    db_session.add_all(
        [
            DetectionResult(
                work_id=work.id,
                snapshot_id=snapshot.id,
                detector_version="v1-observed",
                metric_name="like_count",
                status="very_hot",
                enters_analysis=True,
                priority_analysis=True,
                relative_multiple=6.0,
                evidence={},
            ),
            DetectionResult(
                work_id=work.id,
                snapshot_id=snapshot.id,
                detector_version="v1-final-7d",
                metric_name="like_count",
                status="insufficient_data",
                enters_analysis=False,
                priority_analysis=False,
                evidence={},
            ),
        ]
    )
    await db_session.flush()

    rows, total = await content_monitor_service.list_monitored_works(
        db_session, queue="priority"
    )

    assert total == 1
    assert rows[0].id == work.id
    assert content_monitor_service.work_status(rows[0]) == "very_hot"
