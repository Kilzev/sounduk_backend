# api/tracks.py - Роуты для работы с треками
import email
import logging
import time
from urllib.parse import quote, unquote
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form, Request, Header, BackgroundTasks
from fastapi.responses import StreamingResponse, Response, JSONResponse
import pydantic
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db, SessionLocal
import models
import schemas
from auth_utils import get_current_user, get_verified_user, create_stream_token, decode_token
import uuid
# from s3_utils import upload_file_to_s3, generate_presigned_url, delete_file_from_s3
import os
from pathlib import Path
import asyncio
from datetime import datetime
from io import BytesIO
from typing import Any
import httpx
import tempfile
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC
from mutagen.flac import FLAC
from mutagen import File as MutagenFile
from dotenv import load_dotenv
from library_sync import bump_library_revision, current_library_revision
from cover_cache import (
    cover_cache_headers,
    invalidate as invalidate_cover_cache,
    is_not_modified,
    resolve_cover,
)
from cover_storage import (
    delete_cover_from_s3,
    download_cover_by_url,
    resolve_cover_image,
    upload_track_cover_to_s3,
)
from s3_utils import (
    S3_BUCKET_NAME,
    STREAM_PRESIGNED_ENABLED,
    STREAM_PRESIGNED_TTL,
    get_object_async,
    get_s3_client,
    presigned_url_async,
    upload_bytes_to_s3_async,
)
from youtube_converter import download_youtube_mp3_with_meta, expand_playlist_watch_urls_sync

load_dotenv()

router = APIRouter()
tracks_logger = logging.getLogger("sounduk.tracks")


def _track_log(event: str, track_id: str | None = None, **fields) -> None:
    parts = [f"event={event}"]
    if track_id:
        parts.append(f"track_id={track_id}")
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    tracks_logger.info(" ".join(parts))


def _is_s3_track_file(file_path: str) -> bool:
    return not Path(str(file_path)).exists()


def _rebuild_cumulative_bytes(db: Session, user_id: int) -> None:
    tracks = (
        db.query(models.Track)
        .filter(models.Track.user_id == user_id)
        .order_by(models.Track.created_at.asc(), models.Track.id.asc())
        .all()
    )
    running = 0
    for track in tracks:
        running += track.file_size
        track.cumulative_bytes = running


def _track_is_frozen(track: models.Track, storage_limit: int) -> bool:
    return track.cumulative_bytes > storage_limit


def _make_track_cursor(track: models.Track) -> str:
    return f"{track.created_at.isoformat()}|{track.id}"


def _parse_track_cursor(cursor: str) -> tuple[datetime, str]:
    if "|" not in cursor:
        raise HTTPException(status_code=400, detail="Некорректный cursor")
    created_raw, track_id = cursor.split("|", 1)
    try:
        created_at = datetime.fromisoformat(created_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный cursor") from exc
    return created_at, track_id


UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
YOUTUBE_IMPORT_MAX_ITEMS = int(os.getenv("YOUTUBE_IMPORT_MAX_ITEMS", "100"))
_YOUTUBE_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_YOUTUBE_PLAYLIST_VIDEO_ID_RE = re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"')
JOB_ITEM_AUTO_RETRIES = max(2, int(os.getenv("JOB_ITEM_AUTO_RETRIES", "4")))


def _format_import_job_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, list):
            parts = []
            for entry in detail:
                if isinstance(entry, dict):
                    parts.append(str(entry.get("msg") or entry))
                else:
                    parts.append(str(entry))
            text = "; ".join(parts)
        elif isinstance(detail, dict):
            text = str(detail.get("detail") or detail)
        else:
            text = str(detail)
        return (text or f"HTTP {exc.status_code}")[:500]
    if isinstance(exc, httpx.HTTPError):
        text = f"{type(exc).__name__}: {exc}".strip()
        return text[:500]
    text = str(exc).strip()
    return (text or type(exc).__name__)[:500]


def _is_non_retryable_import_error(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "недостаточно места",
        "storage",
        "private video",
        "video unavailable",
        "sign in to confirm",
        "age-restricted",
        "this video is not available",
        "ожидается ссылка",
        "нет источника аудио",
    )
    return any(marker in lowered for marker in markers)

# Плейлист: волнами по N треков (следующие N только после завершения текущей волны).
YOUTUBE_IMPORT_BATCH_SIZE = max(1, min(int(os.getenv("YOUTUBE_IMPORT_BATCH_SIZE", "10")), 10))
# Одновременных yt-dlp/импортов на весь сервер (между job'ами).
YOUTUBE_IMPORT_CONCURRENCY = max(1, min(int(os.getenv("YOUTUBE_IMPORT_CONCURRENCY", "10")), 10))
MAX_ACTIVE_IMPORT_JOBS_PER_USER = max(1, min(int(os.getenv("MAX_ACTIVE_IMPORT_JOBS_PER_USER", "10")), 10))
_import_slot_semaphore = asyncio.Semaphore(YOUTUBE_IMPORT_CONCURRENCY)
_running_import_jobs: set[str] = set()
_running_jobs_lock = asyncio.Lock()
IMPORT_WORKER_EXTERNAL = os.getenv("IMPORT_WORKER_EXTERNAL", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _count_active_import_jobs(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(models.ImportJob.id))
        .filter(
            models.ImportJob.user_id == user_id,
            models.ImportJob.status.in_(["pending", "running"]),
        )
        .scalar()
        or 0
    )


def _ensure_import_job_capacity(db: Session, user: models.User) -> None:
    active = _count_active_import_jobs(db, user.id)
    if active >= MAX_ACTIVE_IMPORT_JOBS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много активных загрузок (максимум {MAX_ACTIVE_IMPORT_JOBS_PER_USER}). Дождитесь завершения текущих.",
        )


def _extract_duration_seconds(item: dict[str, Any]) -> int:
    value = item.get("duration") or item.get("duration_ms") or item.get("length")
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        # Some APIs return milliseconds.
        if value > 10000:
            return int(value / 1000)
        return int(value)
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return int(parts[0]) * 60 + int(parts[1])
        if value.isdigit():
            raw = int(value)
            return int(raw / 1000) if raw > 10000 else raw
    return 0


def _normalize_source_url(file_url: str) -> str:
    parsed = urlsplit(file_url.strip())
    normalized_query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=False)))
    cleaned = urlunsplit((
        parsed.scheme.lower(),
        (parsed.netloc or "").lower(),
        parsed.path or "/",
        normalized_query,
        "",
    ))
    return cleaned


