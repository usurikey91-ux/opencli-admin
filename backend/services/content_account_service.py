from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.content_monitor import ContentAccount
from backend.schemas.content_account import ContentAccountImportItem


async def import_accounts(
    session: AsyncSession, items: list[ContentAccountImportItem]
) -> tuple[list[ContentAccount], int]:
    """Create or refresh account identities without starting collection."""
    imported: list[ContentAccount] = []
    created = 0
    for item in items:
        result = await session.execute(
            select(ContentAccount).where(
                ContentAccount.platform == item.platform.lower(),
                ContentAccount.external_account_id == item.external_account_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            account = ContentAccount(
                platform=item.platform.lower(),
                external_account_id=item.external_account_id,
                handle=item.handle,
                display_name=item.display_name or item.handle,
                profile_url=item.profile_url,
                raw_profile={},
            )
            session.add(account)
            await session.flush()
            created += 1
        else:
            account.handle = item.handle or account.handle
            account.display_name = item.display_name or account.display_name or item.handle
            account.profile_url = item.profile_url or account.profile_url
        imported.append(account)
    return imported, created


async def list_accounts(
    session: AsyncSession,
    *,
    platform: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[ContentAccount], int]:
    query = select(ContentAccount).order_by(ContentAccount.updated_at.desc())
    count_query = select(func.count()).select_from(ContentAccount)
    if platform:
        query = query.where(ContentAccount.platform == platform.lower())
        count_query = count_query.where(ContentAccount.platform == platform.lower())
    total = (await session.execute(count_query)).scalar_one()
    rows = await session.execute(query.offset((page - 1) * limit).limit(limit))
    return list(rows.scalars().all()), total
