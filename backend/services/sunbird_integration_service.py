"""Small, replaceable contract between the content workbench and OpenCLI Admin."""

from datetime import UTC, datetime
import asyncio
import html
import json
import re
import shutil
import subprocess
import tempfile
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.content_monitor import ContentAccount, ContentWork
from backend.models.schedule import CronSchedule
from backend.models.source import DataSource
from backend.schemas.sunbird import SunbirdAccountBindRequest
from backend.services import content_account_service, content_detection, task_service

DOUYIN_USER_VIDEOS_SOURCE_NAME = "Content Workbench · Douyin public works"
LEGACY_DOUYIN_USER_VIDEOS_SOURCE_NAME = "Sunbird · Douyin public works"
DOUYIN_USER_VIDEOS_CONFIG = {
    "site": "douyin",
    "command": "user-videos",
    "account_argument": "sec_uid",
    "format": "json",
    "args": {
        "limit": 20,
        # 评论接口更容易受平台登录态限制；热度 MVP 先保证作品和公开互动数据入库。
        "with_comments": False,
    },
    "content_monitoring": {},
}

_INTERVAL_CRON = {
    1: "0 * * * *",
    2: "0 */2 * * *",
    4: "0 */4 * * *",
    8: "0 */8 * * *",
    12: "0 */12 * * *",
    24: "0 0 * * *",
}


def account_monitoring_rules(account: ContentAccount) -> dict[str, Any]:
    return content_detection.monitoring_rules_for_account(account)


async def _account_schedule(
    session: AsyncSession, account: ContentAccount
) -> CronSchedule | None:
    if not account.collection_source_id:
        return None
    result = await session.execute(
        select(CronSchedule).where(CronSchedule.source_id == account.collection_source_id)
    )
    return next(
        (
            item
            for item in result.scalars().all()
            if isinstance(item.parameters, dict)
            and item.parameters.get("sunbird_account_id") == account.id
        ),
        None,
    )


async def apply_monitoring_rules(
    session: AsyncSession, account: ContentAccount, rules: dict[str, Any]
) -> dict[str, Any]:
    normalized = {**content_detection.DEFAULT_MONITORING_RULES, **rules}
    # Validation normally happens in the request schema. Clamp again here so
    # older stored values cannot break collection or classification.
    normalized["reference_work_count"] = max(5, min(50, int(normalized["reference_work_count"])))
    normalized["hot_multiple"] = max(1.5, min(10.0, float(normalized["hot_multiple"])))
    normalized["very_hot_multiple"] = max(2.0, min(20.0, float(normalized["very_hot_multiple"])))
    normalized["interval_hours"] = int(normalized["interval_hours"])
    normalized["inherit_global"] = bool(normalized.get("inherit_global", True))
    if normalized["interval_hours"] not in _INTERVAL_CRON:
        raise ValueError("Unsupported inspection interval")
    if normalized["very_hot_multiple"] <= normalized["hot_multiple"]:
        raise ValueError("Very-hot multiple must be greater than hot multiple")
    account.raw_profile = {
        **(account.raw_profile or {}),
        "monitoring_rules": normalized,
    }
    account.collection_args = {
        **(account.collection_args or {}),
        # Internal collection includes the candidate plus N possible prior works.
        "limit": normalized["reference_work_count"] + 1,
    }
    schedule = await _account_schedule(session, account)
    if schedule:
        schedule.cron_expression = _INTERVAL_CRON[normalized["interval_hours"]]
        schedule.parameters = {
            **(schedule.parameters or {}),
            **account.collection_args,
            "sunbird_account_id": account.id,
            "external_account_id": account.external_account_id,
        }
        if account.platform.lower() == "douyin":
            schedule.parameters = {
                **schedule.parameters,
                "sec_uid": account.external_account_id,
            }
    await session.flush()
    return normalized


async def set_monitoring_enabled(
    session: AsyncSession, account: ContentAccount, enabled: bool
) -> None:
    account.collection_enabled = bool(enabled)
    account.collection_status = "ready" if enabled else "paused"
    account.last_error_code = None
    account.last_error_message = None
    schedule = await _account_schedule(session, account)
    if schedule:
        schedule.enabled = bool(enabled)
    await session.flush()


