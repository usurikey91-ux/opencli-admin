from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.common import ApiResponse, PaginationMeta
from backend.schemas.content_monitor import (
    ContentSnapshotRead,
    DetectionRead,
    MonitoredWorkRead,
)
from backend.services import content_monitor_service

router = APIRouter(prefix="/content-monitor", tags=["content-monitor"])


def _to_read(work) -> MonitoredWorkRead:
    detection = content_monitor_service._latest_detection(work)
    snapshot = content_monitor_service._latest_snapshot(work)
    return MonitoredWorkRead(
        id=work.id,
        account_id=work.account_id,
        platform=work.account.platform,
        account_handle=work.account.handle,
        account_display_name=work.account.display_name,
        external_work_id=work.external_work_id,
        url=work.url,
        title=work.title,
        content=work.content,
        author=work.author,
        published_at=work.published_at,
        first_seen_at=work.first_seen_at,
        last_seen_at=work.last_seen_at,
        status=content_monitor_service.work_status(work),
        latest_snapshot=ContentSnapshotRead.model_validate(snapshot) if snapshot else None,
        detection=DetectionRead.model_validate(detection) if detection else None,
    )

@router.get("/works", response_model=ApiResponse[list[MonitoredWorkRead]])
async def list_monitored_works(
    status: Optional[str] = Query(None),
    queue: str = Query("all", pattern="^(all|normal|priority)$"),
    source_id: Optional[str] = None,
    account_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        works, total = await content_monitor_service.list_monitored_works(
            db,
            status=status,
            queue=queue,
            source_id=source_id,
            account_id=account_id,
            page=page,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ApiResponse.ok(
        data=[_to_read(work) for work in works],
        meta=PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            pages=max(1, -(-total // limit)),
        ),
    )
