
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.common import ApiResponse, PaginationMeta
from backend.schemas.content_account import (
    ContentAccountImportItem,
    ContentAccountImportRequest,
    ContentAccountLinkImportRequest,
    ContentAccountRead,
)
from backend.services import content_account_service, douyin_import_service

router = APIRouter(prefix="/content-monitor/accounts", tags=["content-monitor"])


@router.get("", response_model=ApiResponse[list[ContentAccountRead]])
async def list_content_accounts(
    platform: str | None = Query(None),
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
            "accounts": [
                ContentAccountRead.model_validate(account).model_dump()
                for account in accounts
            ],
        }
    )


@router.post("/import-link", response_model=ApiResponse[dict], status_code=201)
async def import_content_account_link(
    body: ContentAccountLinkImportRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """Resolve a Douyin work share link and save its verified author identity."""
    try:
        resolved = await douyin_import_service.resolve_douyin_share(body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except douyin_import_service.DouyinImportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    items = [
        ContentAccountImportItem(
            platform=resolved["platform"],
            external_account_id=resolved["external_account_id"],
            handle=resolved.get("handle"),
            display_name=resolved.get("display_name"),
            profile_url=resolved.get("profile_url"),
        )
    ]
    accounts, created = await content_account_service.import_accounts(db, items)
    account = accounts[0]
    account.raw_profile = {
        **(account.raw_profile or {}),
        "verified_by": "douyin_public_work",
        "available_metrics": resolved["available_metrics"],
        "missing_metrics": resolved["missing_metrics"],
        "sample_work": resolved["sample_work"],
    }
    await db.flush()
    return ApiResponse.ok(
        {
            "created": bool(created),
            "account": ContentAccountRead.model_validate(account).model_dump(),
            "sample_work": resolved["sample_work"],
            "available_metrics": resolved["available_metrics"],
            "missing_metrics": resolved["missing_metrics"],
        }
    )