def _clean_profile_name(value: str | None) -> str | None:
    name = html.unescape(str(value or "")).strip()
    if "的个人空间" in name:
        name = name.split("的个人空间", 1)[0].strip()
    for suffix in (
        "的个人空间_哔哩哔哩_bilibili",
        "的个人空间-哔哩哔哩",
        " - 快手",
        "- 快手",
        " - 小红书",
        "- 小红书",
        "的抖音 - 抖音",
        "的抖音-抖音",
        "的抖音",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    if (
        not name
        or name in {"抖音", "快手", "小红书", "哔哩哔哩"}
        or "验证码" in name
        or "你的生活兴趣社区" in name
    ):
        return None
    return name[:255]


async def _resolve_profile_name_with_opencli(profile_url: str) -> str | None:
    executable = shutil.which("opencli.cmd") or shutil.which("opencli")
    if not executable:
        return None

    def run() -> str | None:
        with tempfile.TemporaryDirectory(prefix="sunbird-profile-") as workdir:
            try:
                completed = subprocess.run(
                    [executable, "web", "read", "--url", profile_url, "-f", "json"],
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
        if completed.returncode != 0:
            return None
        try:
            rows = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None
        return _clean_profile_name(rows[0].get("title"))

    return await asyncio.to_thread(run)


async def resolve_profile_display_name(platform: str, profile_url: str | None) -> str | None:
    """Best-effort public profile nickname lookup; collection still works if blocked."""
    if not profile_url:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=8,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            response = await client.get(profile_url)
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return await _resolve_profile_name_with_opencli(profile_url)

    text = response.text
    # Douyin and Xiaohongshu expose the public nickname in hydrated JSON.
    for match in re.finditer(r'"nickname"\s*:\s*"((?:\\.|[^"\\])*)"', text):
        try:
            candidate = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            candidate = match.group(1)
        cleaned = _clean_profile_name(candidate)
        if cleaned:
            return cleaned

    for title in re.finditer(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL):
        cleaned = _clean_profile_name(title.group(1))
        if cleaned:
            return cleaned
    return await _resolve_profile_name_with_opencli(profile_url)


async def _get_platform_source(session: AsyncSession, platform: str) -> DataSource | None:
    """Find an enabled OpenCLI source registered for a platform.

    The Douyin source remains auto-provisioned because it is the verified MVP adapter.
    Other platforms are intentionally discovered from the user's configured sources,
    keeping this integration independent from a fixed platform list.
    """
    if platform == "douyin":
        return await _get_or_create_douyin_source(session)
    result = await session.execute(
        select(DataSource)
        .where(DataSource.channel_type == "opencli", DataSource.enabled.is_(True))
        .order_by(DataSource.created_at.asc())
    )
    for source in result.scalars().all():
        config = source.channel_config if isinstance(source.channel_config, dict) else {}
        site = str(config.get("site") or "").strip().lower()
        if site == platform:
            return source
    return None


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
        select(DataSource).where(
            DataSource.name.in_([
                DOUYIN_USER_VIDEOS_SOURCE_NAME,
                LEGACY_DOUYIN_USER_VIDEOS_SOURCE_NAME,
            ])
        )
    )
    source = result.scalars().first()
    if source is None:
        source = DataSource(
            name=DOUYIN_USER_VIDEOS_SOURCE_NAME,
            description="Content workbench benchmark collection via OpenCLI douyin user-videos",
            channel_type="opencli",
            channel_config=DOUYIN_USER_VIDEOS_CONFIG.copy(),
            tags=["content-workbench", "benchmark", "douyin"],
            enabled=True,
        )
        session.add(source)
        await session.flush()
    else:
        # Upgrade legacy source branding and configuration in place so existing
        # installations do not create a duplicate source.
        source.name = DOUYIN_USER_VIDEOS_SOURCE_NAME
        source.description = "Content workbench benchmark collection via OpenCLI douyin user-videos"
        source.tags = ["content-workbench", "benchmark", "douyin"]
        # Upgrade sources created before ``account_argument`` was introduced so
        # existing local installations do not duplicate the account ID as options.
        config = dict(source.channel_config or {})
        if config.get("account_argument") != "sec_uid":
            config["account_argument"] = "sec_uid"
        args = dict(config.get("args") or {})
        if args.get("with_comments") is True:
            args["with_comments"] = False
        config["args"] = args
        source.channel_config = config
    return source


async def bind_account(
    session: AsyncSession, body: SunbirdAccountBindRequest
) -> tuple[ContentAccount, CronSchedule | None, bool]:
    existing_result = await session.execute(
        select(ContentAccount).where(
            ContentAccount.platform == body.platform.lower(),
            ContentAccount.external_account_id == body.external_account_id,
        )
    )
    existing_account = existing_result.scalar_one_or_none()
    existing_profile = (
        existing_account.raw_profile
        if existing_account and isinstance(existing_account.raw_profile, dict)
        else {}
    )
    custom_name = bool(existing_profile.get("display_name_custom"))
    if custom_name:
        body = body.model_copy(update={"display_name": None})
    elif not body.display_name and body.profile_url:
        resolved_name = await resolve_profile_display_name(body.platform, body.profile_url)
        if resolved_name:
            body = body.model_copy(update={"display_name": resolved_name})
    items, created = await content_account_service.import_accounts(session, [body])
    account = items[0]
    existing_rules = existing_profile.get("monitoring_rules")
    requested_rules = (
        {**content_detection.DEFAULT_MONITORING_RULES, **existing_rules}
        if existing_account is not None and isinstance(existing_rules, dict)
        else (
            body.monitoring_rules.model_dump()
            if body.monitoring_rules is not None
            else account_monitoring_rules(account)
        )
    )
    account.raw_profile = {
        **(account.raw_profile or {}),
        "monitoring_rules": requested_rules,
    }
    if not account.display_name or account.display_name in {
        LEGACY_DOUYIN_USER_VIDEOS_SOURCE_NAME,
        DOUYIN_USER_VIDEOS_SOURCE_NAME,
    }:
        platform_label = "抖音" if account.platform.lower() == "douyin" else account.platform
        account.display_name = f"{platform_label} · {account.external_account_id[-8:]}"
    schedule = None
    source_id = body.source_id
    platform = body.platform.lower()
    if not source_id:
        source = await _get_platform_source(session, platform)
    elif source_id:
        source = await session.get(DataSource, source_id)
        if source is None:
            raise ValueError("Source not found")
    else:
        source = None

    if source:
        if source.channel_type != "opencli":
            raise ValueError("Benchmark collection currently requires an OpenCLI source")
        configured_command = source.channel_config.get("command")
        source_command = body.command or configured_command
        if not source_command:
            raise ValueError("command is required when source_id is provided")
        if configured_command and body.command and body.command != configured_command:
            raise ValueError("command must match the bound OpenCLI source")
        binding_changed = bool(created) or any(
            (
                account.collection_source_id != source.id,
                account.collection_command != source_command,
                account.collection_enabled != body.enabled,
            )
        )
        account.collection_source_id = source.id
        account.collection_command = source_command
        collection_args = {
            **(source.channel_config.get("args") or {}),
            **body.args,
            "external_account_id": account.external_account_id,
            "limit": requested_rules["reference_work_count"] + 1,
        }
        if platform == "douyin":
            collection_args["sec_uid"] = account.external_account_id
        account.collection_args = collection_args
        account.collection_enabled = body.enabled
        if not body.enabled:
            account.collection_status = "unconfigured"
            account.last_error_code = None
            account.last_error_message = None
        elif binding_changed or account.collection_status == "unconfigured":
            account.collection_status = "ready"
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
            "external_account_id": account.external_account_id,
            **(account.collection_args or {}),
        }
        if platform == "douyin":
            params["sec_uid"] = account.external_account_id
        if schedule is None:
            schedule = CronSchedule(
                source_id=source.id,
                name=f"Content benchmark {account.display_name or account.external_account_id}",
                cron_expression=_INTERVAL_CRON[requested_rules["interval_hours"]],
                timezone="UTC",
                parameters=params,
                enabled=body.enabled,
            )
            session.add(schedule)
        else:
            schedule.name = f"Content benchmark {account.display_name or account.external_account_id}"
            schedule.enabled = body.enabled
            schedule.parameters = params
            schedule.cron_expression = _INTERVAL_CRON[requested_rules["interval_hours"]]
        await session.flush()
    return account, schedule, bool(created)


