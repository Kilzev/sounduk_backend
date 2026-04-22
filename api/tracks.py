# api/tracks.py - Роуты для работы с треками
import email
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, Header, BackgroundTasks
from fastapi.responses import StreamingResponse, Response
import pydantic
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
import models
import schemas
from auth_utils import get_current_user, get_verified_user, create_stream_token, decode_token
import uuid
# from s3_utils import upload_file_to_s3, generate_presigned_url, delete_file_from_s3
import os
import shutil
from pathlib import Path
import asyncio
from datetime import datetime
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC
from mutagen.flac import FLAC
from mutagen import File as MutagenFile

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

@router.post("/upload", response_model=schemas.TrackResponse, status_code=status.HTTP_201_CREATED)
async def upload_track(
    file: UploadFile = File(...),
    title: str = Form(...),
    artist: str = Form(...),
    album: str = Form(None),
    duration: int = Form(...),
    created_at: str = Form(None),
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db)
):
    # Проверка лимита места
    total_usage = db.query(func.sum(models.Track.file_size)).filter(
        models.Track.user_id == current_user.id
    ).scalar() or 0
    
    # Размер загружаемого файла (может быть недоступен точно до сохранения, но попробуем оценить)
    # Здесь мы проверяем только текущее использование. Строгую проверку сделаем после сохранения.
    if total_usage >= current_user.storage_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Превышен лимит хранилища"
        )

    if not file.filename or not file.filename.endswith(('.mp3', '.m4a', '.wav', '.flac')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неподдерживаемый формат файла"
        )
    
    file_extension = os.path.splitext(file.filename)[1]
    track_id = str(uuid.uuid4())
    
    # LOCAL STORAGE
    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(exist_ok=True)
    file_path_local = user_dir / f"{track_id}{file_extension}"

    try:
        with open(file_path_local, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path_local)

        # Извлекаем обложку из метаданных
        cover_path = None
        try:
            audio = MutagenFile(str(file_path_local))
            cover_data = None

            if hasattr(audio, 'tags') and audio.tags:
                # MP3 (ID3 tags)
                for tag in audio.tags.values():
                    if isinstance(tag, APIC):
                        cover_data = tag.data
                        break

            if cover_data is None and hasattr(audio, 'pictures'):
                # FLAC
                if audio.pictures:
                    cover_data = audio.pictures[0].data

            if cover_data:
                cover_file = user_dir / f"{track_id}.jpg"
                with open(cover_file, "wb") as cf:
                    cf.write(cover_data)
                cover_path = str(cover_file)
        except Exception as e:
            print(f"Cover extraction error: {e}")

        if total_usage + file_size > current_user.storage_limit:
            os.remove(file_path_local) # Clean up
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Недостаточно места"
            )
            
        new_track = models.Track(
            id=track_id,
            user_id=current_user.id,
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            file_path=str(file_path_local), # Store local path
            file_size=file_size,
            cover_path=cover_path,
            created_at=datetime.fromisoformat(created_at) if created_at else datetime.utcnow()
        )
        
        db.add(new_track)
        db.commit()
        db.refresh(new_track)
        
        return new_track
        
    except Exception as e:
        print(f"Error uploading file: {e}")
        if 'file_path_local' in locals() and file_path_local.exists():
             os.remove(file_path_local)
        raise HTTPException(status_code=500, detail="Ошибка при загрузке файла")

