# api/tracks.py - Роуты для работы с треками
import email
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, Header
from fastapi.responses import StreamingResponse, Response
import pydantic
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_user
import uuid
import os
import shutil
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
    track = db.query(models.Track).filter(
        models.Track.id == track_id,
        models.Track.user_id == current_user.id
    ).first()
    
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

@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track(
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
    
    file_path = Path(str(track.file_path))
    if file_path.exists():
        file_path.unlink()
    
    db.delete(track)
    db.commit()
    
    return None
