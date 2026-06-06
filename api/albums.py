# api/albums.py - CRUD роуты для работы с альбомами (per-album)
import base64
import binascii
import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from cover_storage import (
    delete_cover_from_s3,
    read_cover_from_s3,
    resolve_cover_image,
    upload_album_cover_to_s3,
)
from database import get_db
import models
from library_sync import bump_library_revision, current_library_revision

router = APIRouter()
logger = logging.getLogger(__name__)

TITLE_MAX_LEN = 200
DESCRIPTION_MAX_LEN = 2000
COVER_ART_MAX_BYTES = 2 * 1024 * 1024  # 2 MB raw


class AlbumCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=TITLE_MAX_LEN)
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX_LEN)
    trackIds: list[str] = Field(default_factory=list)
    coverArt: Optional[str] = None  # base64-encoded image bytes
    cover_url: Optional[str] = None  # URL → скачать и сохранить в S3
    createdAt: Optional[str] = None  # ISO 8601, hint; сервер ставит своё значение
    updatedAt: Optional[str] = None  # ISO 8601, hint; сервер ставит своё значение


class AlbumUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(None, min_length=1, max_length=TITLE_MAX_LEN)
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX_LEN)
    trackIds: Optional[list[str]] = None
    coverArt: Optional[str] = None  # base64 или пустая строка для очистки
    cover_url: Optional[str] = None  # URL → скачать и сохранить в S3


class AlbumOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    trackIds: list[str] = []
    coverArt: Optional[str] = None
    createdAt: str
    updatedAt: str


def _decode_cover_art(cover_art_b64: Optional[str]) -> Optional[bytes]:
    """Декодирует base64 в bytes. Пустая строка = очистка. None = не менять."""
    if cover_art_b64 is None:
        return None
    if cover_art_b64 == "":
        return b""  # маркер очистки
    try:
        raw = base64.b64decode(cover_art_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="coverArt должен быть валидной base64-строкой"
        )
    if len(raw) > COVER_ART_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"coverArt превышает максимальный размер {COVER_ART_MAX_BYTES} байт"
        )
    return raw


def _encode_cover_art(cover_art_bytes: Optional[bytes]) -> Optional[str]:
    """Кодирует bytes в base64 строку для ответа"""
    if not cover_art_bytes:
        return None
    if isinstance(cover_art_bytes, memoryview):
        cover_art_bytes = cover_art_bytes.tobytes()
    return base64.b64encode(cover_art_bytes).decode("ascii")


