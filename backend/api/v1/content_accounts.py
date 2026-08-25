from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.common import ApiResponse, PaginationMeta
from backend.schemas.content_account import (
    ContentAccountImportRequest,
    ContentAccountRead,
)
from backend.services import content_account_service

router = APIRouter(prefix="/content-monitor/accounts", tags=["content-monitor"])


@router.get("", response_model=ApiResponse[list[ContentAccountRead]])
async def list_content_accounts(
    platform: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    accounts, total = await content_account_service.list_accounts(
        db, platform=platform, page=page, limit=limit
    )
    return ApiResponse.ok(
        data=[ContentAccountRead.model_validate(account) for account in accounts],
        meta=PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            pages=max(1, -(-total // limit)),
        ),
    )


@router.post("/import", response_model=ApiResponse[dict], status_code=201)
async def import_content_accounts(
    body: ContentAccountImportRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    accounts, created = await content_account_service.import_accounts(db, body.items)
    return ApiResponse.ok(
        {
            "created": created,
            "updated": len(accounts) - created,
            "total": len(accounts),
            "accounts": [ContentAccountRead.model_validate(account).model_dump() for account in accounts],
        }
    )

