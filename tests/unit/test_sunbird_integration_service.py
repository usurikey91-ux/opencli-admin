from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from backend.models.content_monitor import (
    ContentAccount,
    ContentWork,
    DetectionResult,
    EngagementSnapshot,
)
from backend.models.schedule import CronSchedule
from backend.models.source import DataSource
from backend.schemas.sunbird import SunbirdAccountBindRequest
from backend.services import sunbird_integration_service as service


@pytest.mark.asyncio
async def test_bind_account_creates_one_four_hour_schedule(db_session):
    source = DataSource(
        name="Douyin creator works",
        channel_type="opencli",
        channel_config={"site": "douyin", "command": "user-posts"},
        tags=["sunbird"],
    )
    db_session.add(source)
    await db_session.flush()
    body = SunbirdAccountBindRequest(
        platform="douyin",
        external_account_id="sec-1",
        display_name="creator",
        source_id=source.id,
        command="user-posts",
        args={"limit": 20},
    )

    account, schedule, created = await service.bind_account(db_session, body)
    again, same_schedule, created_again = await service.bind_account(db_session, body)

    assert created is True
    assert created_again is False
    assert again.id == account.id
    assert same_schedule.id == schedule.id
    assert schedule.cron_expression == "0 */4 * * *"
    assert account.collection_status == "ready"
    assert account.collection_args["sec_uid"] == "sec-1"
    assert await db_session.scalar(select(func.count()).select_from(CronSchedule)) == 1


@pytest.mark.asyncio
async def test_douyin_bind_provisions_the_verified_default_source(db_session):
    account, schedule, created = await service.bind_account(
        db_session,
        SunbirdAccountBindRequest(
            platform="douyin",
            external_account_id="sec-default-source",
            display_name="creator",
        ),
    )

    assert created is True
    assert account.collection_enabled is True
    assert account.collection_command == "user-videos"
    assert account.collection_args["sec_uid"] == "sec-default-source"
    assert schedule is not None
    source = await db_session.get(DataSource, account.collection_source_id)
    assert source.channel_config["site"] == "douyin"
    assert source.channel_config["command"] == "user-videos"
    assert schedule.parameters["sec_uid"] == "sec-default-source"


@pytest.mark.asyncio
async def test_unconfigured_account_cannot_start_check(db_session):
    account = ContentAccount(platform="douyin", external_account_id="sec-2", raw_profile={})
    db_session.add(account)
    await db_session.flush()

    with pytest.raises(ValueError, match="not configured"):
        await service.create_check_task(db_session, account)


@pytest.mark.asyncio
async def test_list_bound_accounts_hides_unconfigured_accounts(db_session):
    bound, _, _ = await service.bind_account(
        db_session,
        SunbirdAccountBindRequest(
            platform="douyin",
            external_account_id="sec-bound",
            display_name="bound creator",
        ),
    )
    db_session.add(
        ContentAccount(
            platform="douyin",
            external_account_id="sec-unconfigured",
            display_name="unconfigured creator",
            raw_profile={},
        )
    )
    await db_session.flush()

    accounts, total = await service.list_bound_accounts(db_session)

    assert total == 1
    assert [account.id for account in accounts] == [bound.id]


@pytest.mark.asyncio
async def test_idempotent_rebind_preserves_successful_collection_status(db_session):
    body = SunbirdAccountBindRequest(
        platform="douyin",
        external_account_id="sec-successful",
        display_name="successful creator",
    )
    account, _, _ = await service.bind_account(db_session, body)
    account.collection_status = "ok"
    account.last_success_at = datetime.now(UTC)
    await db_session.flush()

    rebound, _, created = await service.bind_account(db_session, body)

    assert created is False
    assert rebound.collection_status == "ok"
    assert rebound.last_success_at is not None


@pytest.mark.asyncio
async def test_work_contract_exposes_public_evidence_for_sunbird(db_session):
    account = ContentAccount(platform="douyin", external_account_id="sec-3", raw_profile={})
    db_session.add(account)
    await db_session.flush()
    work = ContentWork(
        account_id=account.id,
        external_work_id="work-1",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        raw_identity={},
    )
    db_session.add(work)
    await db_session.flush()
    snapshot = EngagementSnapshot(work_id=work.id, metrics={"like_count": 200}, raw_data={})
    db_session.add(snapshot)
    await db_session.flush()
    db_session.add(
        DetectionResult(
            work_id=work.id,
            snapshot_id=snapshot.id,
            detector_version="v2",
            metric_name="composite",
            baseline_size=20,
            baseline_missing_count=0,
            relative_multiple=5.5,
            enters_analysis=True,
            priority_analysis=True,
            status="very_hot",
            evidence={"used_metrics": ["like_count"]},
        )
    )
    await db_session.flush()

    rows, total = await service.list_work_contracts(db_session, status="very_hot")

    assert total == 1
    assert rows[0]["latest_public_metrics"] == {"like_count": 200}
    assert rows[0]["final_public_metrics"] == {"like_count": 200}
    assert rows[0]["priority"] is True
    assert rows[0]["relative_multiple"] == 5.5


def test_collection_error_codes_are_stable():
    assert service.error_code("login required") == "login_required"
    assert service.error_code("Cookie expired") == "login_expired"
    assert service.error_code("发布时间字段缺失") == "published_at_missing"
    assert service.error_code("statistics field missing") == "missing_metric"
    assert service.error_code("network timeout") == "collection_failed"
