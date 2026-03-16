# api/albums.py - Роуты для работы с альбомами
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models
from auth_utils import get_current_user
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()


class AlbumIn(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    coverArt: Optional[list[int]] = None
    trackIds: list[str] = []
    createdAt: str
    updatedAt: str


class AlbumOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    coverArt: Optional[list[int]] = None
    trackIds: list[str] = []
    createdAt: str
    updatedAt: str


@router.get("")
async def get_albums(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    albums = db.query(models.Album).filter(
        models.Album.user_id == current_user.id
    ).all()

    result = []
    for album in albums:
        cover_art = list(album.cover_art) if album.cover_art else None
        result.append(AlbumOut(
            id=album.id,
            title=album.title,
            description=album.description,
            coverArt=cover_art,
            trackIds=album.track_ids or [],
            createdAt=album.created_at.isoformat(),
            updatedAt=album.updated_at.isoformat(),
        ))

    return result


@router.post("")
async def save_albums(
    albums: list[AlbumIn],
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Удаляем все альбомы пользователя
    db.query(models.Album).filter(
        models.Album.user_id == current_user.id
    ).delete()

    # Создаём новые
    for album_in in albums:
        cover_bytes = bytes(album_in.coverArt) if album_in.coverArt else None

        db_album = models.Album(
            id=album_in.id,
            user_id=current_user.id,
            title=album_in.title,
            description=album_in.description,
            cover_art=cover_bytes,
            track_ids=album_in.trackIds,
            created_at=datetime.fromisoformat(album_in.createdAt),
            updated_at=datetime.fromisoformat(album_in.updatedAt),
        )
        db.add(db_album)

    db.commit()
    return {"status": "ok"}
