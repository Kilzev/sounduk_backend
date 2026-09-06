# api/radio_stations.py — CRUD роуты для глобального каталога интернет-радиостанций
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth_utils import get_current_admin_user, get_current_user
from database import get_db
import cover_storage
import models
import schemas

router = APIRouter()

NAME_MAX_LEN = 200
URL_MAX_LEN = 2048
GENRE_MAX_LEN = 100
WEBSITE_MAX_LEN = 2048
_COVER_FIELDS = {"clear_cover", "cover_data", "cover_url"}


async def _to_response(station: models.RadioStation) -> schemas.RadioStationResponse:
    return schemas.RadioStationResponse(
        id=station.id,
        name=station.name,
        stream_url=station.stream_url,
        genre=station.genre,
        website=station.website,
        cover_url=await cover_storage.presigned_cover_url(station.cover_path),
        created_at=station.created_at,
        updated_at=station.updated_at,
    )


def _validate_name_url(name: str, stream_url: str) -> None:
    if len(name.strip()) > NAME_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Название не должно превышать {NAME_MAX_LEN} символов",
        )
    if len(stream_url.strip()) > URL_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL потока не должен превышать {URL_MAX_LEN} символов",
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
    responses = await asyncio.gather(*[_to_response(s) for s in stations])
    return schemas.RadioStationListResponse(
        stations=list(responses),
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
    _validate_name_url(station_in.name, station_in.stream_url)

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
    if station_in.cover_data is not None or station_in.cover_url is not None:
        await cover_storage.apply_radio_cover(
            station,
            catalog=True,
            cover_data=station_in.cover_data,
            cover_url=station_in.cover_url,
        )
    db.add(station)
    db.commit()
    db.refresh(station)
    return await _to_response(station)


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

    if _COVER_FIELDS & data.keys():
        await cover_storage.apply_radio_cover(
            station,
            catalog=True,
            clear_cover=bool(data.get("clear_cover")),
            cover_data=data["cover_data"] if "cover_data" in data else None,
            cover_url=data["cover_url"] if "cover_url" in data else None,
        )

    station.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(station)
    return await _to_response(station)


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

    cover_storage.delete_cover_from_s3(station.cover_path)
    db.delete(station)
    db.commit()
    return None