def _normalize_track_ids(raw: Any) -> list[str]:
    """Приводит track_ids из БД/клиента к list[str] (защита от битого JSON)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            return []
    return []


def _album_cover_bytes(album: models.Album) -> Optional[bytes]:
    if album.cover_path:
        try:
            return read_cover_from_s3(album.cover_path)
        except Exception as exc:
            logger.warning("Failed to read album cover from S3 %s: %s", album.cover_path, exc)
    if album.cover_art:
        raw = album.cover_art
        if isinstance(raw, memoryview):
            return raw.tobytes()
        return raw
    return None


async def _apply_album_cover_update(
    album: models.Album,
    user_id: int,
    *,
    cover_art_b64: Optional[str] = None,
    cover_url: Optional[str] = None,
) -> None:
    """Обновляет обложку альбома: URL/base64 → S3, пустая строка → очистка."""
    if cover_art_b64 is not None:
        cover_bytes = _decode_cover_art(cover_art_b64)
        if cover_bytes == b"":
            delete_cover_from_s3(album.cover_path)
            album.cover_path = None
            album.cover_art = None
            return
        if cover_bytes is not None:
            delete_cover_from_s3(album.cover_path)
            album.cover_path = upload_album_cover_to_s3(cover_bytes, user_id, album.id)
            album.cover_art = None
        return

    if cover_url is not None:
        url = cover_url.strip()
        if not url:
            delete_cover_from_s3(album.cover_path)
            album.cover_path = None
            album.cover_art = None
            return
        cover_bytes = await resolve_cover_image(url)
        if len(cover_bytes) > COVER_ART_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Обложка превышает максимальный размер {COVER_ART_MAX_BYTES} байт",
            )
        delete_cover_from_s3(album.cover_path)
        album.cover_path = upload_album_cover_to_s3(cover_bytes, user_id, album.id)
        album.cover_art = None


def _to_out(album: models.Album) -> AlbumOut:
    created_at = album.created_at.isoformat() if album.created_at else ""
    updated_at = album.updated_at.isoformat() if album.updated_at else ""
    return AlbumOut(
        id=album.id,
        title=album.title,
        description=album.description,
        trackIds=_normalize_track_ids(album.track_ids),
        coverArt=_encode_cover_art(_album_cover_bytes(album)),
        createdAt=created_at,
        updatedAt=updated_at,
    )


@router.get("")
async def get_albums(
    since_revision: int | None = Query(None, alias="since_revision"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    revision = current_library_revision(db, current_user.id)
    headers = {"X-Library-Revision": str(revision)}

    if since_revision is not None and since_revision == revision:
        return JSONResponse(
            content={"unchanged": True, "revision": revision, "albums": []},
            headers=headers,
        )

    albums = db.query(models.Album).filter(
        models.Album.user_id == current_user.id
    ).order_by(models.Album.created_at.asc()).all()

    album_out = [_to_out(a).model_dump() for a in albums]

    if since_revision is not None:
        return JSONResponse(
            content={
                "unchanged": False,
                "revision": revision,
                "albums": album_out,
            },
            headers=headers,
        )

    return JSONResponse(content=album_out, headers=headers)


@router.get("/{album_id}/cover")
async def get_album_cover(
    album_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    album = db.query(models.Album).filter(
        models.Album.id == album_id,
        models.Album.user_id == current_user.id,
    ).first()
    if not album:
        raise HTTPException(status_code=404, detail="Альбом не найден")

    cover_bytes = _album_cover_bytes(album)
    if not cover_bytes:
        raise HTTPException(status_code=404, detail="Обложка не найдена")

    return Response(
        content=cover_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("", response_model=AlbumOut, status_code=status.HTTP_201_CREATED)
async def create_album(
    album_in: AlbumCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Проверка дубликата id
    existing = db.query(models.Album).filter(
        models.Album.user_id == current_user.id,
        models.Album.id == album_in.id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Альбом с таким id уже существует"
        )

    now = datetime.utcnow()

    db_album = models.Album(
        id=album_in.id,
        user_id=current_user.id,
        title=album_in.title,
        description=album_in.description,
        cover_art=None,
        cover_path=None,
        track_ids=_normalize_track_ids(album_in.trackIds),
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(db_album)
        db.flush()
        if album_in.cover_url:
            await _apply_album_cover_update(
                db_album,
                current_user.id,
                cover_url=album_in.cover_url,
            )
        elif album_in.coverArt is not None:
            await _apply_album_cover_update(
                db_album,
                current_user.id,
                cover_art_b64=album_in.coverArt,
            )
        db.commit()
        db.refresh(db_album)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("create_album failed for user_id=%s album_id=%s", current_user.id, album_in.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось создать альбом",
        ) from exc

    bump_library_revision(db, current_user.id)
    return _to_out(db_album)


@router.put("/{album_id}", response_model=AlbumOut)
async def update_album(
    album_id: str,
    album_update: AlbumUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    album = db.query(models.Album).filter(
        models.Album.id == album_id,
        models.Album.user_id == current_user.id,
    ).first()

    if not album:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Альбом не найден")

    # Partial update — обновляем только переданные поля
    data = album_update.model_dump(exclude_unset=True)

    if "title" in data:
        album.title = data["title"]
    if "description" in data:
        album.description = data["description"]
    if "trackIds" in data:
        album.track_ids = _normalize_track_ids(data["trackIds"])

    try:
        if "cover_url" in data:
            await _apply_album_cover_update(
                album,
                current_user.id,
                cover_url=data["cover_url"],
            )
        elif "coverArt" in data:
            await _apply_album_cover_update(
                album,
                current_user.id,
                cover_art_b64=data["coverArt"],
            )

        album.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(album)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception(
            "update_album failed for user_id=%s album_id=%s",
            current_user.id,
            album_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось обновить альбом",
        ) from exc

    bump_library_revision(db, current_user.id)
    return _to_out(album)


@router.delete("/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_album(
    album_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    album = db.query(models.Album).filter(
        models.Album.id == album_id,
        models.Album.user_id == current_user.id,
    ).first()

    if not album:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Альбом не найден")

    delete_cover_from_s3(album.cover_path)
    db.delete(album)
    db.commit()
    bump_library_revision(db, current_user.id)
    return None
