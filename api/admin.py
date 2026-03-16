
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_admin_user, hash_password
import shutil
import os

router = APIRouter()

@router.get("/users", response_model=list[schemas.AdminUserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users

@router.get("/users/{user_id}", response_model=schemas.AdminUserResponse)
async def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user

@router.get("/users/{user_id}/tracks", response_model=schemas.TracksList)
async def list_user_tracks(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    tracks = db.query(models.Track).filter(models.Track.user_id == user_id).all()
    return {"tracks": tracks, "total": len(tracks)}

@router.patch("/users/{user_id}", response_model=schemas.AdminUserResponse)
async def update_user(
    user_id: int,
    user_update: schemas.UserUpdateAdmin,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    # Обновляем поля, если они переданы
    if user_update.username:
        # Проверка уникальности
        existing = db.query(models.User).filter(models.User.username == user_update.username).first()
        if existing and existing.id != user_id:
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = user_update.username
        
    # if user_update.email:
    #     # Проверка уникальности
    #     existing = db.query(models.User).filter(models.User.email == user_update.email).first()
    #     if existing and existing.id != user_id:
    #         raise HTTPException(status_code=400, detail="Email already registered")
    #     user.email = user_update.email
        
    if user_update.password:
        user.hashed_password = hash_password(user_update.password)
        user.plain_password = user_update.password
        
    if user_update.is_premium is not None:
        user.is_premium = user_update.is_premium
        
    if user_update.storage_limit is not None:
        user.storage_limit = user_update.storage_limit
        
    if user_update.is_restricted is not None:
        user.is_restricted = user_update.is_restricted
        
    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    # Удаляем файлы пользователя
    user_dir = f"uploads/{user_id}"
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)
        
    db.delete(user)
    db.commit()
    return None
