"""Скачивание обложек по URL и хранение в S3."""
from __future__ import annotations

import base64
import re
from io import BytesIO

import httpx
from fastapi import HTTPException

from cover_image import normalize_cover_bytes
from s3_utils import S3_BUCKET_NAME, get_s3_client, presigned_url_async

COVER_MAX_BYTES = 5 * 1024 * 1024
COVER_PRESIGN_TTL = 6 * 3600

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


def _normalized_upload(
    cover_data: bytes, cover_key: str, *, square: str = "crop"
) -> str:
    body, content_type = normalize_cover_bytes(cover_data, square=square)
    return _upload_cover_bytes(body, cover_key, content_type=content_type)


def upload_track_cover_to_s3(cover_data: bytes, user_id: int, track_id: str) -> str:
    return _normalized_upload(cover_data, f"covers/{user_id}/{track_id}.webp")


def upload_album_cover_to_s3(cover_data: bytes, user_id: int, album_id: str) -> str:
    return _normalized_upload(cover_data, f"album_covers/{user_id}/{album_id}.webp")


def upload_catalog_radio_cover(cover_data: bytes, station_id: str) -> str:
    return _normalized_upload(
        cover_data, f"radio_covers/catalog/{station_id}.webp", square="pad"
    )


def upload_user_radio_cover(cover_data: bytes, user_id: int, station_id: str) -> str:
    return _normalized_upload(
        cover_data, f"radio_covers/{user_id}/{station_id}.webp", square="pad"
    )


def read_cover_from_s3(cover_key: str) -> bytes:
    s3_client = get_s3_client()
    obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=cover_key)
    return obj["Body"].read()


def delete_cover_from_s3(cover_key: str | None) -> None:
    if not cover_key or not str(cover_key).startswith(
        ("covers/", "album_covers/", "radio_covers/")
    ):
        return
    key = str(cover_key)
    keys = {key}
    if key.endswith(".jpg"):
        keys.add(f"{key[:-4]}.webp")
    elif key.endswith(".webp"):
        keys.add(f"{key[:-5]}.jpg")
    client = get_s3_client()
    for item in keys:
        try:
            client.delete_object(Bucket=S3_BUCKET_NAME, Key=item)
        except Exception:
            pass


async def presigned_cover_url(
    cover_path: str | None,
    *,
    expiration: int = COVER_PRESIGN_TTL,
) -> str | None:
    if not cover_path:
        return None
    key = str(cover_path)
    if not key.startswith(("covers/", "album_covers/", "radio_covers/")):
        return None
    return await presigned_url_async(key, expiration=expiration)


RADIO_COVER_MAX_BYTES = 2 * 1024 * 1024


def decode_cover_data_b64(cover_data: str) -> bytes:
    """Decode base64 or data-URL image. Empty string → b'' (clear)."""
    trimmed = cover_data.strip()
    if not trimmed:
        return b""
    if trimmed.lower().startswith("data:"):
        return decode_data_url_image(trimmed)
    try:
        data = base64.b64decode(trimmed, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="cover_data должен быть валидной base64-строкой",
        ) from exc
    if len(data) > RADIO_COVER_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Обложка превышает максимальный размер {RADIO_COVER_MAX_BYTES} байт",
        )
    return data


async def apply_radio_cover(
    station,
    *,
    catalog: bool,
    user_id: int | None = None,
    cover_data: str | None = None,
    cover_url: str | None = None,
    clear_cover: bool = False,
) -> None:
    """Priority: clear_cover → cover_data → cover_url. Mutates station.cover_path."""

    def _upload(raw: bytes) -> str:
        if catalog:
            return upload_catalog_radio_cover(raw, station.id)
        if user_id is None:
            raise HTTPException(status_code=500, detail="user_id required for user radio cover")
        return upload_user_radio_cover(raw, user_id, station.id)

    if clear_cover:
        delete_cover_from_s3(station.cover_path)
        station.cover_path = None
        return

    if cover_data is not None:
        raw = decode_cover_data_b64(cover_data)
        if raw == b"":
            delete_cover_from_s3(station.cover_path)
            station.cover_path = None
            return
        delete_cover_from_s3(station.cover_path)
        station.cover_path = _upload(raw)
        return

    if cover_url is not None:
        url = cover_url.strip()
        if not url:
            delete_cover_from_s3(station.cover_path)
            station.cover_path = None
            return
        raw = await resolve_cover_image(url)
        if len(raw) > RADIO_COVER_MAX_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Обложка превышает максимальный размер {RADIO_COVER_MAX_BYTES} байт",
            )
        delete_cover_from_s3(station.cover_path)
        station.cover_path = _upload(raw)
