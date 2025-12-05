# api/tracks.py - Роуты для работы с треками
import email
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, Header, BackgroundTasks
from fastapi.responses import StreamingResponse, Response
import pydantic
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_user, create_stream_token, decode_token
import uuid
import os
import shutil
import asyncio
from pathlib import Path
from s3_utils import get_s3_client, S3_BUCKET_NAME
from fastapi.responses import RedirectResponse
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from mutagen.flac import Picture, FLAC

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
    file_extension = Path(file.filename).suffix
    s3_key = f"tracks/{current_user.id}/{track_id}{file_extension}"
    
    # Вычисляем размер файла
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    # Extract cover art
    cover_data = None
    try:
        audio = MutagenFile(file.file)
        if audio:
            if isinstance(audio, MP3) or file.filename.endswith('.mp3'):
                if audio.tags:
                    for tag in audio.tags.values():
                        if isinstance(tag, APIC):
                            cover_data = tag.data
                            break
            elif isinstance(audio, FLAC) or file.filename.endswith('.flac'):
                if audio.pictures:
                    cover_data = audio.pictures[0].data
        file.file.seek(0)
    except Exception as e:
        print(f"Error extracting cover: {e}")
        file.file.seek(0)

    # Проверка лимитов (если не админ)
    if current_user.role != "admin":
        if current_user.used_space + file_size > current_user.storage_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Превышен лимит хранилища. Использовано: {current_user.used_space / 1024 / 1024:.1f}MB из {current_user.storage_limit / 1024 / 1024:.1f}MB"
            )

    # Upload to S3
    try:
        s3_client = get_s3_client()
        s3_client.upload_fileobj(
            file.file,
            S3_BUCKET_NAME,
            s3_key
        )
        
        if cover_data:
            cover_key = f"tracks/{current_user.id}/{track_id}.jpg"
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=cover_key,
                Body=cover_data,
                ContentType='image/jpeg'
            )
            
    except Exception as e:
        print(f"S3 Upload Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка загрузки файла в хранилище"
        )
    
    # Обновляем использованное место
    current_user.used_space += file_size
    
    new_track = models.Track(
        id=track_id,
        user_id=current_user.id,
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        file_path=s3_key, # Store S3 key instead of local path
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

@router.get("/{track_id}/cover")
async def get_track_cover(
    track_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    track = db.query(models.Track).filter(
        models.Track.id == track_id
    ).first()
    
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Трек не найден"
        )
    
    cover_key = f"tracks/{track.user_id}/{track_id}.jpg"
    
    try:
        s3_client = get_s3_client()
        s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=cover_key)
        
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': cover_key},
            ExpiresIn=3600
        )
        return RedirectResponse(url=url)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Обложка не найдена"
        )

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
    
    # Generate Presigned URL
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': track.file_path},
            ExpiresIn=3600
        )
        return RedirectResponse(url=url)
    except Exception as e:
        print(f"S3 Presign Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка доступа к файлу"
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
    
    # Generate Presigned URL for streaming
    try:
        s3_client = get_s3_client()
        
        # Optional: Add Content-Disposition to force filename in browser download
        filename = f"{track.title}{Path(track.file_path).suffix}"
        encoded_filename = quote(filename)
        
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET_NAME, 
                'Key': track.file_path,
                'ResponseContentDisposition': f"inline; filename*=UTF-8''{encoded_filename}"
            },
            ExpiresIn=3600
        )
        # Redirect to S3. The player will follow this and stream from S3 directly.
        # S3 handles Range requests automatically.
        return RedirectResponse(url=url)
        
    except Exception as e:
        print(f"S3 Presign Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка доступа к файлу"
        )

@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track(
    track_id: str,
    background_tasks: BackgroundTasks,
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
    
    # Обновляем использованное место
    current_user.used_space -= track.file_size
    if current_user.used_space < 0:
        current_user.used_space = 0

    # Delete from S3 in background
    background_tasks.add_task(delete_s3_file, track.file_path)
    
    # Delete cover
    cover_key = f"tracks/{track.user_id}/{track.id}.jpg"
    background_tasks.add_task(delete_s3_file, cover_key)
    
    db.delete(track)
    db.commit()
    
    return None

def delete_s3_file(key: str):
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
    except Exception as e:
        print(f"Error deleting file from S3 {key}: {e}")