def _job_to_response(job: models.ImportJob, db: Session | None = None) -> schemas.ImportJobResponse:
    running_items = 0
    if db is not None:
        running_items = (
            db.query(func.count(models.ImportJobItem.id))
            .filter(
                models.ImportJobItem.job_id == job.id,
                models.ImportJobItem.status == "running",
            )
            .scalar()
            or 0
        )
    return schemas.ImportJobResponse(
        id=job.id,
        status=job.status,
        album_id=job.album_id,
        total_items=job.total_items,
        processed_items=job.processed_items,
        running_items=running_items,
        success_items=job.success_items,
        failed_items=job.failed_items,
        skipped_items=job.skipped_items,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _refresh_job_counters(db: Session, job: models.ImportJob) -> None:
    counts = (
        db.query(models.ImportJobItem.status, func.count(models.ImportJobItem.id))
        .filter(models.ImportJobItem.job_id == job.id)
        .group_by(models.ImportJobItem.status)
        .all()
    )
    by_status = {status: count for status, count in counts}
    success = by_status.get("success", 0)
    failed = by_status.get("failed", 0)
    skipped = by_status.get("skipped", 0)
    processed = success + failed + skipped
    total = db.query(func.count(models.ImportJobItem.id)).filter(models.ImportJobItem.job_id == job.id).scalar() or 0
    job.total_items = total
    job.success_items = success
    job.failed_items = failed
    job.skipped_items = skipped
    job.processed_items = processed


async def _enqueue_import_job(job_id: str) -> None:
    async with _running_jobs_lock:
        if job_id in _running_import_jobs:
            return
        _running_import_jobs.add(job_id)
    asyncio.create_task(_run_import_job(job_id))


async def _schedule_import_job(job_id: str) -> None:
    if IMPORT_WORKER_EXTERNAL:
        return
    await _enqueue_import_job(job_id)


async def run_import_worker_loop() -> None:
    """Отдельный процесс: опрашивает БД и гоняет yt-dlp без нагрузки на API worker."""
    tracks_logger.info(
        "import_worker started batch=%s concurrency=%s",
        YOUTUBE_IMPORT_BATCH_SIZE,
        YOUTUBE_IMPORT_CONCURRENCY,
    )
    while True:
        db = SessionLocal()
        try:
            jobs = (
                db.query(models.ImportJob)
                .filter(models.ImportJob.status.in_(["pending", "running"]))
                .all()
            )
            for job in jobs:
                await _enqueue_import_job(job.id)
        finally:
            db.close()
        await asyncio.sleep(2)


async def _process_import_job_item(item_id: int, job_id: str) -> str | None:
    """Обрабатывает один item в отдельной DB-сессии. Возвращает track_id для альбома."""
    db = SessionLocal()
    track_id: str | None = None
    try:
        item = (
            db.query(models.ImportJobItem)
            .filter(
                models.ImportJobItem.id == item_id,
                models.ImportJobItem.job_id == job_id,
            )
            .first()
        )
        if not item or item.status != "pending":
            return None

        job = db.query(models.ImportJob).filter(models.ImportJob.id == job_id).first()
        if not job or job.status == "cancelled":
            return None

        item.status = "running"
        item.updated_at = datetime.utcnow()
        db.commit()

        duplicate = (
            db.query(models.ImportJobItem)
            .filter(
                models.ImportJobItem.user_id == item.user_id,
                models.ImportJobItem.normalized_url == item.normalized_url,
                models.ImportJobItem.status == "success",
                models.ImportJobItem.imported_track_id.isnot(None),
                models.ImportJobItem.job_id != job_id,
            )
            .order_by(models.ImportJobItem.updated_at.desc())
            .first()
        )
        if duplicate and duplicate.imported_track_id:
            existing_track = (
                db.query(models.Track)
                .filter(
                    models.Track.id == duplicate.imported_track_id,
                    models.Track.user_id == item.user_id,
                )
                .first()
            )
            if existing_track:
                item.status = "skipped"
                item.error_message = "duplicate_in_library"
                item.imported_track_id = duplicate.imported_track_id
                item.updated_at = datetime.utcnow()
                db.commit()
                return None

        user = db.query(models.User).filter(models.User.id == item.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        if _is_youtube_watch_url(item.file_url):
            media_item = await _build_youtube_media_item(
                item.file_url,
                title=item.title,
                artist=item.artist,
                album=item.album,
            )
            created_track = await _create_track_from_remote(media_item, user, db)
        else:
            payload_item = schemas.DirectTrackImportItem(
                file_url=item.file_url,
                title=item.title,
                artist=item.artist,
                album=item.album,
                duration=item.duration,
            )
            created_track = await _create_track_from_direct_url(payload_item, user, db)

        item.status = "success"
        item.error_message = None
        item.imported_track_id = created_track.id
        item.updated_at = datetime.utcnow()
        db.commit()
        track_id = created_track.id
    except Exception as exc:
        item = db.query(models.ImportJobItem).filter(models.ImportJobItem.id == item_id).first()
        if item:
            item.retry_count += 1
            item.error_message = _format_import_job_error(exc)
            item.updated_at = datetime.utcnow()
            if _is_non_retryable_import_error(item.error_message) or item.retry_count > JOB_ITEM_AUTO_RETRIES:
                item.status = "failed"
            else:
                item.status = "pending"
            db.commit()
    finally:
        db.close()
    return track_id


async def _run_import_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(models.ImportJob).filter(models.ImportJob.id == job_id).first()
        if not job:
            return
        if job.status in {"cancelled", "completed"}:
            return

        if job.started_at is None:
            job.started_at = datetime.utcnow()
        job.status = "running"
        db.commit()

        async def _run_item(item_id: int) -> str | None:
            async with _import_slot_semaphore:
                return await _process_import_job_item(item_id, job_id)

        while True:
            db.refresh(job)
            if job.status == "cancelled":
                job.finished_at = datetime.utcnow()
                db.commit()
                break

            pending_items = (
                db.query(models.ImportJobItem)
                .filter(
                    models.ImportJobItem.job_id == job.id,
                    models.ImportJobItem.status == "pending",
                )
                .order_by(models.ImportJobItem.position.asc())
                .limit(YOUTUBE_IMPORT_BATCH_SIZE)
                .all()
            )
            if not pending_items:
                _refresh_job_counters(db, job)
                if job.failed_items > 0:
                    job.status = "completed_with_errors"
                else:
                    job.status = "completed"
                job.finished_at = datetime.utcnow()
                db.commit()
                break

            db.refresh(job)
            if job.status == "cancelled":
                continue

            results = await asyncio.gather(
                *[_run_item(item.id) for item in pending_items],
                return_exceptions=True,
            )
            track_ids_to_attach = [tid for tid in results if isinstance(tid, str) and tid]

            if job.album_id and track_ids_to_attach:
                user = db.query(models.User).filter(models.User.id == job.user_id).first()
                if user:
                    try:
                        _attach_tracks_to_album(track_ids_to_attach, job.album_id, user, db)
                    except Exception:
                        pass

            _refresh_job_counters(db, job)
            db.commit()
    except Exception as exc:
        job = db.query(models.ImportJob).filter(models.ImportJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
        async with _running_jobs_lock:
            _running_import_jobs.discard(job_id)


def _first_non_empty(data: dict[str, Any], keys: list[str], default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _is_youtube_watch_url(url: str) -> bool:
    parsed = urlsplit(url.strip())
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        return False
    if host == "youtu.be":
        video_id = (parsed.path or "").strip("/").split("/")[0]
        return bool(_YOUTUBE_VIDEO_ID_RE.match(video_id))
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    video_id = query.get("v", "")
    return bool(_YOUTUBE_VIDEO_ID_RE.match(video_id))


def _parse_youtube_url_parts(url: str) -> tuple[str | None, str | None]:
    parsed = urlsplit(url.strip())
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        video_id = (parsed.path or "").strip("/").split("/")[0]
        if _YOUTUBE_VIDEO_ID_RE.match(video_id):
            return video_id, None
        return None, None
    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        return None, None
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    video_id = query.get("v")
    list_id = query.get("list")
    if video_id and not _YOUTUBE_VIDEO_ID_RE.match(video_id):
        video_id = None
    return video_id, list_id


def _extract_playlist_video_ids_from_html(html: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for match in _YOUTUBE_PLAYLIST_VIDEO_ID_RE.finditer(html):
        video_id = match.group(1)
        if video_id in seen:
            continue
        seen.add(video_id)
        ordered.append(video_id)
    return ordered


async def _scrape_youtube_playlist_video_ids(list_id: str) -> list[str]:
    playlist_url = f"https://www.youtube.com/playlist?list={quote(list_id, safe='')}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,*/*",
        "User-Agent": "Mozilla/5.0 (compatible; sounduk-backend/1.0)",
    }
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            response = await client.get(playlist_url, headers=headers)
            response.raise_for_status()
            video_ids = _extract_playlist_video_ids_from_html(response.text)
    except httpx.HTTPError:
        video_ids = []

    if video_ids:
        return video_ids

    watch_urls = await asyncio.to_thread(expand_playlist_watch_urls_sync, playlist_url)
    return [url.split("v=")[-1].split("&")[0] for url in watch_urls if "v=" in url]


async def _resolve_single_youtube_watch_url(youtube_url: str) -> str:
    video_id, list_id = _parse_youtube_url_parts(youtube_url)
    if list_id and not video_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для одного трека передайте ссылку на видео. Для плейлиста используйте /import/youtube/playlist",
        )
    if video_id:
        return _youtube_watch_url(video_id)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный YouTube URL")


async def _expand_youtube_watch_urls(youtube_url: str) -> list[str]:
    video_id, list_id = _parse_youtube_url_parts(youtube_url)
    if list_id:
        video_ids = await _scrape_youtube_playlist_video_ids(list_id)
        if not video_ids:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Не удалось получить список видео из YouTube-плейлиста",
            )
        if len(video_ids) > YOUTUBE_IMPORT_MAX_ITEMS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Плейлист содержит больше {YOUTUBE_IMPORT_MAX_ITEMS} треков",
            )
        return [_youtube_watch_url(vid) for vid in video_ids]
    if video_id:
        return [_youtube_watch_url(video_id)]
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный YouTube URL")


def _normalize_download_url(value: str) -> str | None:
    candidate = value.strip().strip('"').strip("'")
    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate.split()[0]
    return None


def _extract_download_url_from_json(payload: Any) -> str | None:
    if isinstance(payload, str):
        return _normalize_download_url(payload)
    if isinstance(payload, dict):
        for key in (
            "download_url",
            "downloadUrl",
            "url",
            "file",
            "link",
            "mp3",
            "audio",
            "audio_url",
            "downloadLink",
        ):
            if key not in payload:
                continue
            found = _extract_download_url_from_json(payload[key])
            if found:
                return found
        for value in payload.values():
            found = _extract_download_url_from_json(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_download_url_from_json(item)
            if found:
                return found
    return None


async def _fetch_youtube_oembed_title(watch_url: str) -> str | None:
    headers = {"Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": watch_url, "format": "json"},
                headers=headers,
            )
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


_VIDEO_TITLE_MARKERS = (
    "[official",
    "[hd",
    "(official",
    "music video",
    "official video",
    "official audio",
    "lyric video",
    "lyrics video",
    " full video",
    "vevo",
    " ft.",
    " feat.",
)


def _looks_like_youtube_video_title(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _VIDEO_TITLE_MARKERS):
        return True
    return ("[" in text or "(" in text) and len(text) > 32


def _title_artist_from_youtube_title(raw_title: str) -> tuple[str, str]:
    """Возвращает (track_title, artist). YouTube: и «Artist - Song», и «Song - Artist»."""
    title = raw_title.strip() or "Unknown title"
    if " - " not in title:
        return title, "Unknown artist"

    left, right = (part.strip() for part in title.split(" - ", 1))
    if not left or not right:
        return title, "Unknown artist"

    left_video = _looks_like_youtube_video_title(left)
    right_video = _looks_like_youtube_video_title(right)

    if left_video and not right_video:
        return left, right
    if right_video and not left_video:
        return right, left

    if len(right) <= 48 and len(left) > len(right) + 8 and not right_video:
        return left, right
    if len(left) <= 48 and len(right) > len(left) + 8 and not left_video:
        return right, left

    return right, left


async def _build_youtube_media_item(
    watch_url: str,
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> dict[str, Any]:
    if not _is_youtube_watch_url(watch_url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ожидается ссылка на YouTube-видео")

    media: dict[str, Any] = {"duration": 0}
    
    audio_bytes, yt_title, yt_duration, yt_artist, yt_thumbnail = await download_youtube_mp3_with_meta(watch_url)
    media["audio_bytes"] = audio_bytes
    if yt_duration > 0:
        media["duration"] = yt_duration
    if yt_thumbnail:
        media["thumbnail_url"] = yt_thumbnail

    resolved_title = _sanitize_meta_value(title)
    resolved_artist = _sanitize_meta_value(artist) or _sanitize_meta_value(yt_artist)
    if not resolved_title or not resolved_artist:
        title_source = yt_title or await _fetch_youtube_oembed_title(watch_url)
        parsed_title, parsed_artist = _title_artist_from_youtube_title(title_source or "Unknown title")
        resolved_title = resolved_title or parsed_title
        resolved_artist = resolved_artist or parsed_artist

    media["title"] = resolved_title
    media["artist"] = resolved_artist
    media["album"] = _sanitize_meta_value(album)
    return media


def _track_to_imported(track: models.Track) -> schemas.ImportedTrack:
    return schemas.ImportedTrack(
        id=track.id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        file_size=track.file_size,
        s3_key=str(track.file_path),
    )


async def _download_binary(url: str) -> bytes:
    headers = {
        "Accept": "application/json, application/octet-stream, audio/*, */*",
        "User-Agent": "sounduk-backend/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось скачать аудио по ссылке: {exc}",
        ) from exc


def _build_s3_track_key(user_id: int, track_id: str, extension: str = ".mp3") -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"tracks/{user_id}/{track_id}{ext}"


def _parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int]:
    start = 0
    end = file_size - 1
    if range_header:
        try:
            range_str = range_header.replace("bytes=", "")
            start_str, end_str = range_str.split("-")
            if start_str:
                start = int(start_str)
            if end_str:
                end = int(end_str)
        except ValueError:
            pass

    if start >= file_size:
        start = file_size - 1
    if end >= file_size:
        end = file_size - 1
    if end < start:
        end = start
    return start, end


def _resolve_mime_type(path_like: str, fallback: str = "audio/mpeg") -> str:
    suffix = Path(path_like).suffix.lower()
    mime_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".flac": "audio/flac"
    }
    return mime_types.get(suffix, fallback)


async def _stream_s3_object_with_range(
    object_key: str,
    file_size: int,
    range_header: str | None,
    filename: str,
    fallback_mime: str = "audio/mpeg",
) -> StreamingResponse:
    start, end = _parse_range_header(range_header, file_size)
    chunk_size = end - start + 1
    range_value = f"bytes={start}-{end}"

    s3_get_start = time.perf_counter()
    try:
        obj = await get_object_async(object_key, range_value)
    except Exception as exc:
        _track_log(
            "s3_get_object_fail",
            key=object_key,
            range=range_value,
            error=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Файл не найден в S3: {exc}"
        ) from exc
    s3_get_ms = int((time.perf_counter() - s3_get_start) * 1000)
    _track_log(
        "s3_get_object_ok",
        key=object_key,
        range=range_value,
        chunk_bytes=chunk_size,
        s3_get_ms=s3_get_ms,
    )

    body = obj["Body"]
    content_type = obj.get("ContentType") or _resolve_mime_type(object_key, fallback=fallback_mime)
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Range": f"bytes {start}-{end}/{file_size}"
    }
    return StreamingResponse(
        body.iter_chunks(chunk_size=8192),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=content_type,
        headers=headers,
    )


