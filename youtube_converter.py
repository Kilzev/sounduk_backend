"""
Локальная конвертация YouTube → MP3 через yt-dlp и FFmpeg.
Подход как в https://github.com/alperensumeroglu/yt-audio-api (без отдельного Flask-сервиса).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv
from fastapi import HTTPException, status

load_dotenv()

YTDLP_MP3_QUALITY = (os.getenv("YOUTUBE_YTDLP_MP3_QUALITY") or "192").strip()
YTDLP_PROXY = (os.getenv("YTDLP_PROXY") or os.getenv("HTTPS_PROXY") or "").strip()
YTDLP_COOKIES_FILE = (os.getenv("YTDLP_COOKIES_FILE") or "").strip()
# Медленный прокси: 5 MB при ~30 KiB/s может занять >60 с; иначе job делает 3 retry ≈ 3 мин.
YTDLP_SOCKET_TIMEOUT = max(30, int(os.getenv("YTDLP_SOCKET_TIMEOUT", "180")))
TMP_DIR = Path(os.getenv("YOUTUBE_TMP_DIR") or "uploads/youtube_tmp")
TMP_DIR.mkdir(parents=True, exist_ok=True)


def _ffmpeg_location() -> str | None:
    explicit = (os.getenv("FFMPEG_LOCATION") or "").strip()
    if explicit:
        return explicit
    return shutil.which("ffmpeg")


def _build_ydl_opts(output_path: Path) -> dict:
    opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": str(output_path),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": YTDLP_MP3_QUALITY,
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": YTDLP_SOCKET_TIMEOUT,
        "retries": 2,
        "fragment_retries": 2,
        # Меньше блокировок с датацентровых IP (в т.ч. РФ)
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if YTDLP_PROXY:
        opts["proxy"] = YTDLP_PROXY
    if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).is_file():
        opts["cookiefile"] = YTDLP_COOKIES_FILE
    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    return opts


def _resolve_mp3_output_path(base: Path) -> Path:
    direct = base.with_suffix(".mp3")
    if direct.is_file():
        return direct
    matches = sorted(TMP_DIR.glob(f"{base.name}*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if matches:
        return matches[0]
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="yt-dlp завершился без mp3-файла. Проверьте FFmpeg и YTDLP_PROXY.",
    )


def _download_mp3_sync(watch_url: str) -> tuple[Path, str | None, int, str | None, str | None]:
    base = TMP_DIR / uuid.uuid4().hex
    ydl_opts = _build_ydl_opts(base)
    info: dict | None = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(watch_url, download=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось скачать аудио с YouTube (yt-dlp): {exc}",
        ) from exc

    title: str | None = None
    artist: str | None = None
    duration = 0
    if isinstance(info, dict):
        raw_title = info.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            title = raw_title.strip()
        for key in ("artist", "album_artist", "track_artist"):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                artist = value.strip()
                break
        if not artist:
            channel = info.get("channel") or info.get("uploader")
            if isinstance(channel, str) and channel.strip():
                artist = channel.strip()
        try:
            duration = max(0, int(info.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0

    thumbnail_url = _pick_thumbnail_url(info) if isinstance(info, dict) else None
    return _resolve_mp3_output_path(base), title, duration, artist, thumbnail_url


def _pick_thumbnail_url(info: dict) -> str | None:
    thumbnails = info.get("thumbnails")
    if isinstance(thumbnails, list):
        for entry in reversed(thumbnails):
            if isinstance(entry, dict):
                url = entry.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
    thumb = info.get("thumbnail")
    if isinstance(thumb, str) and thumb.strip():
        return thumb.strip()
    return None


def _cleanup_path(path: Path) -> None:
    path.unlink(missing_ok=True)
    stem = path.stem
    for candidate in TMP_DIR.glob(f"{stem}*"):
        candidate.unlink(missing_ok=True)
    # base name without .mp3 suffix (when path is already .mp3)
    root = stem.removesuffix(".mp3") if stem.endswith(".mp3") else stem
    for candidate in TMP_DIR.glob(f"{root}*"):
        candidate.unlink(missing_ok=True)


async def download_youtube_mp3_with_meta(
    watch_url: str,
) -> tuple[bytes, str | None, int, str | None, str | None]:
    path, title, duration, artist, thumbnail_url = await asyncio.to_thread(
        _download_mp3_sync, watch_url
    )
    try:
        return path.read_bytes(), title, duration, artist, thumbnail_url
    finally:
        _cleanup_path(path)


async def download_youtube_mp3_bytes(watch_url: str) -> bytes:
    audio_bytes, _, _, _, _ = await download_youtube_mp3_with_meta(watch_url)
    return audio_bytes


def _flat_playlist_ydl_opts() -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if YTDLP_PROXY:
        opts["proxy"] = YTDLP_PROXY
    if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).is_file():
        opts["cookiefile"] = YTDLP_COOKIES_FILE
    return opts


def expand_playlist_watch_urls_sync(playlist_url: str) -> list[str]:
    """Список watch?v= для плейлиста (через yt-dlp, с прокси если задан)."""
    try:
        with yt_dlp.YoutubeDL(_flat_playlist_ydl_opts()) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось получить список видео плейлиста (yt-dlp): {exc}",
        ) from exc

    entries = info.get("entries") if isinstance(info, dict) else None
    if not entries:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Плейлист пуст или недоступен",
        )

    urls: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        video_id = (entry.get("id") or "").strip()
        if len(video_id) != 11 or video_id in seen:
            continue
        seen.add(video_id)
        urls.append(f"https://www.youtube.com/watch?v={video_id}")
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось извлечь видео из плейлиста",
        )
    return urls
