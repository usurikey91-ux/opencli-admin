"""Persist stable works and time-series snapshots from generic collected items."""

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.content_monitor import ContentAccount, ContentWork, EngagementSnapshot
from backend.models.source import DataSource
from backend.monitoring_policy import evaluate_snapshot_policy


_ACCOUNT_ID_KEYS = (
    "author_id",
    "user_id",
    "uid",
    "sec_uid",
    "channel_id",
    "account_id",
    "owner_id",
)
_ACCOUNT_HANDLE_KEYS = ("author", "author_name", "username", "user_name", "channel", "creator")
_WORK_ID_KEYS = ("work_id", "post_id", "note_id", "video_id", "aweme_id", "bvid", "id")
_PROFILE_URL_KEYS = ("profile_url", "author_url", "user_url", "channel_url")

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "view_count": ("view_count", "views", "play_count", "plays", "view"),
    "like_count": ("like_count", "likes", "liked_count", "digg_count", "like"),
    "comment_count": ("comment_count", "comments", "reply_count", "comment"),
    "favorite_count": (
        "favorite_count",
        "favorites",
        "favourite_count",
        "collect_count",
        "collects",
        "bookmark_count",
    ),
    "share_count": ("share_count", "shares", "repost_count", "forward_count", "share"),
}

_NUMBER_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "千": 1_000,
    "万": 10_000,
    "亿": 100_000_000,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mapping_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lower_map = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        value = lower_map.get(key)
        if value not in (None, "") and not isinstance(value, (dict, list)):
            return value
    return None


