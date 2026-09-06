# api/user_radio_stations.py — пользовательские радиостанции (привязаны к аккаунту)
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
import cover_storage
import models
import schemas

router = APIRouter()

NAME_MAX_LEN = 200
URL_MAX_LEN = 2048
GENRE_MAX_LEN = 100
WEBSITE_MAX_LEN = 2048
FREE_STATION_LIMIT = 5
_COVER_FIELDS = {"clear_cover", "cover_data", "cover_url"}


async def _to_response(station: models.UserRadioStation) -> schemas.RadioStationResponse:
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
    responses = await asyncio.gather(*[_to_response(s) for s in stations])
    return schemas.RadioStationListResponse(
        stations=list(responses),
        total=len(stations),
    )


@router.put("/radio/stations", response_model=schemas.RadioStationListResponse)
async def replace_user_stations(
    payload: schemas.UserRadioStationReplaceRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Полностью заменяет список пользовательских радиостанций (sync с клиента).

    cover_path сохраняется по старому id — bulk не принимает cover_data.
    """
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

    seen_urls: set[str] = set()
    unique_items: list[schemas.UserRadioStationItem] = []
    for item in payload.stations:
        url = item.stream_url.strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique_items.append(item)

    existing = (
        db.query(models.UserRadioStation)
        .filter(models.UserRadioStation.user_id == current_user.id)
        .all()
    )
    cover_by_id = {s.id: s.cover_path for s in existing if s.cover_path}
    kept_ids = {
        (item.id.strip() if item.id and item.id.strip() else "")
        for item in unique_items
    }
    for old in existing:
        if old.id not in kept_ids and old.cover_path:
            cover_storage.delete_cover_from_s3(old.cover_path)

    db.query(models.UserRadioStation).filter(
        models.UserRadioStation.user_id == current_user.id
    ).delete()

    now = datetime.utcnow()
    created: list[models.UserRadioStation] = []
    for item in unique_items:
        sid = item.id.strip() if item.id and item.id.strip() else uuid.uuid4().hex
        station = models.UserRadioStation(
            id=sid,
            user_id=current_user.id,
            name=item.name.strip(),
            stream_url=item.stream_url.strip(),
            genre=item.genre.strip()[:GENRE_MAX_LEN] if item.genre else None,
            website=item.website.strip()[:WEBSITE_MAX_LEN] if item.website else None,
            cover_path=cover_by_id.get(sid),
            created_at=now,
            updated_at=now,
        )
        db.add(station)
        created.append(station)

    db.commit()
    for s in created:
        db.refresh(s)

    created.sort(key=lambda s: s.name.lower())
    responses = await asyncio.gather(*[_to_response(s) for s in created])
    return schemas.RadioStationListResponse(
        stations=list(responses),
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
    if station_in.cover_data is not None or station_in.cover_url is not None:
        await cover_storage.apply_radio_cover(
            station,
            catalog=False,
            user_id=current_user.id,
            cover_data=station_in.cover_data,
            cover_url=station_in.cover_url,
        )
    db.add(station)
    db.commit()
    db.refresh(station)
    return await _to_response(station)


@router.put("/radio/stations/{station_id}", response_model=schemas.RadioStationResponse)
async def update_user_station(
    station_id: str,
    station_update: schemas.RadioStationUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Обновляет пользовательскую станцию и обложку (за аккаунтом)."""
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

    data = station_update.model_dump(exclude_unset=True)
    if "name" in data:
        name = data["name"].strip()
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
        station.name = name
    if "stream_url" in data:
        url = data["stream_url"].strip()
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
        dup = (
            db.query(models.UserRadioStation)
            .filter(
                models.UserRadioStation.user_id == current_user.id,
                models.UserRadioStation.stream_url == url,
                models.UserRadioStation.id != station_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Станция с таким URL уже добавлена",
            )
        station.stream_url = url
    if "genre" in data:
        genre = data["genre"]
        station.genre = genre.strip()[:GENRE_MAX_LEN] if genre else None
    if "website" in data:
        website = data["website"]
        station.website = website.strip()[:WEBSITE_MAX_LEN] if website else None

    if _COVER_FIELDS & data.keys():
        await cover_storage.apply_radio_cover(
            station,
            catalog=False,
            user_id=current_user.id,
            clear_cover=bool(data.get("clear_cover")),
            cover_data=data["cover_data"] if "cover_data" in data else None,
            cover_url=data["cover_url"] if "cover_url" in data else None,
        )

    station.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(station)
    return await _to_response(station)


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
    cover_storage.delete_cover_from_s3(station.cover_path)
    db.delete(station)
    db.commit()
    return None