def _validate_direct_media_url(file_url: str) -> None:
    parsed = httpx.URL(file_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Поддерживаются только http/https ссылки")
    if not parsed.host:
        raise HTTPException(status_code=400, detail="Некорректный URL файла")


def _guess_content_type(file_url: str, response_headers: httpx.Headers) -> str:
    header_type = response_headers.get("content-type")
    if header_type:
        return header_type.split(";")[0].strip()
    lowered = file_url.lower()
    if lowered.endswith(".mp3"):
        return "audio/mpeg"
    if lowered.endswith(".m4a"):
        return "audio/mp4"
    if lowered.endswith(".wav"):
        return "audio/wav"
    if lowered.endswith(".flac"):
        return "audio/flac"
    return "application/octet-stream"


def _extract_source_filename(file_url: str, response_headers: httpx.Headers) -> str:
    content_disposition = response_headers.get("content-disposition", "")
    if content_disposition:
        # RFC 5987: filename*=UTF-8''encoded-name.mp3
        m_ext = re.search(r"filename\*\s*=\s*([^;]+)", content_disposition, flags=re.IGNORECASE)
        if m_ext:
            raw_value = m_ext.group(1).strip().strip('"')
            if "''" in raw_value:
                raw_value = raw_value.split("''", 1)[1]
            decoded = unquote(raw_value).strip()
            if decoded:
                return decoded

        m_basic = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition, flags=re.IGNORECASE)
        if m_basic:
            decoded = unquote(m_basic.group(1)).strip()
            if decoded:
                return decoded

    source_path = httpx.URL(file_url).path
    source_name = Path(source_path).name if source_path else ""
    if source_name:
        return source_name
    return "track.mp3"


