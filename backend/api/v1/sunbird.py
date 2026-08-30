from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.content_monitor import ContentWork
from backend.models.source import DataSource
from backend.schemas.common import ApiResponse, PaginationMeta
from backend.schemas.sunbird import (
    SunbirdAccountBindRequest,
    SunbirdAccountRead,
    SunbirdCheckRead,
    SunbirdWorkRead,
)
from backend.services import sunbird_integration_service as service

router = APIRouter(prefix="/integrations/sunbird", tags=["sunbird-integration"])


@router.get("/platforms", response_model=ApiResponse[list[dict]])
async def list_sunbird_platforms(db: AsyncSession = Depends(get_db)) -> ApiResponse:
    """List platform adapters exposed by configured OpenCLI sources."""
    result = await db.execute(
        select(DataSource)
        .where(DataSource.channel_type == "opencli", DataSource.enabled.is_(True))
        .order_by(DataSource.created_at.asc())
    )
    platforms: dict[str, dict] = {}
    for source in result.scalars().all():
        config = source.channel_config if isinstance(source.channel_config, dict) else {}
        platform = str(config.get("site") or "").strip().lower()
        if not platform:
            continue
        platforms.setdefault(
            platform,
            {
                "id": platform,
                "label": platform,
                "source_id": source.id,
                "command": config.get("command"),
                "status": "configured",
            },
        )
    return ApiResponse.ok(list(platforms.values()))


@router.post("/accounts", response_model=ApiResponse[dict], status_code=201)
async def bind_sunbird_account(
    body: SunbirdAccountBindRequest, db: AsyncSession = Depends(get_db)
) -> ApiResponse:
    try:
        account, schedule, created = await service.bind_account(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return ApiResponse.ok(
        {
            "created": created,
            "account": SunbirdAccountRead.model_validate(account).model_dump(),
            "schedule": (
                {
                    "id": schedule.id,
                    "cron_expression": schedule.cron_expression,
                    "enabled": schedule.enabled,
                }
                if schedule
                else None
            ),
        }
    )


@router.get("/accounts", response_model=ApiResponse[list[SunbirdAccountRead]])
async def list_sunbird_accounts(
    platform: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    accounts, total = await service.list_bound_accounts(
        db, platform=platform, page=page, limit=limit
    )
    return ApiResponse.ok(
        data=[SunbirdAccountRead.model_validate(account) for account in accounts],
        meta=PaginationMeta(total=total, page=page, limit=limit, pages=max(1, -(-total // limit))),
    )


@router.post(
    "/accounts/{account_id}/check", response_model=ApiResponse[SunbirdCheckRead], status_code=202
)
async def check_sunbird_account(account_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    account = await service.get_account(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        task = await service.create_check_task(db, account)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    from backend.executor import get_executor

    dispatch = await get_executor().dispatch_collection(task.id, task.parameters)
    return ApiResponse.ok(
        SunbirdCheckRead(
            account_id=account.id,
            task_id=dispatch.get("task_id", task.id),
            status="dispatched",
            source_id=task.source_id,
        )
    )


@router.get("/works", response_model=ApiResponse[list[SunbirdWorkRead]])
async def list_sunbird_works(
    status: str | None = None,
    priority: bool | None = None,
    account_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    contracts, total = await service.list_work_contracts(
        db, status=status, priority=priority, account_id=account_id, page=page, limit=limit
    )
    return ApiResponse.ok(
        data=[SunbirdWorkRead.model_validate(item) for item in contracts],
        meta=PaginationMeta(total=total, page=page, limit=limit, pages=max(1, -(-total // limit))),
    )


@router.get("/works/{work_id}", response_model=ApiResponse[SunbirdWorkRead])
async def get_sunbird_work(work_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse:
    result = await db.execute(
        select(ContentWork)
        .where(ContentWork.id == work_id)
        .options(
            selectinload(ContentWork.account),
            selectinload(ContentWork.snapshots),
            selectinload(ContentWork.detections),
        )
    )
    work = result.scalar_one_or_none()
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return ApiResponse.ok(SunbirdWorkRead.model_validate(service.work_contract(work)))
