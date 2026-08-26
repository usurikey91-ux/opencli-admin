"""Resolve a Douyin share link into a verified benchmark-account identity."""

import asyncio
import json
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from backend.channels.opencli_output import parse_opencli_json

_DOUYIN_URL_RE = re.compile(r"https?://(?:[\w-]+\.)?douyin\.com/[^\s<>\]\[\"']+", re.I)
_ALLOWED_HOSTS = {"douyin.com", "www.douyin.com", "v.douyin.com"}
_OPENCLI_NAME = os.environ.get("OPENCLI_BIN", "opencli")
_OPENCLI_BIN = (
    shutil.which(_OPENCLI_NAME)
    or (shutil.which(f"{_OPENCLI_NAME}.cmd") if os.name == "nt" else None)
    or _OPENCLI_NAME
)
_OPENCLI_TIMEOUT = int(os.environ.get("OPENCLI_TIMEOUT", "120"))


def _opencli_command() -> list[str]:
    """Bypass the npm .cmd shim on Windows so JS arguments keep '&' intact."""
    if os.name == "nt" and str(_OPENCLI_BIN).lower().endswith(".cmd"):
        node = shutil.which("node")
        main = (
            Path(_OPENCLI_BIN).parent
            / "node_modules"
            / "@jackwener"
            / "opencli"
            / "dist"
            / "src"
            / "main.js"
        )
        if node and main.is_file():
            return [node, str(main)]
    return [str(_OPENCLI_BIN)]


class DouyinImportError(RuntimeError):
    """A public Douyin link could not be resolved through the local session."""


def extract_douyin_url(text: str) -> str:
    match = _DOUYIN_URL_RE.search(text or "")
    if not match:
        raise ValueError("没有找到有效的抖音链接")
    return match.group(0).rstrip(".,;:!?，。；：！？)）")


def _validate_douyin_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        raise ValueError("只支持 douyin.com 的公开链接")
    return url


def _aweme_id_from_url(url: str) -> str:
    match = re.search(r"/video/(\d+)", urlparse(url).path)
    if not match:
        raise ValueError("当前请粘贴包含具体作品的抖音分享链接")
    return match.group(1)


async def _resolve_share_url(url: str) -> str:
    _validate_douyin_url(url)
    if "/video/" in urlparse(url).path:
        return url
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/125 Safari/537.36"
        )
    }
    def resolve() -> str:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=20) as response:  # noqa: S310 - host is allow-listed above
            return response.geturl()

    try:
        final_url = await asyncio.to_thread(resolve)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DouyinImportError(f"抖音短链解析失败：{exc}") from exc
    _validate_douyin_url(final_url)
    return final_url


async def _run_opencli(*args: str, timeout: int | None = None) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *_opencli_command(),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise DouyinImportError("本机没有找到 OpenCLI，无法解析抖音作品") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout or _OPENCLI_TIMEOUT
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise DouyinImportError("OpenCLI 解析抖音作品超时") from exc

    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    if process.returncode != 0:
        detail = (stderr_text or stdout_text).strip()[-800:]
        raise DouyinImportError(f"OpenCLI 解析失败：{detail}")
    return stdout_text


def _detail_script(aweme_id: str) -> str:
    endpoint = (
        "https://www.douyin.com/aweme/v1/web/aweme/detail/"
        f"?aweme_id={aweme_id}&aid=6383"
    )
    return (
        "(async()=>{"
        f"const r=await fetch({json.dumps(endpoint)},"
        "{credentials:'include',headers:{referer:'https://www.douyin.com/'}});"
        "const j=await r.json();const a=j.aweme_detail||null;"
        "return {http:r.status,status_code:j.status_code,status_msg:j.status_msg||'',"
        "item:a?{aweme_id:a.aweme_id,desc:a.desc,create_time:a.create_time,"
        "author:{nickname:a.author?.nickname||'',sec_uid:a.author?.sec_uid||'',"
        "unique_id:a.author?.unique_id||''},statistics:a.statistics||{},"
        "duration_ms:a.video?.duration||0,"
        "cover_url:a.video?.cover?.url_list?.[0]||''}:null};})()"
    )


async def resolve_douyin_share(text: str) -> dict[str, Any]:
    """Resolve one work link without exposing or persisting browser cookies."""
    shared_url = extract_douyin_url(text)
    resolved_url = await _resolve_share_url(shared_url)
    aweme_id = _aweme_id_from_url(resolved_url)
    canonical_url = f"https://www.douyin.com/video/{aweme_id}"
    session_name = f"content-import-{uuid.uuid4().hex[:12]}"

    try:
        await _run_opencli(
            "browser", session_name, "open", canonical_url, "--window", "background"
        )
        raw = await _run_opencli(
            "browser", session_name, "eval", _detail_script(aweme_id)
        )
        payload = parse_opencli_json(raw)[0]
    finally:
        try:
            await _run_opencli("browser", session_name, "close", timeout=15)
        except DouyinImportError:
            pass

    item = payload.get("item") if isinstance(payload, dict) else None
    author = item.get("author") if isinstance(item, dict) else None
    if payload.get("status_code") != 0 or not isinstance(author, dict):
        raise DouyinImportError(
            f"抖音详情接口没有返回作者身份：{payload.get('status_msg') or '未知错误'}"
        )
    sec_uid = str(author.get("sec_uid") or "").strip()
    if not sec_uid:
        raise DouyinImportError("抖音详情接口缺少 sec_uid")

    statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
    create_time = item.get("create_time")
    published_at = None
    if isinstance(create_time, (int, float)) and create_time > 0:
        published_at = datetime.fromtimestamp(create_time, tz=UTC).isoformat()
    metrics = {
        "view_count": statistics.get("play_count"),
        "like_count": statistics.get("digg_count"),
        "comment_count": statistics.get("comment_count"),
        "favorite_count": statistics.get("collect_count"),
        "share_count": statistics.get("share_count"),
    }
    # Douyin exposes play_count=0 for public benchmark works. Preserve the raw
    # value for evidence but do not advertise it as an available comparison signal.
    available_metrics = [
        name for name, value in metrics.items() if name != "view_count" and isinstance(value, int)
    ]
    return {
        "platform": "douyin",
        "external_account_id": sec_uid,
        "handle": str(author.get("unique_id") or "").strip() or None,
        "display_name": str(author.get("nickname") or "").strip() or None,
        "profile_url": f"https://www.douyin.com/user/{sec_uid}",
        "sample_work": {
            "external_work_id": aweme_id,
            "url": canonical_url,
            "title": item.get("desc") or None,
            "published_at": published_at,
            "duration_ms": item.get("duration_ms"),
            "cover_url": item.get("cover_url") or None,
            "metrics": metrics,
        },
        "available_metrics": available_metrics,
        "missing_metrics": ["view_count"],
    }
