from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_user, hash_password, verify_password
from typing import Optional

router = APIRouter()

@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Удаляет аккаунт текущего пользователя.
    """
    db.delete(current_user)
    db.commit()
    return None

@router.patch("/me", response_model=schemas.UserResponse)
async def update_me(
    user_update: schemas.UserUpdateSelf,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Изменяет профиль (логин, пароль) текущего пользователя.
    """
    if user_update.username:
        # Check if username exists
        existing_user = db.query(models.User).filter(
            models.User.username == user_update.username
        ).first()
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Имя пользователя уже занято"
            )
        current_user.username = user_update.username

    if user_update.password:
        current_user.hashed_password = hash_password(user_update.password)

    db.commit()
    db.refresh(current_user)
    return current_user

@router.get("/storage/usage", response_model=schemas.StorageUsageResponse)
async def get_storage_usage(
    current_user: models.User = Depends(get_current_user),
):
    """
    Возвращает информацию о занятом месте.
    """
    usage = current_user.storage_used
    limit = current_user.storage_limit
    
    percentage = 0.0
    if limit > 0:
        percentage = (usage / limit) * 100
        
    return schemas.StorageUsageResponse(
        storage_limit=limit,
        storage_used=usage,
        percentage=round(percentage, 2)
    )