def _extract_audio_metadata(raw_bytes: bytes, source_name: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "title": None,
        "artist": None,
        "album": None,
        "duration": 0,
        "cover_data": None,
    }
    suffix = Path(source_name).suffix or ".mp3"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name

        audio = MutagenFile(tmp_path)
        if not audio:
            return metadata

        if getattr(audio, "info", None) and getattr(audio.info, "length", None):
            metadata["duration"] = max(0, int(audio.info.length))

        tags = getattr(audio, "tags", None)
        if tags:
            def _read_first(keys: list[str]) -> str | None:
                for key in keys:
                    value = tags.get(key)
                    if value is None:
                        continue
                    if isinstance(value, list):
                        if value:
                            return str(value[0]).strip()
                    else:
                        text = getattr(value, "text", None)
                        if isinstance(text, list) and text:
                            return str(text[0]).strip()
                        return str(value).strip()
                return None

            metadata["title"] = _read_first(["TIT2", "title", "\xa9nam"])
            metadata["artist"] = _read_first(["TPE1", "artist", "\xa9ART"])
            metadata["album"] = _read_first(["TALB", "album", "\xa9alb"])

            for tag in tags.values():
                if isinstance(tag, APIC):
                    metadata["cover_data"] = tag.data
                    break

            if metadata["cover_data"] is None:
                covr = tags.get("covr")
                if isinstance(covr, list) and covr:
                    metadata["cover_data"] = bytes(covr[0])

        if metadata["cover_data"] is None and hasattr(audio, "pictures") and audio.pictures:
            metadata["cover_data"] = audio.pictures[0].data
    except Exception as exc:
        print(f"Metadata extraction error for {source_name}: {exc}")
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return metadata


def _upload_cover_to_s3(cover_data: bytes, user_id: int, track_id: str) -> str:
    return upload_track_cover_to_s3(cover_data, user_id, track_id)


async def _persist_track_cover(
    *,
    user_id: int,
    track_id: str,
    cover_data: bytes | None = None,
    cover_url: str | None = None,
) -> str | None:
    """Скачивает обложку (если URL) и сохраняет в S3. Возвращает cover_path."""
    data = cover_data
    if data is None and cover_url:
        try:
            data = await download_cover_by_url(cover_url.strip())
        except HTTPException:
            return None
        except Exception:
            return None
    if not data:
        return None
    try:
        return upload_track_cover_to_s3(data, user_id, track_id)
    except Exception as exc:
        print(f"Cover upload error: {exc}")
        return None


async def _download_cover_by_url(cover_url: str) -> bytes:
    return await resolve_cover_image(cover_url)


def _guess_title_artist_from_filename(file_name: str) -> tuple[str, str]:
    stem = Path(file_name).stem.strip()
    if not stem:
        return "Unknown title", "Unknown artist"
    # Common naming pattern: "Artist - Title".
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        artist = artist.strip() or "Unknown artist"
        title = title.strip() or stem
        return title, artist
    return stem, "Unknown artist"


def _sanitize_meta_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    bad = {"unknown", "unknown title", "unknown artist", "неизвестный", "неизвестно"}
    if lowered in bad:
        return None
    return text


def _attach_tracks_to_album(
    track_ids: list[str],
    album_id: str,
    current_user: models.User,
    db: Session,
) -> None:
    album = db.query(models.Album).filter(
        models.Album.id == album_id,
        models.Album.user_id == current_user.id,
    ).first()
    if not album:
        raise HTTPException(status_code=404, detail="Альбом для привязки не найден")

    existing = set(album.track_ids or [])
    changed = False
    for track_id in track_ids:
        if track_id not in existing:
            existing.add(track_id)
            changed = True

    if changed:
        album.track_ids = list(existing)
        album.updated_at = datetime.utcnow()
        db.commit()
        bump_library_revision(db, current_user.id)


async def _create_track_from_remote(
    item: dict[str, Any],
    current_user: models.User,
    db: Session,
) -> models.Track:
    audio_bytes = item.get("audio_bytes")
    if audio_bytes is not None:
        raw_bytes = audio_bytes
    elif item.get("download_url"):
        raw_bytes = await _download_binary(item["download_url"])
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет источника аудио для импорта",
        )
    file_size = len(raw_bytes)
    total_usage = db.query(func.sum(models.Track.file_size)).filter(
        models.Track.user_id == current_user.id
    ).scalar() or 0
    if total_usage + file_size > current_user.storage_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно места для импорта трека"
        )

    title = item.get("title") or "Unknown title"
    artist = item.get("artist") or "Unknown artist"
    source_name = f"{title}.mp3"
    parsed_meta = _extract_audio_metadata(raw_bytes, source_name)
    duration = item.get("duration") or parsed_meta.get("duration") or 0
    duration = max(0, int(duration))
    if _sanitize_meta_value(parsed_meta.get("title")):
        title = _sanitize_meta_value(parsed_meta.get("title")) or title
    if _sanitize_meta_value(parsed_meta.get("artist")):
        artist = _sanitize_meta_value(parsed_meta.get("artist")) or artist
    album_name = _sanitize_meta_value(item.get("album")) or _sanitize_meta_value(parsed_meta.get("album"))

    track_id = str(uuid.uuid4())
    s3_key = _build_s3_track_key(current_user.id, track_id)
    upload_t0 = time.perf_counter()
    tracks_logger.info(
        "import_s3_upload_start user_id=%s track_id=%s bytes=%s key=%s",
        current_user.id,
        track_id,
        file_size,
        s3_key,
    )
    try:
        await upload_bytes_to_s3_async(raw_bytes, s3_key, content_type="audio/mpeg")
    except Exception as exc:
        tracks_logger.error(
            "import_s3_upload_fail user_id=%s track_id=%s bytes=%s key=%s ms=%s error=%s",
            current_user.id,
            track_id,
            file_size,
            s3_key,
            int((time.perf_counter() - upload_t0) * 1000),
            exc,
        )
        raise
    tracks_logger.info(
        "import_s3_upload_ok user_id=%s track_id=%s bytes=%s key=%s ms=%s",
        current_user.id,
        track_id,
        file_size,
        s3_key,
        int((time.perf_counter() - upload_t0) * 1000),
    )

    cover_path = await _persist_track_cover(
        user_id=current_user.id,
        track_id=track_id,
        cover_data=parsed_meta.get("cover_data"),
        cover_url=item.get("thumbnail_url") or item.get("cover_url"),
    )

    new_track = models.Track(
        id=track_id,
        user_id=current_user.id,
        title=title,
        artist=artist,
        album=album_name,
        duration=duration,
        file_path=s3_key,
        file_size=file_size,
        cover_path=cover_path,
        created_at=datetime.utcnow(),
    )
    db.add(new_track)
    db.flush()
    _rebuild_cumulative_bytes(db, current_user.id)
    db.commit()
    db.refresh(new_track)
    bump_library_revision(db, current_user.id)
    return new_track