async def get_account(session: AsyncSession, account_id: str) -> ContentAccount | None:
    return await session.get(ContentAccount, account_id)


async def remove_account(
    session: AsyncSession, account: ContentAccount
) -> dict[str, Any]:
    """Permanently remove an account and all of its monitoring history."""
    result = await session.execute(
        select(CronSchedule).where(CronSchedule.source_id == account.collection_source_id)
    )
    schedules = [
        item
        for item in result.scalars().all()
        if isinstance(item.parameters, dict)
        and item.parameters.get("sunbird_account_id") == account.id
    ]
    work_count = await session.scalar(
        select(func.count()).select_from(ContentWork).where(ContentWork.account_id == account.id)
    )
    for schedule in schedules:
        await session.delete(schedule)
    await session.delete(account)
    await session.flush()
    return {
        "account_id": account.id,
        "purged": True,
        "history_preserved": False,
        "works_affected": int(work_count or 0),
    }


async def list_bound_accounts(
    session: AsyncSession,
    *,
    platform: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[ContentAccount], int]:
    """List benchmark account identities, including unsupported/unconfigured ones.

    An account without a matching source must remain visible so the UI can show
    an explicit ``unconfigured`` state instead of silently hiding the account.
    """
    filters = []
    if platform:
        filters.append(ContentAccount.platform == platform.lower())
    query = (
        select(ContentAccount)
        .where(*filters)
        .order_by(ContentAccount.updated_at.desc())
    )
    count_query = select(func.count()).select_from(ContentAccount).where(*filters)
    total = (await session.execute(count_query)).scalar_one()
    rows = await session.execute(query.offset((page - 1) * limit).limit(limit))
    return list(rows.scalars().all()), total


