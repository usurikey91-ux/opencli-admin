"""Small, replaceable contract between Sunbird and OpenCLI Admin."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.content_monitor import ContentAccount, ContentWork
from backend.models.schedule import CronSchedule
from backend.models.source import DataSource
from backend.schemas.sunbird import SunbirdAccountBindRequest
from backend.services import content_account_service, task_service

DOUYIN_USER_VIDEOS_SOURCE_NAME = "Sunbird · Douyin public works"
DOUYIN_USER_VIDEOS_CONFIG = {
    "site": "douyin",
    "command": "user-videos",
    "format": "json",
    "args": {
        "limit": 20,
        "with_comments": True,
        "comment_limit": 10,
    },
    "content_monitoring": {},
}


def error_code(message: str | None) -> str:
    text = (message or "").lower()
    if "login required" in text or "请登录" in text or "未登录" in text:
        return "login_required"
    if "login" in text or "登录" in text or "cookie" in text:
        return "login_expired"
    if "published" in text or "发布时间" in text:
        return "published_at_missing"
    if "metric" in text or "字段" in text or "statistics" in text:
        return "missing_metric"
    if "account" in text or "用户" in text or "作者" in text:
        return "account_invalid"
    return "collection_failed"


async def _get_or_create_douyin_source(session: AsyncSession) -> DataSource:
    """Provision the one verified OpenCLI command needed by the MVP.

    ``opencli douyin user-videos <sec_uid>`` was checked against the installed
    CLI help. Its returned fields still need a real-account run before they are
    treated as guaranteed platform data.
    """
    result = await session.execute(
        select(DataSource).where(DataSource.name == DOUYIN_USER_VIDEOS_SOURCE_NAME)
    )
    source = result.scalar_one_or_none()
    if source is None:
        source = DataSource(
            name=DOUYIN_USER_VIDEOS_SOURCE_NAME,
            description="Sunbird benchmark account巡检 via OpenCLI douyin user-videos",
            channel_type="opencli",
            channel_config=DOUYIN_USER_VIDEOS_CONFIG.copy(),
            tags=["sunbird", "benchmark", "douyin"],
            enabled=True,
        )
        session.add(source)
        await session.flush()
    return source


async def bind_account(
    session: AsyncSession, body: SunbirdAccountBindRequest
) -> tuple[ContentAccount, CronSchedule | None, bool]:
    items, created = await content_account_service.import_accounts(session, [body])
    account = items[0]
    schedule = None
    source_id = body.source_id
    if not source_id and body.platform.lower() == "douyin":
        source = await _get_or_create_douyin_source(session)
    elif source_id:
        source = await session.get(DataSource, source_id)
        if source is None:
            raise ValueError("Source not found")
    else:
        source = None

    if source:
        if source.channel_type != "opencli":
            raise ValueError("Sunbird benchmark collection currently requires an opencli source")
        configured_command = source.channel_config.get("command")
        source_command = body.command or configured_command
        if not source_command:
            raise ValueError("command is required when source_id is provided")
        if configured_command and body.command and body.command != configured_command:
            raise ValueError("command must match the bound OpenCLI source")
        account.collection_source_id = source.id
        account.collection_command = source_command
        account.collection_args = {
            **(source.channel_config.get("args") or {}),
            **body.args,
            "sec_uid": account.external_account_id,
        }
        account.collection_enabled = body.enabled
        account.collection_status = "ready" if body.enabled else "unconfigured"
        account.last_error_code = None
        account.last_error_message = None

        # JSON path is supported by SQLite and PostgreSQL; this keeps binding idempotent.
        result = await session.execute(
            select(CronSchedule).where(CronSchedule.source_id == source.id)
        )
        schedule = next(
            (
                item
                for item in result.scalars().all()
                if isinstance(item.parameters, dict)
                and item.parameters.get("sunbird_account_id") == account.id
            ),
            None,
        )
        params = {
            "sunbird_account_id": account.id,
            "sec_uid": account.external_account_id,
            **(account.collection_args or {}),
        }
        if schedule is None:
            schedule = CronSchedule(
                source_id=source.id,
                name=f"Sunbird benchmark {account.display_name or account.external_account_id}",
                cron_expression="0 */4 * * *",
                timezone="UTC",
                parameters=params,
                enabled=body.enabled,
            )
            session.add(schedule)
        else:
            schedule.enabled = body.enabled
            schedule.parameters = params
        await session.flush()
    return account, schedule, bool(created)


async def get_account(session: AsyncSession, account_id: str) -> ContentAccount | None:
    return await session.get(ContentAccount, account_id)


async def create_check_task(session: AsyncSession, account: ContentAccount):
    if not account.collection_source_id or not account.collection_command:
        raise ValueError("account collection is not configured")
    account.collection_status = "checking"
    account.last_collection_at = datetime.now(UTC)
    account.last_error_code = None
    account.last_error_message = None
    params = {
        **(account.collection_args or {}),
        "sunbird_account_id": account.id,
        "sec_uid": account.external_account_id,
    }
    task = await task_service.create_task(
        session,
        source_id=account.collection_source_id,
        trigger_type="manual",
        parameters=params,
        priority=5,
    )
    await session.flush()
    return task


async def update_collection_result(
    session: AsyncSession, account_id: str, *, success: bool, error: str | None = None
) -> None:
    account = await session.get(ContentAccount, account_id)
    if account is None:
        return
    account.last_collection_at = datetime.now(UTC)
    if success:
        # A technically successful request can still be unusable for monitoring.
        # The snapshotter records these data-quality states before this callback.
        if account.collection_status not in {"missing_metric", "published_at_missing"}:
            account.collection_status = "ok"
            account.last_error_code = None
            account.last_error_message = None
        account.last_success_at = account.last_collection_at
    else:
        account.collection_status = error_code(error)
        account.last_error_code = account.collection_status
        account.last_error_message = error


def work_contract(work: ContentWork) -> dict[str, Any]:
    snapshots = sorted(work.snapshots, key=lambda item: item.collected_at)
    latest = snapshots[-1] if snapshots else None
    detection = max(work.detections, key=lambda item: item.evaluated_at, default=None)
    return {
        "account": {
            "id": work.account.id,
            "platform": work.account.platform,
            "external_account_id": work.account.external_account_id,
            "handle": work.account.handle,
            "display_name": work.account.display_name,
        },
        "platform": work.account.platform,
        "external_work_id": work.external_work_id,
        "url": work.url,
        "title": work.title,
        "content": work.content,
        "published_at": work.published_at,
        "latest_public_metrics": latest.metrics if latest else {},
        "final_public_metrics": latest.metrics if latest and detection else {},
        "relative_multiple": detection.relative_multiple if detection else None,
        "status": detection.status if detection else ("observing" if latest else "not_seen"),
        "priority": bool(detection and detection.priority_analysis),
        "evidence": detection.evidence if detection else {},
    }


async def list_work_contracts(
    session: AsyncSession,
    *,
    status: str | None = None,
    priority: bool | None = None,
    account_id: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    result = await session.execute(
        select(ContentWork)
        .options(
            selectinload(ContentWork.account),
            selectinload(ContentWork.snapshots),
            selectinload(ContentWork.detections),
        )
        .order_by(ContentWork.published_at.desc().nullslast(), ContentWork.created_at.desc())
    )
    contracts = [work_contract(work) for work in result.scalars().unique().all()]
    if status:
        contracts = [item for item in contracts if item["status"] == status]
    if priority is not None:
        contracts = [item for item in contracts if item["priority"] == priority]
    if account_id:
        contracts = [item for item in contracts if item["account"]["id"] == account_id]
    total = len(contracts)
    offset = (page - 1) * limit
    return contracts[offset : offset + limit], total