async def _create_track_from_direct_url(
    item: schemas.DirectTrackImportItem,
    current_user: models.User,
    db: Session,
) -> models.Track:
    _validate_direct_media_url(item.file_url)
    headers = {
        "Accept": "application/json,audio/*,application/octet-stream,*/*",
        "User-Agent": "sounduk-backend/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(item.file_url, headers=headers)
            response.raise_for_status()
            raw_bytes = response.content
            content_type = _guess_content_type(item.file_url, response.headers)
            source_name = _extract_source_filename(item.file_url, response.headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось скачать файл по ссылке: {exc}"
        ) from exc

    parsed_meta = _extract_audio_metadata(raw_bytes, source_name)
    file_size = len(raw_bytes)
    total_usage = db.query(func.sum(models.Track.file_size)).filter(
        models.Track.user_id == current_user.id
    ).scalar() or 0
    if total_usage + file_size > current_user.storage_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно места для импорта по ссылке"
        )

    track_id = str(uuid.uuid4())
    s3_key = _build_s3_track_key(current_user.id, track_id)
    await upload_bytes_to_s3_async(raw_bytes, s3_key, content_type=content_type)
    cover_path = None
    if parsed_meta.get("cover_data"):
        cover_path = await _persist_track_cover(
            user_id=current_user.id,
            track_id=track_id,
            cover_data=parsed_meta["cover_data"],
        )

    guessed_title, guessed_artist = _guess_title_artist_from_filename(source_name)
    parsed_title = _sanitize_meta_value(parsed_meta.get("title"))
    parsed_artist = _sanitize_meta_value(parsed_meta.get("artist"))
    parsed_album = _sanitize_meta_value(parsed_meta.get("album"))
    manual_title = _sanitize_meta_value(item.title)
    manual_artist = _sanitize_meta_value(item.artist)
    manual_album = _sanitize_meta_value(item.album)

    final_title = manual_title or parsed_title or guessed_title
    final_artist = manual_artist or parsed_artist or guessed_artist
    final_album = manual_album or parsed_album

    host = httpx.URL(item.file_url).host or ""
    host_base = host.split(".")[0].strip()

    # Never persist fully unknown artist/title.
    if final_artist.lower().startswith("unknown"):
        if host_base:
            final_artist = host_base.capitalize()
        else:
            final_artist = "Imported"
    if final_title.lower().startswith("unknown") or not final_title.strip():
        fallback_stem = Path(source_name).stem.strip()
        if fallback_stem and not fallback_stem.lower().startswith("unknown"):
            final_title = fallback_stem
        else:
            final_title = f"track-{track_id[:8]}"
    final_duration = item.duration if item.duration is not None else parsed_meta.get("duration") or 0

    new_track = models.Track(
        id=track_id,
        user_id=current_user.id,
        title=final_title,
        artist=final_artist,
        album=final_album,
        duration=max(0, int(final_duration)),
        file_path=s3_key,
        file_size=file_size,
        cover_path=cover_path,
        created_at=datetime.utcnow(),
    )
    db.add(new_track)
    db.flush()
    _rebuild_cumulative_bytes(db, current_user.id)
    db.commit()
    db.refresh(new_track)
    bump_library_revision(db, current_user.id)
    return new_track

@router.post("/upload", response_model=schemas.TrackResponse, status_code=status.HTTP_201_CREATED)
async def upload_track(
    file: UploadFile = File(...),
    title: str = Form(...),
    artist: str = Form(...),
    album: str = Form(None),
    duration: int = Form(...),
    created_at: str = Form(None),
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db)
):
    total_usage = db.query(func.sum(models.Track.file_size)).filter(
        models.Track.user_id == current_user.id
    ).scalar() or 0

    if not file.filename or not file.filename.lower().endswith(
        (".mp3", ".m4a", ".wav", ".flac")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неподдерживаемый формат файла",
        )

    try:
        raw_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось прочитать файл: {exc}",
        ) from exc

    file_size = len(raw_bytes)
    if file_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пустой файл",
        )

    if total_usage + file_size > current_user.storage_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно места",
        )

    file_extension = os.path.splitext(file.filename)[1].lower()
    track_id = str(uuid.uuid4())
    source_name = file.filename
    parsed_meta = _extract_audio_metadata(raw_bytes, source_name)

    track_duration = max(0, int(duration))
    if track_duration <= 0 and parsed_meta.get("duration"):
        track_duration = max(0, int(parsed_meta["duration"]))

    s3_key = _build_s3_track_key(current_user.id, track_id, file_extension)
    content_type = _resolve_mime_type(source_name)

    try:
        await upload_bytes_to_s3_async(raw_bytes, s3_key, content_type=content_type)
    except Exception as exc:
        _track_log(
            "upload_s3_fail",
            track_id,
            user_id=current_user.id,
            error=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось сохранить файл в облако",
        ) from exc

    cover_path = None
    if parsed_meta.get("cover_data"):
        cover_path = await _persist_track_cover(
            user_id=current_user.id,
            track_id=track_id,
            cover_data=parsed_meta["cover_data"],
        )

    new_track = models.Track(
        id=track_id,
        user_id=current_user.id,
        title=title,
        artist=artist,
        album=album,
        duration=track_duration,
        file_path=s3_key,
        file_size=file_size,
        cover_path=cover_path,
        created_at=datetime.fromisoformat(created_at) if created_at else datetime.utcnow(),
    )

    db.add(new_track)
    db.flush()
    _rebuild_cumulative_bytes(db, current_user.id)
    db.commit()
    db.refresh(new_track)
    bump_library_revision(db, current_user.id)
    _track_log(
        "upload_ok",
        track_id,
        user_id=current_user.id,
        bytes=file_size,
        s3_key=s3_key,
    )
    return new_track

