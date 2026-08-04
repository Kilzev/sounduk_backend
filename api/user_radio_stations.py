# api/user_radio_stations.py — пользовательские радиостанции (привязаны к аккаунту)
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
import models
import schemas

router = APIRouter()

NAME_MAX_LEN = 200
URL_MAX_LEN = 2048
GENRE_MAX_LEN = 100
WEBSITE_MAX_LEN = 2048
FREE_STATION_LIMIT = 5


def _to_response(station: models.UserRadioStation) -> schemas.RadioStationResponse:
    return schemas.RadioStationResponse(
        id=station.id,
        name=station.name,
        stream_url=station.stream_url,
        genre=station.genre,
        website=station.website,
        created_at=station.created_at,
        updated_at=station.updated_at,
    )


def _max_stations(user: models.User) -> int:
    return 0x7FFFFFFF if user.is_premium else FREE_STATION_LIMIT


def _validate_item(item: schemas.UserRadioStationItem) -> None:
    name = item.name.strip()
    url = item.stream_url.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Название не может быть пустым",
        )
    if len(name) > NAME_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Название не должно превышать {NAME_MAX_LEN} символов",
        )
    if not url or len(url) > URL_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL потока обязателен и не должен превышать {URL_MAX_LEN} символов",
        )
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL потока должен начинаться с http:// или https://",
        )


@router.get("/radio/stations", response_model=schemas.RadioStationListResponse)
async def list_user_stations(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Возвращает радиостанции, сохранённые за аккаунтом текущего пользователя."""
    stations = (
        db.query(models.UserRadioStation)
        .filter(models.UserRadioStation.user_id == current_user.id)
        .order_by(models.UserRadioStation.name.asc())
        .all()
    )
    return schemas.RadioStationListResponse(
        stations=[_to_response(s) for s in stations],
        total=len(stations),
    )


@router.put("/radio/stations", response_model=schemas.RadioStationListResponse)
async def replace_user_stations(
    payload: schemas.UserRadioStationReplaceRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Полностью заменяет список пользовательских радиостанций (sync с клиента)."""
    max_count = _max_stations(current_user)
    if len(payload.stations) > max_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Лимит радиостанций: {FREE_STATION_LIMIT} для бесплатного аккаунта. "
                "Приобретите премиум для неограниченного количества."
                if not current_user.is_premium
                else "Превышен лимит радиостанций"
            ),
        )

    for item in payload.stations:
        _validate_item(item)

    # Dedup by stream_url (keep first).
    seen_urls: set[str] = set()
    unique_items: list[schemas.UserRadioStationItem] = []
    for item in payload.stations:
        url = item.stream_url.strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique_items.append(item)

    db.query(models.UserRadioStation).filter(
        models.UserRadioStation.user_id == current_user.id
    ).delete()

    now = datetime.utcnow()
    created: list[models.UserRadioStation] = []
    for item in unique_items:
        station = models.UserRadioStation(
            id=(item.id.strip() if item.id and item.id.strip() else uuid.uuid4().hex),
            user_id=current_user.id,
            name=item.name.strip(),
            stream_url=item.stream_url.strip(),
            genre=item.genre.strip()[:GENRE_MAX_LEN] if item.genre else None,
            website=item.website.strip()[:WEBSITE_MAX_LEN] if item.website else None,
            created_at=now,
            updated_at=now,
        )
        db.add(station)
        created.append(station)

    db.commit()
    for s in created:
        db.refresh(s)

    created.sort(key=lambda s: s.name.lower())
    return schemas.RadioStationListResponse(
        stations=[_to_response(s) for s in created],
        total=len(created),
    )


@router.post(
    "/radio/stations",
    response_model=schemas.RadioStationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_station(
    station_in: schemas.RadioStationCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Добавляет одну радиостанцию в аккаунт пользователя."""
    item = schemas.UserRadioStationItem(
        name=station_in.name,
        stream_url=station_in.stream_url,
        genre=station_in.genre,
        website=station_in.website,
    )
    _validate_item(item)

    count = (
        db.query(models.UserRadioStation)
        .filter(models.UserRadioStation.user_id == current_user.id)
        .count()
    )
    if count >= _max_stations(current_user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Лимит радиостанций: {FREE_STATION_LIMIT} для бесплатного аккаунта. "
                "Приобретите премиум для неограниченного количества."
                if not current_user.is_premium
                else "Превышен лимит радиостанций"
            ),
        )

    url = station_in.stream_url.strip()
    exists = (
        db.query(models.UserRadioStation)
        .filter(
            models.UserRadioStation.user_id == current_user.id,
            models.UserRadioStation.stream_url == url,
        )
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Станция с таким URL уже добавлена",
        )

    now = datetime.utcnow()
    station = models.UserRadioStation(
        id=uuid.uuid4().hex,
        user_id=current_user.id,
        name=station_in.name.strip(),
        stream_url=url,
        genre=station_in.genre.strip()[:GENRE_MAX_LEN] if station_in.genre else None,
        website=station_in.website.strip()[:WEBSITE_MAX_LEN] if station_in.website else None,
        created_at=now,
        updated_at=now,
    )
    db.add(station)
    db.commit()
    db.refresh(station)
    return _to_response(station)


@router.delete("/radio/stations/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_station(
    station_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удаляет пользовательскую радиостанцию из аккаунта."""
    station = (
        db.query(models.UserRadioStation)
        .filter(
            models.UserRadioStation.id == station_id,
            models.UserRadioStation.user_id == current_user.id,
        )
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
