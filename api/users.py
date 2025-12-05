from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_user, ADMIN_SECRET_KEY

router = APIRouter()

@router.post("/upgrade", response_model=schemas.UserResponse)
async def upgrade_tier(
    tier: str = Body(..., embed=True), # "subscriber" or "admin"
    admin_token: str = Body(..., embed=True), # Токен подтверждения
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Обновляет уровень подписки пользователя.
    Требует admin_token для подтверждения.
    """
    # Простая проверка токена (в реальности это может быть подпись платежа)
    if admin_token != ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Неверный токен подтверждения"
        )

    if tier == "subscriber":
        current_user.role = "subscriber"
        current_user.storage_limit = 5 * 1024 * 1024 * 1024 # 5 GB
    elif tier == "admin":
        current_user.role = "admin"
    else:
        raise HTTPException(status_code=400, detail="Неверный тип подписки")
    
    db.commit()
    db.refresh(current_user)
    return current_user

@router.post("/add_space", response_model=schemas.UserResponse)
async def add_extra_space(
    megabytes: int = Body(..., embed=True),
    secret_code: str = Body(..., embed=True), # Секретный код от рекламы
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Добавляет дополнительное место.
    Требует секретный код (например, от рекламного SDK).
    """
    # В реальном приложении этот код должен генерироваться на сервере и проверяться
    # Для примера используем фиксированный "AD_WATCHED_SUCCESS"
    if secret_code != "AD_WATCHED_SUCCESS":
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Неверный код подтверждения"
        )

    bytes_to_add = megabytes * 1024 * 1024
    current_user.storage_limit += bytes_to_add
    
    db.commit()
    db.refresh(current_user)
    return current_user
