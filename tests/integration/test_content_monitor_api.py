import pytest


@pytest.mark.asyncio
async def test_content_monitor_works_endpoint_returns_empty_page(client):
    response = await client.get("/api/v1/content-monitor/works", params={"queue": "priority"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == []
    assert payload["meta"]["total"] == 0