@router.get("/{track_id}/cover")
async def get_track_cover(
    track_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    track = db.query(models.Track).filter(
        models.Track.id == track_id,
        models.Track.user_id == current_user.id
    ).first()

    if not track or not track.cover_path:
        raise HTTPException(status_code=404, detail="Обложка не найдена")

    cover_file = Path(track.cover_path)
    if not cover_file.exists():
        raise HTTPException(status_code=404, detail="Файл обложки не найден")

    return Response(
        content=cover_file.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"}
    )

@router.get("", response_model=schemas.TracksList)
async def get_tracks(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tracks = db.query(models.Track).filter(
        models.Track.user_id == current_user.id
    ).order_by(models.Track.created_at.asc()).all()
    
    current_storage: int = 0
    result_tracks = []
    
    for t in tracks:
        # Устанавливаем статус по умолчанию (модель SQLAlchemy)
        t_dict = t.__dict__.copy()
        
        # Если без премиума общая сумма текущего и всех предыдущих файлов больше 1 ГБ,
        # то этот трек заморожен. (Хотя мы используем current_user.storage_limit 
        # который уже откатился к 1ГБ, если премиум истек).
        current_storage += t.file_size
        
        # Трек считается замороженным, если его добавление превысило текущий лимит пользователя.
        is_frozen = False
        if current_storage > current_user.storage_limit:
            is_frozen = True
            
        t_dict["is_frozen"] = is_frozen
        # Для корректной выдачи в Pydantic убираем служебные поля SQLAlchemy
        if "_sa_instance_state" in t_dict:
            del t_dict["_sa_instance_state"]
            
        result_tracks.append(t_dict)
    
    return {
        "tracks": result_tracks,
        "total": len(result_tracks)
    }

@router.get("/{track_id}/stream")
async def stream_track(
    track_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(models.Track).filter(models.Track.id == track_id)
    # Если не админ, показываем только свои треки
    if not getattr(current_user, 'is_admin', False):
        query = query.filter(models.Track.user_id == current_user.id)
        
    track = query.first()
    
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Трек не найден"
        )
        
    # Проверка на заморозку (если не админ)
    if not getattr(current_user, 'is_admin', False) and track.user_id == current_user.id:
        older_tracks = db.query(models.Track).filter(
            models.Track.user_id == current_user.id,
            models.Track.created_at <= track.created_at
        ).all()
        # Суммируем размер всех старых треков и текущего
        total_size = sum(t.file_size for t in older_tracks)
        
        if total_size > current_user.storage_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Этот трек заморожен, так как превышен лимит хранилища. Оплатите подписку или удалите старые треки."
            )
    
    # Check if this is a path (local) or S3 key
    file_path = Path(str(track.file_path))
    
    if file_path.exists():
        # Local file
        mime_types = {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".flac": "audio/flac"
        }
        mime_type = mime_types.get(file_path.suffix, "audio/mpeg")
        
        def file_iterator():
            with open(file_path, "rb") as file:
                while chunk := file.read(8192):
                    yield chunk
        
        filename = f"{track.title}{file_path.suffix}"
        encoded_filename = quote(filename)
        
        return StreamingResponse(
            file_iterator(),
            media_type=mime_type,
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"
            }
        )
    else:
        # S3 fallback (not configured now)
        raise HTTPException(status_code=404, detail="Файл не найден локально")

@router.get("/{track_id}/token")
async def get_track_token(
    track_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    track = db.query(models.Track).filter(
        models.Track.id == track_id,
        models.Track.user_id == current_user.id
    ).first()
    
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Трек не найден"
        )
        
    # Проверка на заморозку
    older_tracks = db.query(models.Track).filter(
        models.Track.user_id == current_user.id,
        models.Track.created_at <= track.created_at
    ).all()
    total_size = sum(t.file_size for t in older_tracks)
    
    if total_size > current_user.storage_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Этот трек заморожен, так как превышен лимит хранилища. Оплатите подписку или удалите старые треки."
        )
        
    token = create_stream_token(track_id)
    return {"token": token, "url": f"/api/tracks/play/{token}"}

@router.get("/play/{token}")
async def play_track(
    token: str,
    request: Request,
    range: str = Header(None),
    db: Session = Depends(get_db)
):
    try:
        payload = decode_token(token)
        if payload.get("type") != "stream":
            raise HTTPException(status_code=401, detail="Invalid token type")
        track_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Трек не найден"
        )
    
    # Local File Stream with Range support
    file_path = Path(str(track.file_path))
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден на сервере"
        )
    
    file_size = file_path.stat().st_size
    start = 0
    end = file_size - 1
    
    if range:
        try:
            range_str = range.replace("bytes=", "")
            start_str, end_str = range_str.split("-")
            if start_str:
                start = int(start_str)
            if end_str:
                end = int(end_str)
        except ValueError:
            pass
            
    # Ensure valid range
    if start >= file_size:
        start = file_size - 1
    if end >= file_size:
        end = file_size - 1
        
    chunk_size = end - start + 1
    
    mime_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".flac": "audio/flac"
    }
    mime_type = mime_types.get(file_path.suffix, "audio/mpeg")
    
    def file_iterator(start_byte, end_byte):
        with open(file_path, "rb") as file:
            file.seek(start_byte)
            remaining = end_byte - start_byte + 1
            while remaining > 0:
                chunk_size = min(8192, remaining)
                chunk = file.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)
    
    filename = f"{track.title}{file_path.suffix}"
    encoded_filename = quote(filename)
    
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Range": f"bytes {start}-{end}/{file_size}"
    }
    
    return StreamingResponse(
        file_iterator(start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=mime_type,
        headers=headers
    )

@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track(
    track_id: str,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(models.Track).filter(models.Track.id == track_id)
    # Если не админ, можно удалять только свои треки
    if not getattr(current_user, 'is_admin', False):
        query = query.filter(models.Track.user_id == current_user.id)
        
    track = query.first()
    
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Трек не найден"
        )
    
    # Try to delete local file
    file_path = Path(str(track.file_path))
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception:
            pass # Ignore deletion errors

    db.delete(track)
    db.commit()
    
    return None
