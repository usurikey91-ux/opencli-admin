import pytest

from backend.models.content_monitor import ContentAccount
from backend.schemas.content_account import ContentAccountImportItem
from backend.services.content_account_service import import_accounts


@pytest.mark.asyncio
async def test_import_accounts_is_idempotent(db_session):
    items = [
        ContentAccountImportItem(
            platform="Example",
            external_account_id="creator-1",
            handle="creator",
            profile_url="https://example.com/creator",
        )
    ]
    first, created_first = await import_accounts(db_session, items)
    second, created_second = await import_accounts(
        db_session,
        [items[0].model_copy(update={"display_name": "Creator updated"})],
    )
    assert created_first == 1
    assert created_second == 0
    assert first[0].id == second[0].id
    assert second[0].display_name == "Creator updated"
    assert (await db_session.get(ContentAccount, first[0].id)).platform == "example"
