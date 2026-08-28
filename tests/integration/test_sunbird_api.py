import pytest


@pytest.mark.asyncio
async def test_sunbird_accounts_can_be_registered_without_claiming_collection(client):
    response = await client.post(
        "/api/v1/integrations/sunbird/accounts",
        json={"platform": "douyin", "external_account_id": "sec-api-1", "display_name": "creator"},
    )
    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["account"]["collection_status"] == "unconfigured"
    assert payload["schedule"] is None

    listing = await client.get("/api/v1/integrations/sunbird/accounts")
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] == 1


@pytest.mark.asyncio
async def test_sunbird_check_rejects_account_without_collection_binding(client):
    created = await client.post(
        "/api/v1/integrations/sunbird/accounts",
        json={"platform": "douyin", "external_account_id": "sec-api-2"},
    )
    account_id = created.json()["data"]["account"]["id"]

    response = await client.post(f"/api/v1/integrations/sunbird/accounts/{account_id}/check")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_sunbird_works_endpoint_starts_empty(client):
    response = await client.get("/api/v1/integrations/sunbird/works")
    assert response.status_code == 200
    assert response.json()["data"] == []
