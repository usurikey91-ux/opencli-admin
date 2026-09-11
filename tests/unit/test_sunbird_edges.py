"""Focused branch coverage for the Sunbird/content-workbench contract."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.models.content_monitor import ContentAccount, ContentWork, DetectionResult, EngagementSnapshot
from backend.models.schedule import CronSchedule
from backend.models.source import DataSource
from backend.schemas.sunbird import SunbirdAccountBindRequest
from backend.services import sunbird_integration_service as service


async def _source(db_session, *, name="edge-source", platform="douyin", channel_type="opencli", enabled=True, command="user-videos"):
    source = DataSource(
        name=name,
        channel_type=channel_type,
        channel_config={"site": platform, "command": command} if command is not None else {"site": platform},
        enabled=enabled,
    )
    db_session.add(source)
    await db_session.flush()
    return source


@pytest.mark.asyncio
async def test_apply_rules_and_toggle_schedule_state(db_session):
    account, schedule, _ = await service.bind_account(
        db_session,
        SunbirdAccountBindRequest(
            platform="douyin", external_account_id="rules-account", display_name="Creator"
        ),
    )
    normalized = await service.apply_monitoring_rules(
        db_session,
        account,
        {
            "reference_work_count": 8,
            "hot_multiple": 2.5,
            "very_hot_multiple": 6,
            "interval_hours": 12,
            "inherit_global": False,
        },
    )
    assert normalized["reference_work_count"] == 8
    assert account.collection_args["limit"] == 9
    assert schedule.cron_expression == "0 */12 * * *"
    assert schedule.parameters["sec_uid"] == account.external_account_id

    await service.set_monitoring_enabled(db_session, account, False)
    assert account.collection_status == "paused"
    assert schedule.enabled is False
    await service.set_monitoring_enabled(db_session, account, True)
    assert account.collection_status == "ready"
    assert schedule.enabled is True

    with pytest.raises(ValueError, match="Unsupported inspection interval"):
        await service.apply_monitoring_rules(db_session, account, {"interval_hours": 3})
    with pytest.raises(ValueError, match="Very-hot"):
        await service.apply_monitoring_rules(
            db_session, account, {"hot_multiple": 8, "very_hot_multiple": 7}
        )


@pytest.mark.asyncio
async def test_platform_source_selection_and_legacy_upgrade(db_session):
    legacy = await _source(
        db_session,
        name=service.LEGACY_DOUYIN_USER_VIDEOS_SOURCE_NAME,
        platform="legacy",
        command="legacy-command",
    )
    legacy.channel_config["args"] = {"with_comments": True}
    await db_session.flush()
    upgraded = await service._get_or_create_douyin_source(db_session)
    assert upgraded.id == legacy.id
    assert upgraded.name == service.DOUYIN_USER_VIDEOS_SOURCE_NAME

    other = await _source(db_session, name="bilibili-source", platform="bilibili", command="hot")
    selected = await service._get_platform_source(db_session, "bilibili")
    assert selected.id == other.id
    assert await service._get_platform_source(db_session, "missing-platform") is None

    assert upgraded.channel_config["account_argument"] == "sec_uid"
    assert upgraded.channel_config["args"]["with_comments"] is False


@pytest.mark.asyncio
async def test_bind_validation_and_check_task_lifecycle(db_session):
    non_opencli = await _source(db_session, name="api-source", channel_type="api", platform="bilibili")
    with pytest.raises(ValueError, match="OpenCLI"):
        await service.bind_account(
            db_session,
            SunbirdAccountBindRequest(
                platform="bilibili", external_account_id="api-account", source_id=non_opencli.id
            ),
        )

    with pytest.raises(ValueError, match="Source not found"):
        await service.bind_account(
            db_session,
            SunbirdAccountBindRequest(
                platform="douyin", external_account_id="missing-source", source_id="missing"
            ),
        )

    no_command = await _source(
        db_session, name="no-command", platform="xiaohongshu", command=None
    )
    with pytest.raises(ValueError, match="command is required"):
        await service.bind_account(
            db_session,
            SunbirdAccountBindRequest(
                platform="xiaohongshu", external_account_id="missing-command", source_id=no_command.id
            ),
        )

    source = await _source(db_session, name="command-source", platform="bilibili", command="hot")
    with pytest.raises(ValueError, match="must match"):
        await service.bind_account(
            db_session,
            SunbirdAccountBindRequest(
                platform="bilibili",
                external_account_id="mismatch-command",
                source_id=source.id,
                command="other",
            ),
        )

    account, schedule, _ = await service.bind_account(
        db_session,
        SunbirdAccountBindRequest(
            platform="bilibili",
            external_account_id="check-account",
            source_id=source.id,
            enabled=False,
        ),
    )
    assert account.collection_status == "unconfigured"
    assert schedule is not None and schedule.enabled is False
    with pytest.raises(ValueError, match="paused"):
        await service.create_check_task(db_session, account)

    account.collection_enabled = True
    account.collection_status = "ready"
    task = await service.create_check_task(db_session, account)
    assert task.source_id == source.id
    assert task.parameters["external_account_id"] == account.external_account_id
    assert account.collection_status == "checking"


@pytest.mark.asyncio
async def test_collection_result_and_account_schedule_helpers(db_session):
    account = ContentAccount(platform="douyin", external_account_id="result-account", raw_profile={})
    db_session.add(account)
    await db_session.flush()
    assert await service._account_schedule(db_session, account) is None

    await service.update_collection_result(db_session, "missing-account", success=False, error="no account")
    await service.update_collection_result(db_session, account.id, success=False, error="login required")
    assert account.collection_status == "login_required"
    assert account.last_error_code == "login_required"
    account.collection_status = "missing_metric"
    await service.update_collection_result(db_session, account.id, success=True)
    assert account.collection_status == "missing_metric"
    assert account.last_success_at is not None
    account.collection_status = "checking"
    await service.update_collection_result(db_session, account.id, success=True)
    assert account.collection_status == "ok"


def test_profile_name_cleanup_and_error_mapping():
    assert service._clean_profile_name(None) is None
    assert service._clean_profile_name("创作者的个人空间") == "创作者"
    assert service._clean_profile_name("创作者 - 快手") == "创作者"
    assert service._clean_profile_name("抖音") is None
    assert service._clean_profile_name("验证码") is None
    assert service.error_code("未登录") == "login_required"
    assert service.error_code("cookie expired") == "login_expired"
    assert service.error_code("published_at missing") == "published_at_missing"
    assert service.error_code("statistics missing") == "missing_metric"
    assert service.error_code("author account invalid") == "account_invalid"
    assert service.error_code("network down") == "collection_failed"


@pytest.mark.asyncio
async def test_profile_name_resolution_fallbacks(db_session, monkeypatch):
    original_opencli_resolver = service._resolve_profile_name_with_opencli
    assert await service.resolve_profile_display_name("douyin", None) is None

    class FakeResponse:
        text = "<html><title>Creator\u7684\u6296\u97f3 - \u6296\u97f3</title></html>"

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url):
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    assert await service.resolve_profile_display_name(
        "douyin", "https://www.douyin.com/user/profile"
    ) == "Creator"

    class ErrorClient(FakeClient):
        async def get(self, _url):
            raise service.httpx.HTTPError("blocked")

    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_kwargs: ErrorClient())
    async def fallback_none(_url):
        return None

    monkeypatch.setattr(service, "_resolve_profile_name_with_opencli", fallback_none)
    assert await service.resolve_profile_display_name(
        "douyin", "https://www.douyin.com/user/profile"
    ) is None

    monkeypatch.setattr(service.shutil, "which", lambda _name: None)
    assert await service._resolve_profile_name_with_opencli("https://example.com") is None

    monkeypatch.setattr(service.shutil, "which", lambda _name: "opencli")
    monkeypatch.setattr(service, "_resolve_profile_name_with_opencli", original_opencli_resolver)
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout='[{"title":"Creator\\u7684\\u6296\\u97f3 - \\u6296\\u97f3"}]'
        ),
    )
    assert await service._resolve_profile_name_with_opencli("https://example.com") == "Creator"


@pytest.mark.asyncio
async def test_work_contract_branches_and_filters(db_session):
    account = ContentAccount(
        platform="douyin", external_account_id="contract-account", display_name="Creator", raw_profile={}
    )
    db_session.add(account)
    await db_session.flush()
    no_data = SimpleNamespace(
        account=account,
        external_work_id="no-data",
        url=None,
        title=None,
        content=None,
        published_at=None,
        snapshots=[],
        detections=[],
    )
    assert service.work_contract(no_data)["status"] == "not_seen"

    work = SimpleNamespace(
        account=account,
        external_work_id="contract-work",
        url=None,
        title=None,
        content=None,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    snapshot = SimpleNamespace(
        collected_at=datetime(2026, 8, 2, tzinfo=UTC),
        metrics={"like_count": 300},
    )
    work.snapshots = [snapshot]
    early = DetectionResult(
        work_id="contract-work",
        snapshot_id="contract-snapshot",
        detector_version="v1-observed",
        metric_name="like_count",
        relative_multiple=4,
        status="hot",
        enters_analysis=True,
        priority_analysis=False,
        evidence={"stage": "early"},
    )
    final_pending = DetectionResult(
        work_id="contract-work",
        snapshot_id="contract-snapshot",
        detector_version="v1-final-7d",
        metric_name="like_count",
        relative_multiple=None,
        status="insufficient_data",
        enters_analysis=False,
        priority_analysis=False,
        evidence={"stage": "pending"},
    )
    db_session.add_all([early, final_pending])
    await db_session.flush()
    work.detections = [early, final_pending]
    contract = service.work_contract(work)
    assert contract["status"] == "hot"
    assert contract["priority"] is False
    assert contract["latest_public_metrics"] == {"like_count": 300}
    assert contract["final_public_metrics"] == {}
