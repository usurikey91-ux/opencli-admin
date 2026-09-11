"""HTTP coverage for content-monitor account and work endpoints."""

from datetime import datetime, timezone

import pytest

from backend.models.content_monitor import ContentAccount, ContentWork, DetectionResult, EngagementSnapshot
from backend.models.source import DataSource


@pytest.mark.asyncio
async def test_content_accounts_import_list_and_platform_filter(client):
    response = await client.post(
        "/api/v1/content-monitor/accounts/import",
        json={
            "items": [
                {
                    "platform": "Example",
                    "external_account_id": "account-api-1",
                    "handle": "creator",
                    "display_name": "Creator",
                },
                {
                    "platform": "Other",
                    "external_account_id": "account-api-2",
                },
            ]
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["created"] == 2

    updated = await client.post(
        "/api/v1/content-monitor/accounts/import",
        json={
            "items": [
                {
                    "platform": "example",
                    "external_account_id": "account-api-1",
                    "display_name": "Updated creator",
                }
            ]
        },
    )
    assert updated.status_code == 201
    assert updated.json()["data"]["updated"] == 1

    listing = await client.get(
        "/api/v1/content-monitor/accounts",
        params={"platform": "EXAMPLE", "page": 1, "limit": 1},
    )
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] == 1
    assert listing.json()["data"][0]["display_name"] == "Updated creator"


@pytest.mark.asyncio
async def test_content_account_link_import_maps_expected_errors(client, monkeypatch):
    from backend.api.v1 import content_accounts

    async def invalid(_text):
        raise ValueError("bad link")

    monkeypatch.setattr(content_accounts.douyin_import_service, "resolve_douyin_share", invalid)
    response = await client.post(
        "/api/v1/content-monitor/accounts/import-link", json={"text": "bad"}
    )
    assert response.status_code == 400

    async def failed(_text):
        raise content_accounts.douyin_import_service.DouyinImportError("opencli failed")

    monkeypatch.setattr(content_accounts.douyin_import_service, "resolve_douyin_share", failed)
    response = await client.post(
        "/api/v1/content-monitor/accounts/import-link", json={"text": "https://v.douyin.com/x/"}
    )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_content_monitor_work_endpoint_serializes_snapshot_and_detection(client, db_session):
    account = ContentAccount(
        platform="douyin",
        external_account_id="account-work-api",
        handle="creator",
        display_name="Creator",
        raw_profile={},
    )
    source = DataSource(
        name="monitor-api-source",
        channel_type="opencli",
        channel_config={"site": "douyin", "command": "user-videos"},
    )
    db_session.add_all([account, source])
    await db_session.flush()
    collected_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
    work = ContentWork(
        account_id=account.id,
        source_id=source.id,
        external_work_id="work-api-1",
        url="https://douyin.com/video/work-api-1",
        title="API work",
        content="body",
        author="Creator",
        published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        first_seen_at=collected_at,
        last_seen_at=collected_at,
        raw_identity={},
    )
    db_session.add(work)
    await db_session.flush()
    snapshot = EngagementSnapshot(
        work_id=work.id,
        collected_at=collected_at,
        like_count=300,
        metrics={"like_count": 300},
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
            current_value=300,
            baseline_value=100,
            baseline_size=20,
            baseline_missing_count=0,
            relative_multiple=3,
            hot_multiple=3,
            very_hot_multiple=5,
            enters_analysis=True,
            priority_analysis=False,
            status="hot",
            evidence={"used_metrics": ["like_count"]},
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/v1/content-monitor/works",
        params={"status": "hot", "source_id": source.id, "account_id": account.id},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 1
    item = payload["data"][0]
    assert item["title"] == "API work"
    assert item["latest_snapshot"]["like_count"] == 300
    assert item["detection"]["status"] == "hot"


@pytest.mark.asyncio
async def test_content_monitor_endpoint_maps_service_queue_errors(client, monkeypatch):
    from backend.api.v1 import content_monitor

    async def invalid_queue(*_args, **_kwargs):
        raise ValueError("Unsupported analysis queue: bad")

    monkeypatch.setattr(content_monitor.content_monitor_service, "list_monitored_works", invalid_queue)
    response = await client.get("/api/v1/content-monitor/works", params={"queue": "all"})
    assert response.status_code == 400
    assert "Unsupported analysis queue" in response.json()["detail"]
