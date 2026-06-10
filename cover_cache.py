"""Кэш обложек: память + диск, чтобы не ходить в S3 на каждый запрос."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections import OrderedDict
from pathlib import Path

from s3_utils import S3_BUCKET_NAME, get_object_async

logger = logging.getLogger("sounduk.cover_cache")

COVER_S3_TIMEOUT = max(5, int(os.getenv("COVER_S3_TIMEOUT", "15")))

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = BASE_DIR / "uploads" / ".cover_cache"
MEM_MAX_ITEMS = 256
DISK_MAX_BYTES = 8 * 1024 * 1024

_mem: OrderedDict[str, tuple[bytes, str]] = OrderedDict()


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _disk_paths(cache_key: str) -> tuple[Path, Path]:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.img", CACHE_DIR / f"{digest}.ctype"


def _etag_for(body: bytes) -> str:
    return f'"{hashlib.md5(body).hexdigest()}"'


def _mem_get(cache_key: str) -> tuple[bytes, str] | None:
    item = _mem.get(cache_key)
    if item is None:
        return None
    _mem.move_to_end(cache_key)
    return item


def _mem_put(cache_key: str, body: bytes, content_type: str) -> None:
    _mem[cache_key] = (body, content_type)
    _mem.move_to_end(cache_key)
    while len(_mem) > MEM_MAX_ITEMS:
        _mem.popitem(last=False)


def _disk_get_sync(cache_key: str) -> tuple[bytes, str] | None:
    img_path, ctype_path = _disk_paths(cache_key)
    if not img_path.is_file():
        return None
    try:
        body = img_path.read_bytes()
        content_type = (
            ctype_path.read_text(encoding="utf-8").strip()
            if ctype_path.is_file()
            else "image/jpeg"
        )
        return body, content_type
    except OSError as exc:
        logger.warning("cover_cache disk read fail key=%s error=%s", cache_key, exc)
        return None


def _disk_put_sync(cache_key: str, body: bytes, content_type: str) -> None:
    if len(body) > DISK_MAX_BYTES:
        return
    _ensure_cache_dir()
    img_path, ctype_path = _disk_paths(cache_key)
    try:
        img_path.write_bytes(body)
        ctype_path.write_text(content_type or "image/jpeg", encoding="utf-8")
    except OSError as exc:
        logger.warning("cover_cache disk write fail key=%s error=%s", cache_key, exc)


def invalidate(cache_key: str) -> None:
    _mem.pop(cache_key, None)
    img_path, ctype_path = _disk_paths(cache_key)
    for path in (img_path, ctype_path):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


async def _read_local(local_path: Path) -> bytes:
    return await asyncio.to_thread(local_path.read_bytes)


async def _load_from_s3(s3_key: str) -> tuple[bytes, str]:
    async def _fetch() -> tuple[bytes, str]:
        obj = await get_object_async(s3_key)
        content_type = obj.get("ContentType") or "image/jpeg"
        body = await asyncio.to_thread(obj["Body"].read)
        return body, content_type

    try:
        return await asyncio.wait_for(_fetch(), timeout=COVER_S3_TIMEOUT)
    except asyncio.TimeoutError as exc:
        logger.warning("cover_s3_timeout key=%s timeout=%ss", s3_key, COVER_S3_TIMEOUT)
        raise TimeoutError(f"S3 cover timeout after {COVER_S3_TIMEOUT}s") from exc


async def resolve_cover(
    cache_key: str,
    *,
    local_path: Path | None = None,
    s3_key: str | None = None,
    inline_bytes: bytes | None = None,
) -> tuple[bytes, str, str]:
    """
    Возвращает (body, content_type, source).
    source: mem | disk | local | s3
    """
    cached = _mem_get(cache_key)
    if cached is not None:
        return cached[0], cached[1], "mem"

    disk_item = await asyncio.to_thread(_disk_get_sync, cache_key)
    if disk_item is not None:
        _mem_put(cache_key, disk_item[0], disk_item[1])
        return disk_item[0], disk_item[1], "disk"

    if local_path is not None and local_path.is_file():
        body = await _read_local(local_path)
        content_type = "image/jpeg"
        _mem_put(cache_key, body, content_type)
        await asyncio.to_thread(_disk_put_sync, cache_key, body, content_type)
        return body, content_type, "local"

    if s3_key:
        body, content_type = await _load_from_s3(s3_key)
        _mem_put(cache_key, body, content_type)
        await asyncio.to_thread(_disk_put_sync, cache_key, body, content_type)
        return body, content_type, "s3"

    if inline_bytes:
        content_type = "image/jpeg"
        _mem_put(cache_key, inline_bytes, content_type)
        await asyncio.to_thread(
            _disk_put_sync, cache_key, inline_bytes, content_type
        )
        return inline_bytes, content_type, "inline"

    raise FileNotFoundError(cache_key)


def cover_cache_headers(body: bytes) -> dict[str, str]:
    return {
        "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
        "ETag": _etag_for(body),
    }


def is_not_modified(if_none_match: str | None, body: bytes) -> bool:
    if not if_none_match:
        return False
    etag = _etag_for(body)
    for token in if_none_match.split(","):
        if token.strip() == etag or token.strip() == "*":
            return True
    return False
