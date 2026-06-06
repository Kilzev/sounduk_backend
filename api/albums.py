# api/albums.py - CRUD роуты для работы с альбомами (per-album)
import base64
import binascii
import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
import models

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
    createdAt: Optional[str] = None  # ISO 8601, hint; сервер ставит своё значение
    updatedAt: Optional[str] = None  # ISO 8601, hint; сервер ставит своё значение


class AlbumUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(None, min_length=1, max_length=TITLE_MAX_LEN)
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX_LEN)
    trackIds: Optional[list[str]] = None
    coverArt: Optional[str] = None  # base64 или пустая строка для очистки


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


def _to_out(album: models.Album) -> AlbumOut:
    created_at = album.created_at.isoformat() if album.created_at else ""
    updated_at = album.updated_at.isoformat() if album.updated_at else ""
    return AlbumOut(
        id=album.id,
        title=album.title,
        description=album.description,
        trackIds=_normalize_track_ids(album.track_ids),
        coverArt=_encode_cover_art(album.cover_art),
        createdAt=created_at,
        updatedAt=updated_at,
    )


@router.get("", response_model=list[AlbumOut])
async def get_albums(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    albums = db.query(models.Album).filter(
        models.Album.user_id == current_user.id
    ).order_by(models.Album.created_at.asc()).all()

    return [_to_out(a) for a in albums]


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

    cover_bytes = _decode_cover_art(album_in.coverArt)
    # Для create: пустая строка и None означают "без обложки"
    if cover_bytes == b"":
        cover_bytes = None

    now = datetime.utcnow()

    db_album = models.Album(
        id=album_in.id,
        user_id=current_user.id,
        title=album_in.title,
        description=album_in.description,
        cover_art=cover_bytes,
        track_ids=_normalize_track_ids(album_in.trackIds),
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(db_album)
        db.commit()
        db.refresh(db_album)
    except Exception as exc:
        db.rollback()
        logger.exception("create_album failed for user_id=%s album_id=%s", current_user.id, album_in.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось создать альбом",
        ) from exc

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
    if "coverArt" in data:
        cover_bytes = _decode_cover_art(data["coverArt"])
        # Пустая строка = очистить обложку
        album.cover_art = None if cover_bytes == b"" else cover_bytes

    album.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(album)
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

    db.delete(album)
    db.commit()
    return None
