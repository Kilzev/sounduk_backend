# api/radio_stations.py — CRUD роуты для глобального каталога интернет-радиостанций
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth_utils import get_current_admin_user, get_current_user
from database import get_db
import models
import schemas

router = APIRouter()

NAME_MAX_LEN = 200
URL_MAX_LEN = 2048
GENRE_MAX_LEN = 100
WEBSITE_MAX_LEN = 2048


def _to_response(station: models.RadioStation) -> schemas.RadioStationResponse:
    return schemas.RadioStationResponse(
        id=station.id,
        name=station.name,
        stream_url=station.stream_url,
        genre=station.genre,
        website=station.website,
        created_at=station.created_at,
        updated_at=station.updated_at,
    )


@router.get("/stations", response_model=schemas.RadioStationListResponse)
async def list_stations(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Возвращает полный глобальный каталог радиостанций."""
    stations = (
        db.query(models.RadioStation)
        .order_by(models.RadioStation.name.asc())
        .all()
    )
    return schemas.RadioStationListResponse(
        stations=[_to_response(s) for s in stations],
        total=len(stations),
    )


@router.post(
    "/stations",
    response_model=schemas.RadioStationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_station(
    station_in: schemas.RadioStationCreate,
    _admin: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Создаёт новую радиостанцию в глобальном каталоге (только админ)."""
    if len(station_in.name.strip()) > NAME_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Название не должно превышать {NAME_MAX_LEN} символов",
        )
    if len(station_in.stream_url.strip()) > URL_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL потока не должен превышать {URL_MAX_LEN} символов",
        )

    now = datetime.utcnow()
    station = models.RadioStation(
        id=uuid.uuid4().hex,
        name=station_in.name.strip(),
        stream_url=station_in.stream_url.strip(),
        genre=station_in.genre.strip()[:GENRE_MAX_LEN] if station_in.genre else None,
        website=station_in.website.strip()[:WEBSITE_MAX_LEN] if station_in.website else None,
        created_at=now,
        updated_at=now,
    )
    db.add(station)
    db.commit()
    db.refresh(station)
    return _to_response(station)


@router.put("/stations/{station_id}", response_model=schemas.RadioStationResponse)
async def update_station(
    station_id: str,
    station_update: schemas.RadioStationUpdate,
    _admin: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Обновляет радиостанцию в каталоге (только админ)."""
    station = (
        db.query(models.RadioStation)
        .filter(models.RadioStation.id == station_id)
        .first()
    )
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Радиостанция не найдена",
        )

    data = station_update.model_dump(exclude_unset=True)
    if "name" in data:
        station.name = data["name"].strip()
    if "stream_url" in data:
        station.stream_url = data["stream_url"].strip()
    if "genre" in data:
        genre = data["genre"]
        station.genre = genre.strip()[:GENRE_MAX_LEN] if genre else None
    if "website" in data:
        website = data["website"]
        station.website = website.strip()[:WEBSITE_MAX_LEN] if website else None

    station.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(station)
    return _to_response(station)


@router.delete("/stations/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_station(
    station_id: str,
    _admin: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Удаляет радиостанцию из каталога (только админ)."""
    station = (
        db.query(models.RadioStation)
        .filter(models.RadioStation.id == station_id)
        .first()
    )
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Радиостанция не найдена",
        )

    db.delete(station)
    db.commit()
    return None