async def create_check_task(session: AsyncSession, account: ContentAccount):
    if not account.collection_source_id or not account.collection_command:
        raise ValueError("account collection is not configured")
    if not account.collection_enabled:
        raise ValueError("account monitoring is paused")
    account.collection_status = "checking"
    account.last_collection_at = datetime.now(UTC)
    account.last_error_code = None
    account.last_error_message = None
    params = {
        **(account.collection_args or {}),
        "sunbird_account_id": account.id,
        "external_account_id": account.external_account_id,
    }
    if account.platform.lower() == "douyin":
        params["sec_uid"] = account.external_account_id
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
    # Prefer a valid seven-day decision when one exists. If the final pass is
    # still insufficient (for example, a historical work lacks a final
    # snapshot), keep an earlier hot candidate visible instead of letting an
    # incomplete re-check erase the analysis queue entry.
    final_detections = [
        item for item in work.detections if item.detector_version == "v1-final-7d"
    ]
    final_detection = max(final_detections, key=lambda item: item.evaluated_at, default=None)
    if final_detection and final_detection.status not in {"insufficient_data", "pending_final_window"}:
        detection = final_detection
    else:
        early_candidates = [
            item
            for item in work.detections
            if item.detector_version == "v1-observed"
            and item.status in {"hot", "very_hot"}
        ]
        detection = max(
            early_candidates or work.detections,
            key=lambda item: item.evaluated_at,
            default=None,
        )
    relative_multiple = detection.relative_multiple if detection else None
    if relative_multiple is not None:
        if relative_multiple >= 5.0:
            current_status = "very_hot"
            current_priority = True
        elif relative_multiple >= 3.0:
            current_status = "hot"
            current_priority = False
        elif detection and detection.status in {"hot", "very_hot"}:
            current_status = "observing"
            current_priority = False
        else:
            current_status = detection.status if detection else "observing"
            current_priority = False
    else:
        current_status = detection.status if detection else ("observing" if latest else "not_seen")
        current_priority = bool(detection and detection.priority_analysis)
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
        "relative_multiple": relative_multiple,
        "status": current_status,
        "priority": current_priority,
        "evidence": detection.evidence if detection else {},
    }


async def list_work_contracts(
    session: AsyncSession,
    *,
    status: str | None = None,
    priority: bool | None = None,
    account_id: str | None = None,
    platform: str | None = None,
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
    if platform:
        normalized_platform = platform.strip().lower()
        contracts = [item for item in contracts if item["platform"] == normalized_platform]
    total = len(contracts)
    offset = (page - 1) * limit
    return contracts[offset : offset + limit], total
