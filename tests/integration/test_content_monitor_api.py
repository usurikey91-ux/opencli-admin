import pytest

from backend.api.v1 import content_accounts


@pytest.mark.asyncio
async def test_content_monitor_works_endpoint_returns_empty_page(client):
    response = await client.get("/api/v1/content-monitor/works", params={"queue": "priority"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == []
    assert payload["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_import_douyin_share_resolves_and_saves_account(client, monkeypatch):
    async def fake_resolve(_text):
        return {
            "platform": "douyin",
            "external_account_id": "sec-user-1",
            "handle": "82849915426",
            "display_name": "Vittorioo",
            "profile_url": "https://www.douyin.com/user/sec-user-1",
            "sample_work": {
                "external_work_id": "7667379238509042118",
                "url": "https://www.douyin.com/video/7667379238509042118",
                "metrics": {
                    "view_count": 0,
                    "like_count": 13591,
                    "comment_count": 643,
                    "favorite_count": 1959,
                    "share_count": 1899,
                },
            },
            "available_metrics": [
                "like_count",
                "comment_count",
                "favorite_count",
                "share_count",
            ],
            "missing_metrics": ["view_count"],
        }

    monkeypatch.setattr(
        content_accounts.douyin_import_service,
        "resolve_douyin_share",
        fake_resolve,
    )
    response = await client.post(
        "/api/v1/content-monitor/accounts/import-link",
        json={"text": "https://v.douyin.com/2Eiu7qmLsA8/"},
    )
    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["created"] is True
    assert payload["account"]["display_name"] == "Vittorioo"
    assert payload["account"]["external_account_id"] == "sec-user-1"
    assert payload["available_metrics"] == [
        "like_count",
        "comment_count",
        "favorite_count",
        "share_count",
    ]
