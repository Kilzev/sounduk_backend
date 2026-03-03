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
from auth_utils import get_current_user, create_stream_token, decode_token
import uuid
import os
import shutil
import asyncio
from pathlib import Path

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
    current_user: models.User = Depends(get_current_user),
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
    
    track_id = str(uuid.uuid4())
    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(exist_ok=True)
    
    file_extension = Path(file.filename).suffix
    file_path = user_dir / f"{track_id}{file_extension}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    file_size = os.path.getsize(file_path)
    
    # Вторая, точная проверка после загрузки
    if total_usage + file_size > current_user.storage_limit:
        os.remove(file_path) # Удаляем файл, если не влезает
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Недостаточно места. Лимит: {current_user.storage_limit // 1024 // 1024} MB"
        )
    
    new_track = models.Track(
        id=track_id,
        user_id=current_user.id,
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        file_path=str(file_path),
        file_size=file_size
    )
    
    db.add(new_track)
    db.commit()
    db.refresh(new_track)
    
    return new_track

@router.get("", response_model=schemas.TracksList)
async def get_tracks(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tracks = db.query(models.Track).filter(
        models.Track.user_id == current_user.id
    ).all()
    
    return {
        "tracks": tracks,
        "total": len(tracks)
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
    
    file_path = Path(str(track.file_path))
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден на сервере"
        )
    
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
    
    file_path = Path(str(track.file_path))
    
    # Try to delete file immediately
    if file_path.exists():
        try:
            file_path.unlink()
        except PermissionError:
            # File is likely in use (streaming). Schedule retry in background.
            background_tasks.add_task(remove_file_with_retry, file_path)
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")
    
    db.delete(track)
    db.commit()
    
    return None

async def remove_file_with_retry(path: Path, retries=10, delay=1.0):
    """Attempts to delete a file with retries if it's locked."""
    for i in range(retries):
        try:
            if path.exists():
                path.unlink()
            return
        except PermissionError:
            await asyncio.sleep(delay)
        except Exception as e:
            print(f"Background delete error for {path}: {e}")
            return
    print(f"Failed to delete file {path} after {retries} retries")