@router.get("/{track_id}/cover")
async def get_track_cover(
    track_id: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
):
    t0 = time.perf_counter()
    user_id = current_user.id
    db = SessionLocal()
    try:
        track = db.query(models.Track).filter(
            models.Track.id == track_id,
            models.Track.user_id == user_id,
        ).first()
        if not track or not track.cover_path:
            _track_log(
                "cover_not_found",
                track_id,
                user_id=user_id,
                total_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise HTTPException(status_code=404, detail="Обложка не найдена")
        cover_path = str(track.cover_path)
    finally:
        db.close()

    cache_key = f"track:{user_id}:{track_id}"
    cover_file = Path(cover_path)
    local_path = cover_file if cover_file.is_file() else None
    s3_key = None if local_path else cover_path

    try:
        body, content_type, source = await resolve_cover(
            cache_key,
            local_path=local_path,
            s3_key=s3_key,
        )
    except FileNotFoundError:
        _track_log(
            "cover_s3_fail",
            track_id,
            user_id=user_id,
            error="not_found",
            total_ms=int((time.perf_counter() - t0) * 1000),
        )
        raise HTTPException(status_code=404, detail="Файл обложки не найден")
    except Exception as exc:
        _track_log(
            "cover_s3_fail",
            track_id,
            user_id=user_id,
            error=type(exc).__name__,
            total_ms=int((time.perf_counter() - t0) * 1000),
        )
        raise HTTPException(status_code=404, detail="Файл обложки не найден") from exc

    headers = cover_cache_headers(body)
    if is_not_modified(request.headers.get("if-none-match"), body):
        _track_log(
            "cover_not_modified",
            track_id,
            user_id=user_id,
            source=source,
            total_ms=int((time.perf_counter() - t0) * 1000),
        )
        return Response(status_code=304, headers=headers)

    total_ms = int((time.perf_counter() - t0) * 1000)
    _track_log(
        "cover_ok",
        track_id,
        user_id=user_id,
        source=source,
        bytes=len(body),
        total_ms=total_ms,
    )
    return Response(content=body, media_type=content_type, headers=headers)

@router.get("")
async def get_tracks(
    since_revision: int | None = Query(None, alias="since_revision"),
    limit: int | None = Query(None, ge=1, le=200),
    cursor: str | None = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    revision = current_library_revision(db, current_user.id)
    headers = {"X-Library-Revision": str(revision)}

    if since_revision is not None and since_revision == revision:
        _track_log(
            "list_tracks_unchanged",
            user_id=current_user.id,
            revision=revision,
            since_revision=since_revision,
            total_ms=int((time.perf_counter() - t0) * 1000),
        )
        return JSONResponse(
            content={
                "unchanged": True,
                "revision": revision,
                "tracks": [],
                "total": 0,
                "has_more": False,
            },
            headers=headers,
        )

    total_count = (
        db.query(func.count(models.Track.id))
        .filter(models.Track.user_id == current_user.id)
        .scalar()
        or 0
    )

    query = db.query(models.Track).filter(models.Track.user_id == current_user.id)
    if cursor:
        created_at, track_id = _parse_track_cursor(cursor)
        query = query.filter(
            (models.Track.created_at > created_at)
            | (
                (models.Track.created_at == created_at)
                & (models.Track.id > track_id)
            )
        )

    query = query.order_by(models.Track.created_at.asc(), models.Track.id.asc())

    has_more = False
    next_cursor: str | None = None
    if limit is not None:
        tracks = query.limit(limit + 1).all()
        if len(tracks) > limit:
            has_more = True
            tracks = tracks[:limit]
            next_cursor = _make_track_cursor(tracks[-1])
    else:
        tracks_logger.warning(
            "list_tracks_no_limit user_id=%s total=%s",
            current_user.id,
            total_count,
        )
        tracks = query.all()

    result_tracks = []
    for track in tracks:
        track_out = schemas.TrackResponse.model_validate(track)
        track_dict = track_out.model_dump(mode="json")
        track_dict["is_frozen"] = _track_is_frozen(track, current_user.storage_limit)
        track_dict["has_cover"] = bool(track.cover_path)
        result_tracks.append(track_dict)

    body = {
        "tracks": result_tracks,
        "total": total_count,
        "has_more": has_more,
    }
    if next_cursor:
        body["next_cursor"] = next_cursor
    if since_revision is not None:
        body["unchanged"] = False
        body["revision"] = revision

    _track_log(
        "list_tracks_ok",
        user_id=current_user.id,
        count=len(result_tracks),
        revision=revision,
        since_revision=since_revision,
        limit=limit,
        cursor=bool(cursor),
        has_more=has_more,
        total_ms=int((time.perf_counter() - t0) * 1000),
    )
    return JSONResponse(content=body, headers=headers)

@router.get("/{track_id}/stream")
async def stream_track(
    track_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(models.Track).filter(models.Track.id == track_id)
    # Если не админ, показываем только свои треки
    if not getattr(current_user, 'is_admin', False):
        query = query.filter(models.Track.user_id == current_user.id)
        
    track = query.first()
    
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Трек не найден"
        )
        
    # Проверка на заморозку (если не админ)
    if (
        not getattr(current_user, 'is_admin', False)
        and track.user_id == current_user.id
        and _track_is_frozen(track, current_user.storage_limit)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Этот трек заморожен, так как превышен лимит хранилища. Оплатите подписку или удалите старые треки."
        )

    # Check if this is a path (local) or S3 key
    file_path = Path(str(track.file_path))

    if file_path.exists():
        # Local file
        mime_type = _resolve_mime_type(str(file_path))
        
        def file_iterator():
            with open(file_path, "rb") as file:
                while chunk := file.read(8192):
                    yield chunk
        
        filename = f"{track.title}{file_path.suffix}"
        encoded_filename = quote(filename)
        
        return StreamingResponse(
            file_iterator(),
            media_type=mime_type,
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"
            }
        )
    else:
        file_size = track.file_size
        filename = f"{track.title}{Path(str(track.file_path)).suffix or '.mp3'}"
        return await _stream_s3_object_with_range(
            object_key=str(track.file_path),
            file_size=file_size,
            range_header="bytes=0-{}".format(max(0, file_size - 1)),
            filename=filename,
        )

@router.get("/{track_id}/token", response_model=schemas.StreamTokenResponse)
async def get_track_token(
    track_id: str,
    current_user: models.User = Depends(get_current_user),
):
    t0 = time.perf_counter()
    user_id = current_user.id
    db = SessionLocal()
    try:
        track = db.query(models.Track).filter(
            models.Track.id == track_id,
            models.Track.user_id == user_id,
        ).first()

        if not track:
            _track_log(
                "token_not_found",
                track_id,
                user_id=user_id,
                total_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Трек не найден"
            )

        freeze_start = time.perf_counter()
        is_frozen = _track_is_frozen(track, current_user.storage_limit)
        freeze_ms = int((time.perf_counter() - freeze_start) * 1000)

        if is_frozen:
            _track_log(
                "token_frozen",
                track_id,
                user_id=user_id,
                freeze_check_ms=freeze_ms,
                total_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Этот трек заморожен, так как превышен лимит хранилища. Оплатите подписку или удалите старые треки."
            )

        track_file_path = str(track.file_path)
    finally:
        db.close()

    token = create_stream_token(track_id)
    proxy_url = f"/api/tracks/play/{token}"
    presigned_url: str | None = None
    expires_in: int | None = None

    if STREAM_PRESIGNED_ENABLED and _is_s3_track_file(track_file_path):
        presigned_url = await presigned_url_async(
            track_file_path,
            expiration=STREAM_PRESIGNED_TTL,
        )
        if presigned_url:
            expires_in = STREAM_PRESIGNED_TTL

    _track_log(
        "token_issued",
        track_id,
        user_id=user_id,
        freeze_check_ms=freeze_ms,
        presigned=bool(presigned_url),
        total_ms=int((time.perf_counter() - t0) * 1000),
    )
    return schemas.StreamTokenResponse(
        token=token,
        url=proxy_url,
        presigned_url=presigned_url,
        expires_in=expires_in,
    )

@router.get("/play/{token}")
async def play_track(
    token: str,
    request: Request,
    range: str = Header(None),
):
    t0 = time.perf_counter()
    try:
        payload = decode_token(token)
        if payload.get("type") != "stream":
            raise HTTPException(status_code=401, detail="Invalid token type")
        track_id = payload.get("sub")
    except Exception:
        _track_log("play_invalid_token", total_ms=int((time.perf_counter() - t0) * 1000))
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    db = SessionLocal()
    try:
        track = db.query(models.Track).filter(models.Track.id == track_id).first()
        if not track:
            _track_log(
                "play_not_found",
                track_id,
                total_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Трек не найден"
            )
        track_file_path = str(track.file_path)
        track_file_size = track.file_size
        track_title = track.title
    finally:
        db.close()

    file_path = Path(track_file_path)
    if not file_path.exists():
        file_size = track_file_size
        start_byte, end_byte = _parse_range_header(range, file_size)
        _track_log(
            "play_start",
            track_id,
            source="s3",
            range=range,
            chunk=f"{start_byte}-{end_byte}",
            file_size=file_size,
            total_ms=int((time.perf_counter() - t0) * 1000),
        )
        filename = f"{track_title}{Path(track_file_path).suffix or '.mp3'}"
        return await _stream_s3_object_with_range(
            object_key=track_file_path,
            file_size=file_size,
            range_header=range,
            filename=filename,
        )
    
    file_size = file_path.stat().st_size
    start, end = _parse_range_header(range, file_size)
    _track_log(
        "play_start",
        track_id,
        source="local",
        range=range,
        chunk=f"{start}-{end}",
        file_size=file_size,
        total_ms=int((time.perf_counter() - t0) * 1000),
    )
    chunk_size = end - start + 1
    
    mime_type = _resolve_mime_type(str(file_path))
    
    def file_iterator(start_byte, end_byte):
        with open(file_path, "rb") as file:
            file.seek(start_byte)
            remaining = end_byte - start_byte + 1
            while remaining > 0:
                chunk_size = min(8192, remaining)
                chunk = file.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)
    
    filename = f"{track_title}{file_path.suffix}"
    encoded_filename = quote(filename)
    
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Range": f"bytes {start}-{end}/{file_size}"
    }
    
    return StreamingResponse(
        file_iterator(start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=mime_type,
        headers=headers
    )


@router.patch("/{track_id}", response_model=schemas.TrackResponse)
async def update_track(
    track_id: str,
    payload: schemas.TrackUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(models.Track).filter(
        models.Track.id == track_id,
        models.Track.user_id == current_user.id,
    ).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Название не может быть пустым")
        track.title = title

    if payload.artist is not None:
        artist = payload.artist.strip()
        if not artist:
            raise HTTPException(status_code=400, detail="Исполнитель не может быть пустым")
        track.artist = artist

    if payload.clear_cover:
        delete_cover_from_s3(track.cover_path)
        invalidate_cover_cache(f"track:{current_user.id}:{track_id}")
        track.cover_path = None
    elif payload.cover_url:
        cover_bytes = await _download_cover_by_url(payload.cover_url.strip())
        delete_cover_from_s3(track.cover_path)
        invalidate_cover_cache(f"track:{current_user.id}:{track_id}")
        track.cover_path = _upload_cover_to_s3(cover_bytes, current_user.id, track.id)

    db.commit()
    db.refresh(track)
    bump_library_revision(db, current_user.id)
    return track


def _download_track_bytes_from_s3(object_key: str) -> bytes:
    s3_client = get_s3_client()
    obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=object_key)
    return obj["Body"].read()


@router.post("/{track_id}/repair-metadata", response_model=schemas.TrackResponse)
async def repair_track_metadata(
    track_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Перечитать duration (и теги) из MP3 в S3 — для треков с duration=0 после старого YouTube-импорта."""
    track = db.query(models.Track).filter(
        models.Track.id == track_id,
        models.Track.user_id == current_user.id,
    ).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")
    if not track.file_path or str(track.file_path).startswith("uploads/"):
        raise HTTPException(status_code=400, detail="Трек без файла в облаке")

    raw_bytes = _download_track_bytes_from_s3(str(track.file_path))
    parsed = _extract_audio_metadata(raw_bytes, f"{track.title}.mp3")
    duration = max(0, int(parsed.get("duration") or 0))
    if duration <= 0:
        raise HTTPException(status_code=400, detail="Не удалось определить длительность из файла")

    track.duration = duration
    if _sanitize_meta_value(parsed.get("title")):
        track.title = _sanitize_meta_value(parsed.get("title"))
    if _sanitize_meta_value(parsed.get("artist")):
        track.artist = _sanitize_meta_value(parsed.get("artist"))
    if not track.cover_path and parsed.get("cover_data"):
        cover_path = await _persist_track_cover(
            user_id=current_user.id,
            track_id=track.id,
            cover_data=parsed["cover_data"],
        )
        if cover_path:
            track.cover_path = cover_path
    db.commit()
    db.refresh(track)
    bump_library_revision(db, current_user.id)
    return track


@router.post("/import/youtube/track", response_model=schemas.TrackImportResponse, status_code=status.HTTP_201_CREATED)
async def import_youtube_track(
    payload: schemas.YouTubeImportRequest,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    watch_url = await _resolve_single_youtube_watch_url(payload.youtube_url)
    media_item = await _build_youtube_media_item(watch_url)
    track = await _create_track_from_remote(media_item, current_user, db)
    if payload.album_id:
        _attach_tracks_to_album([track.id], payload.album_id, current_user, db)
    return schemas.TrackImportResponse(imported=[_track_to_imported(track)], total=1)


@router.post("/import/youtube/playlist", response_model=schemas.TrackImportResponse, status_code=status.HTTP_201_CREATED)
async def import_youtube_playlist(
    payload: schemas.YouTubeImportRequest,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    watch_urls = await _expand_youtube_watch_urls(payload.youtube_url)
    imported: list[schemas.ImportedTrack] = []
    imported_ids: list[str] = []
    for watch_url in watch_urls:
        media_item = await _build_youtube_media_item(watch_url)
        track = await _create_track_from_remote(media_item, current_user, db)
        imported_ids.append(track.id)
        imported.append(_track_to_imported(track))
    if payload.album_id and imported_ids:
        _attach_tracks_to_album(imported_ids, payload.album_id, current_user, db)
    return schemas.TrackImportResponse(imported=imported, total=len(imported))


@router.post("/import/youtube/jobs", response_model=schemas.ImportJobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_youtube_import_job(
    payload: schemas.YouTubeImportJobCreateRequest,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    watch_urls = await _expand_youtube_watch_urls(payload.youtube_url)

    if payload.client_request_id:
        existing = (
            db.query(models.ImportJob)
            .filter(
                models.ImportJob.user_id == current_user.id,
                models.ImportJob.client_request_id == payload.client_request_id,
                models.ImportJob.status.in_(["pending", "running"]),
            )
            .order_by(models.ImportJob.created_at.desc())
            .first()
        )
        if existing:
            await _schedule_import_job(existing.id)
            return schemas.ImportJobCreateResponse(job_id=existing.id, status=existing.status)

    _ensure_import_job_capacity(db, current_user)

    job = models.ImportJob(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        album_id=payload.album_id,
        status="pending",
        client_request_id=payload.client_request_id,
    )
    db.add(job)
    db.flush()

    seen_urls: set[str] = set()
    for index, watch_url in enumerate(watch_urls):
        normalized = _normalize_source_url(watch_url)
        is_duplicate = normalized in seen_urls
        seen_urls.add(normalized)
        job_item = models.ImportJobItem(
            job_id=job.id,
            user_id=current_user.id,
            position=index,
            file_url=watch_url,
            normalized_url=normalized,
            status="skipped" if is_duplicate else "pending",
            error_message="skipped_duplicate_in_request" if is_duplicate else None,
        )
        db.add(job_item)
    db.commit()
    db.refresh(job)
    _refresh_job_counters(db, job)
    db.commit()

    await _schedule_import_job(job.id)
    return schemas.ImportJobCreateResponse(job_id=job.id, status=job.status)


@router.post("/import/direct", response_model=schemas.TrackImportResponse, status_code=status.HTTP_201_CREATED)
async def import_direct_track(
    payload: schemas.DirectTrackImportRequest,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db)
):
    item = schemas.DirectTrackImportItem(
        file_url=payload.file_url,
    )
    track = await _create_track_from_direct_url(item, current_user, db)

    if payload.album_id:
        _attach_tracks_to_album([track.id], payload.album_id, current_user, db)

    return schemas.TrackImportResponse(imported=[_track_to_imported(track)], total=1)


@router.post("/import/direct/batch", response_model=schemas.TrackImportResponse, status_code=status.HTTP_201_CREATED)
async def import_direct_batch(
    payload: schemas.DirectBatchImportRequest,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db)
):
    if not payload.tracks:
        raise HTTPException(status_code=400, detail="Список tracks не должен быть пустым")

    imported: list[schemas.ImportedTrack] = []
    imported_ids: list[str] = []
    for item in payload.tracks:
        track = await _create_track_from_direct_url(item, current_user, db)
        imported_ids.append(track.id)
        imported.append(_track_to_imported(track))

    if payload.album_id and imported_ids:
        _attach_tracks_to_album(imported_ids, payload.album_id, current_user, db)

    return schemas.TrackImportResponse(imported=imported, total=len(imported))


@router.post("/import/direct/jobs", response_model=schemas.ImportJobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_direct_import_job(
    payload: schemas.DirectImportJobCreateRequest,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    if not payload.tracks:
        raise HTTPException(status_code=400, detail="Список tracks не должен быть пустым")

    if payload.client_request_id:
        existing = (
            db.query(models.ImportJob)
            .filter(
                models.ImportJob.user_id == current_user.id,
                models.ImportJob.client_request_id == payload.client_request_id,
                models.ImportJob.status.in_(["pending", "running"]),
            )
            .order_by(models.ImportJob.created_at.desc())
            .first()
        )
        if existing:
            await _schedule_import_job(existing.id)
            return schemas.ImportJobCreateResponse(job_id=existing.id, status=existing.status)

    _ensure_import_job_capacity(db, current_user)

    job = models.ImportJob(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        album_id=payload.album_id,
        status="pending",
        client_request_id=payload.client_request_id,
    )
    db.add(job)
    db.flush()

    seen_urls: set[str] = set()
    for index, item in enumerate(payload.tracks):
        normalized = _normalize_source_url(item.file_url)
        is_duplicate = normalized in seen_urls
        seen_urls.add(normalized)
        job_item = models.ImportJobItem(
            job_id=job.id,
            user_id=current_user.id,
            position=index,
            file_url=item.file_url,
            normalized_url=normalized,
            status="skipped" if is_duplicate else "pending",
            error_message="skipped_duplicate_in_request" if is_duplicate else None,
            title=item.title,
            artist=item.artist,
            album=item.album,
            duration=item.duration,
        )
        db.add(job_item)
    db.commit()
    db.refresh(job)
    _refresh_job_counters(db, job)
    db.commit()

    await _schedule_import_job(job.id)
    return schemas.ImportJobCreateResponse(job_id=job.id, status=job.status)


@router.get("/import/direct/jobs/{job_id}", response_model=schemas.ImportJobResponse)
async def get_direct_import_job(
    job_id: str,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    job = (
        db.query(models.ImportJob)
        .filter(
            models.ImportJob.id == job_id,
            models.ImportJob.user_id == current_user.id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Import job не найден")
    _refresh_job_counters(db, job)
    db.commit()
    db.refresh(job)
    return _job_to_response(job, db)


@router.get("/import/direct/jobs/{job_id}/items", response_model=schemas.ImportJobItemsListResponse)
async def get_direct_import_job_items(
    job_id: str,
    offset: int = 0,
    limit: int = 200,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    job = (
        db.query(models.ImportJob)
        .filter(
            models.ImportJob.id == job_id,
            models.ImportJob.user_id == current_user.id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Import job не найден")

    safe_limit = max(1, min(limit, 500))
    items = (
        db.query(models.ImportJobItem)
        .filter(models.ImportJobItem.job_id == job_id)
        .order_by(models.ImportJobItem.position.asc())
        .offset(max(0, offset))
        .limit(safe_limit)
        .all()
    )
    total = db.query(func.count(models.ImportJobItem.id)).filter(models.ImportJobItem.job_id == job_id).scalar() or 0
    return schemas.ImportJobItemsListResponse(items=items, total=total)


@router.post("/import/direct/jobs/{job_id}/retry-failed", response_model=schemas.ImportJobRetryResponse)
async def retry_direct_import_job_failed(
    job_id: str,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    job = (
        db.query(models.ImportJob)
        .filter(
            models.ImportJob.id == job_id,
            models.ImportJob.user_id == current_user.id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Import job не найден")
    if job.status == "cancelled":
        raise HTTPException(status_code=400, detail="Отмененную задачу нельзя перезапустить")

    failed_items = (
        db.query(models.ImportJobItem)
        .filter(
            models.ImportJobItem.job_id == job.id,
            models.ImportJobItem.status == "failed",
        )
        .all()
    )
    for item in failed_items:
        item.status = "pending"
        item.retry_count = 0
        item.error_message = None
        item.updated_at = datetime.utcnow()
    queued = len(failed_items)
    if queued > 0:
        job.status = "pending"
        job.finished_at = None
        job.error_message = None
    _refresh_job_counters(db, job)
    db.commit()
    await _schedule_import_job(job.id)
    db.refresh(job)
    return schemas.ImportJobRetryResponse(job_id=job.id, status=job.status, queued_items=queued)


@router.post("/import/direct/jobs/{job_id}/cancel", response_model=schemas.ImportJobResponse)
async def cancel_direct_import_job(
    job_id: str,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    job = (
        db.query(models.ImportJob)
        .filter(
            models.ImportJob.id == job_id,
            models.ImportJob.user_id == current_user.id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Import job не найден")
    if job.status not in {"completed", "completed_with_errors", "failed", "cancelled"}:
        job.status = "cancelled"
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
    return _job_to_response(job, db)

def _delete_s3_object_sync(object_key: str) -> None:
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=object_key)
    except Exception:
        pass


async def _purge_track_files_async(
    audio_key: str | None,
    cover_key: str | None,
) -> None:
    """Очистка файлов вне hot-path — иначе один worker блокирует /tracks и /token."""
    if audio_key:
        local_file = Path(audio_key)
        if local_file.exists():
            try:
                local_file.unlink()
            except Exception:
                pass
        else:
            await asyncio.to_thread(_delete_s3_object_sync, audio_key)
    if cover_key:
        await asyncio.to_thread(delete_cover_from_s3, cover_key)


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track(
    track_id: str,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(models.Track).filter(models.Track.id == track_id)
    # Если не админ, можно удалять только свои треки
    if not getattr(current_user, 'is_admin', False):
        query = query.filter(models.Track.user_id == current_user.id)

    track = query.first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Трек не найден"
        )

    audio_key = str(track.file_path) if track.file_path else None
    cover_key = str(track.cover_path) if track.cover_path else None
    owner_id = track.user_id

    db.delete(track)
    db.flush()
    _rebuild_cumulative_bytes(db, owner_id)
    db.commit()
    bump_library_revision(db, owner_id)

    background_tasks.add_task(_purge_track_files_async, audio_key, cover_key)

    return None
