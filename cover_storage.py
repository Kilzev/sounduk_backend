"""Скачивание обложек по URL и хранение в S3."""
from __future__ import annotations

import base64
import re
from io import BytesIO

import httpx
from fastapi import HTTPException

from s3_utils import S3_BUCKET_NAME, get_s3_client

COVER_MAX_BYTES = 5 * 1024 * 1024

_DATA_URL_RE = re.compile(
    r"^data:image/(?P<fmt>jpeg|jpg|png|webp|gif);base64,(?P<b64>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def decode_data_url_image(data_url: str) -> bytes:
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Некорректный data URL обложки")
    try:
        data = base64.b64decode(match.group("b64"), validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Не удалось декодировать base64 обложки") from exc
    if not data:
        raise HTTPException(status_code=400, detail="Пустое изображение")
    if len(data) > COVER_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Обложка слишком большая (макс 5MB)")
    return data


async def resolve_cover_image(source: str) -> bytes:
    trimmed = source.strip()
    if trimmed.lower().startswith("data:"):
        return decode_data_url_image(trimmed)
    return await download_cover_by_url(trimmed)


async def download_cover_by_url(cover_url: str) -> bytes:
    parsed = httpx.URL(cover_url)
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise HTTPException(status_code=400, detail="Некорректный URL обложки")

    headers = {
        "Accept": "application/json,image/*,*/*",
        "User-Agent": "sounduk-backend/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(cover_url, headers=headers)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            if "image" not in content_type and not content_type.startswith("application/octet-stream"):
                raise HTTPException(status_code=400, detail="URL не указывает на изображение")
            if len(response.content) > COVER_MAX_BYTES:
                raise HTTPException(status_code=400, detail="Обложка слишком большая (макс 5MB)")
            return response.content
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось скачать обложку: {exc}") from exc


def _upload_cover_bytes(cover_data: bytes, cover_key: str, content_type: str = "image/jpeg") -> str:
    s3_client = get_s3_client()
    s3_client.upload_fileobj(
        BytesIO(cover_data),
        S3_BUCKET_NAME,
        cover_key,
        ExtraArgs={"ContentType": content_type},
    )
    return cover_key


def upload_track_cover_to_s3(cover_data: bytes, user_id: int, track_id: str) -> str:
    return _upload_cover_bytes(cover_data, f"covers/{user_id}/{track_id}.jpg")


def upload_album_cover_to_s3(cover_data: bytes, user_id: int, album_id: str) -> str:
    return _upload_cover_bytes(cover_data, f"album_covers/{user_id}/{album_id}.jpg")


def read_cover_from_s3(cover_key: str) -> bytes:
    s3_client = get_s3_client()
    obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=cover_key)
    return obj["Body"].read()


def delete_cover_from_s3(cover_key: str | None) -> None:
    if not cover_key or not str(cover_key).startswith(("covers/", "album_covers/")):
        return
    try:
        get_s3_client().delete_object(Bucket=S3_BUCKET_NAME, Key=str(cover_key))
    except Exception:
        pass