def parse_public_count(value: Any) -> int | None:
    """Parse common public counter formats such as 1.2K, 3万, or 4,500."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not isinstance(value, str):
        return None

    text = value.strip().lower().replace(",", "").replace("+", "")
    if not text or text in {"-", "--", "n/a", "null", "none"}:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([kmb千万亿]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    if number < 0:
        return None
    multiplier = _NUMBER_MULTIPLIERS.get(match.group(2), 1)
    return int(number * multiplier)


def extract_metrics(raw: dict[str, Any]) -> dict[str, int | None]:
    nested_metrics = next(
        (
            raw.get(key)
            for key in ("metrics", "statistics", "stats", "engagement")
            if isinstance(raw.get(key), dict)
        ),
        {},
    )
    return {
        target: parse_public_count(
            _mapping_value(raw, aliases) or _mapping_value(nested_metrics, aliases)
        )
        for target, aliases in _METRIC_ALIASES.items()
    }


def _parse_published_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _source_platform(source: DataSource) -> str:
    site = source.channel_config.get("site") if isinstance(source.channel_config, dict) else None
    return str(site or source.channel_type or "unknown").lower()


def _account_identity(
    raw: dict[str, Any],
    normalized: dict[str, Any],
    source: DataSource,
    task_parameters: dict[str, Any] | None = None,
) -> tuple[str, str | None, str | None, str | None]:
    author_data = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    external_id = _mapping_value(raw, _ACCOUNT_ID_KEYS) or _mapping_value(
        author_data, ("id", "uid", "user_id", "channel_id", "account_id")
    )
    handle = (
        _mapping_value(raw, _ACCOUNT_HANDLE_KEYS)
        or _mapping_value(author_data, ("name", "username", "handle", "nickname"))
        or normalized.get("author")
    )
    profile_url = _mapping_value(raw, _PROFILE_URL_KEYS) or _mapping_value(
        author_data, ("profile_url", "url")
    )

    config = source.channel_config if isinstance(source.channel_config, dict) else {}
    config_args = config.get("args") if isinstance(config.get("args"), dict) else {}
    task_parameters = task_parameters if isinstance(task_parameters, dict) else {}
    configured_account = next(
        (
            task_parameters.get(key) or config_args.get(key) or config.get(key)
            for key in (
                "account_id",
                "external_account_id",
                "user_id",
                "uid",
                "sec_uid",
                "username",
                "user",
                "channel",
            )
            if task_parameters.get(key) or config_args.get(key) or config.get(key)
        ),
        None,
    )
    external_id = external_id or configured_account or handle or source.id
    # A source name describes the collector, not the creator. Keep it out of
    # the account identity so a collection run cannot overwrite a user-facing
    # account label when the adapter omits author metadata.
    display_name = str(handle) if handle not in (None, "") else None
    return (
        str(external_id),
        str(handle) if handle else None,
        display_name,
        str(profile_url) if profile_url else None,
    )


def _work_identity(raw: dict[str, Any], normalized: dict[str, Any], content_hash: str) -> str:
    external_id = _mapping_value(raw, _WORK_ID_KEYS)
    if external_id not in (None, ""):
        return str(external_id)
    url = normalized.get("url")
    if url:
        return "url:" + hashlib.sha256(str(url).encode()).hexdigest()
    return "hash:" + content_hash


async def store_content_snapshots(
    session: AsyncSession,
    task_id: str,
    source_id: str,
    normalized_triples: list[tuple[dict, dict, str]],
) -> int:
    """Store one snapshot per work for this collection task.

    The generic collected-record table remains first-seen/deduplicated. This
    time-series table deliberately records the same work again on later tasks.
    """
    if not normalized_triples:
        return 0

    source = await session.get(DataSource, source_id)
    if source is None:
        return 0

    # A shared source serves multiple benchmark accounts. The task carries the
    # account identity, while the public adapter's row may intentionally omit
    # author fields. Read it once so rows are attached to the account that
    # triggered this collection instead of falling back to the source itself.
    from backend.models.task import CollectionTask

    task = await session.get(CollectionTask, task_id)
    task_parameters = task.parameters if task and isinstance(task.parameters, dict) else {}

    platform = _source_platform(source)
    account_cache: dict[str, ContentAccount] = {}
    work_cache: dict[tuple[str, str], ContentWork] = {}
    task_work_ids: set[str] = set()
    new_snapshots: list[EngagementSnapshot] = []
    stored = 0
    observed_now = _utcnow()

    for raw, normalized, content_hash in normalized_triples:
        account_external_id, handle, display_name, profile_url = _account_identity(
            raw, normalized, source, task_parameters
        )
        account = account_cache.get(account_external_id)
        if account is None:
            result = await session.execute(
                select(ContentAccount).where(
                    ContentAccount.platform == platform,
                    ContentAccount.external_account_id == account_external_id,
                )
            )
            account = result.scalar_one_or_none()
            if account is None:
                account = ContentAccount(
                    source_id=source_id,
                    platform=platform,
                    external_account_id=account_external_id,
                    handle=handle,
                    display_name=display_name,
                    profile_url=profile_url,
                    raw_profile={},
                )
                session.add(account)
                await session.flush()
            else:
                account.source_id = source_id
                account.handle = handle or account.handle
                account.display_name = display_name or account.display_name
                account.profile_url = profile_url or account.profile_url
            account_cache[account_external_id] = account

        external_work_id = _work_identity(raw, normalized, content_hash)
        work_key = (account.id, external_work_id)
        work = work_cache.get(work_key)
        is_new_work = False
        if work is None:
            result = await session.execute(
                select(ContentWork).where(
                    ContentWork.account_id == account.id,
                    ContentWork.external_work_id == external_work_id,
                )
            )
            work = result.scalar_one_or_none()
            published_raw = normalized.get("published_at") or None
            if work is None:
                is_new_work = True
                work = ContentWork(
                    account_id=account.id,
                    source_id=source_id,
                    external_work_id=external_work_id,
                    url=normalized.get("url") or None,
                    title=normalized.get("title") or None,
                    content=normalized.get("content") or None,
                    author=normalized.get("author") or None,
                    published_at=_parse_published_at(published_raw),
                    published_at_raw=str(published_raw) if published_raw else None,
                    first_seen_at=observed_now,
                    last_seen_at=observed_now,
                    raw_identity={"content_hash": content_hash},
                )
                session.add(work)
                await session.flush()
            else:
                work.source_id = source_id
                work.url = normalized.get("url") or work.url
                work.title = normalized.get("title") or work.title
                work.content = normalized.get("content") or work.content
                work.author = normalized.get("author") or work.author
                work.published_at_raw = (
                    str(published_raw) if published_raw else work.published_at_raw
                )
                work.published_at = _parse_published_at(published_raw) or work.published_at
                work.last_seen_at = observed_now
            work_cache[work_key] = work

        if work.id in task_work_ids:
            continue
        task_work_ids.add(work.id)

        existing = await session.execute(
            select(EngagementSnapshot.id).where(
                EngagementSnapshot.work_id == work.id,
                EngagementSnapshot.task_id == task_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        if not is_new_work:
            latest_snapshot = await session.execute(
                select(EngagementSnapshot.collected_at)
                .where(EngagementSnapshot.work_id == work.id)
                .order_by(EngagementSnapshot.collected_at.desc())
                .limit(1)
            )
            latest_snapshot_at = latest_snapshot.scalar_one_or_none()
            if latest_snapshot_at is not None:
                if work.published_at is not None:
                    policy = evaluate_snapshot_policy(
                        published_at=work.published_at,
                        last_snapshot_at=latest_snapshot_at,
                        now=observed_now,
                    )
                    if not policy.due:
                        continue
                # When the platform omits publication time, keep every scheduled
                # observation instead of inventing a timestamp or losing the
                # snapshot. The work remains flagged as published_at_missing and
                # final heat evaluation stays disabled until a real date appears.

        metrics = extract_metrics(raw)
        if work.published_at is None:
            account.collection_status = "published_at_missing"
            account.last_error_code = "published_at_missing"
            account.last_error_message = f"Work {work.external_work_id} has no usable published_at"
        elif not any(value is not None for value in metrics.values()):
            account.collection_status = "missing_metric"
            account.last_error_code = "missing_metric"
            account.last_error_message = (
                f"Work {work.external_work_id} has no supported public metrics"
            )
        snapshot = EngagementSnapshot(
            work_id=work.id,
            task_id=task_id,
            collected_at=observed_now,
            metrics={key: value for key, value in metrics.items() if value is not None},
            raw_data=raw,
            **metrics,
        )
        session.add(snapshot)
        new_snapshots.append(snapshot)
        stored += 1

    await session.flush()
    from backend.services.content_detection import (
        configured_metrics,
        evaluate_final_snapshot,
        evaluate_observed_snapshot,
    )

    metric_names = configured_metrics(source.channel_config)
    if metric_names:
        for snapshot in new_snapshots:
            await evaluate_observed_snapshot(
                session,
                snapshot_id=snapshot.id,
                metric_names=metric_names,
            )
            await evaluate_final_snapshot(
                session,
                snapshot_id=snapshot.id,
                metric_names=metric_names,
            )
    return stored
