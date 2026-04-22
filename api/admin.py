from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_admin_user, hash_password
import shutil
import os
import json
from datetime import datetime
from typing import Optional

router = APIRouter()


def _get_client_ip(request: Request) -> str:
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers.get("X-Real-IP").strip()
    return request.client.host if request.client else "unknown"


def _log_admin_action(
    db: Session,
    admin: models.User,
    action: str,
    target_user_id: Optional[int],
    details: Optional[dict],
    ip: str,
):
    """Записывает действие админа в журнал"""
    log = models.AdminAuditLog(
        admin_id=admin.id,
        admin_username=admin.username,
        action=action,
        target_user_id=target_user_id,
        details=json.dumps(details, ensure_ascii=False) if details else None,
        ip_address=ip,
    )
    db.add(log)
    db.commit()


def _count_active_admins(db: Session) -> int:
    return db.query(models.User).filter(
        models.User.is_admin == True,
        models.User.is_restricted == False,
    ).count()


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
    request: Request,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    is_self = user.id == current_admin.id

    # Защита от self-demotion: админ не может снять с себя права/заблокировать/удалить верификацию
    if is_self:
        if user_update.is_admin is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нельзя снять с себя права администратора"
            )
        if user_update.is_restricted is True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нельзя заблокировать самого себя"
            )

    # Защита от "потери последнего админа": нельзя снять права с последнего активного админа
    if (user_update.is_admin is False and user.is_admin) or \
       (user_update.is_restricted is True and user.is_admin and not user.is_restricted):
        if _count_active_admins(db) <= 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="В системе должен остаться хотя бы один активный администратор"
            )

    changes = {}

    if user_update.username:
        existing = db.query(models.User).filter(models.User.username == user_update.username).first()
        if existing and existing.id != user_id:
            raise HTTPException(status_code=400, detail="Username already taken")
        changes["username"] = {"old": user.username, "new": user_update.username}
        user.username = user_update.username

    if user_update.email:
        email_lower = user_update.email.strip().lower()
        existing = db.query(models.User).filter(models.User.email == email_lower).first()
        if existing and existing.id != user_id:
            raise HTTPException(status_code=400, detail="Email already registered")
        changes["email"] = {"old": user.email, "new": email_lower}
        user.email = email_lower

    if user_update.password:
        user.hashed_password = hash_password(user_update.password)
        changes["password"] = "reset"

    if user_update.is_premium is not None and user_update.is_premium != user.is_premium:
        changes["is_premium"] = {"old": user.is_premium, "new": user_update.is_premium}
        user.is_premium = user_update.is_premium

    if user_update.storage_limit is not None and user_update.storage_limit != user.storage_limit:
        changes["storage_limit"] = {"old": user.storage_limit, "new": user_update.storage_limit}
        user.storage_limit = user_update.storage_limit

    if user_update.is_restricted is not None and user_update.is_restricted != user.is_restricted:
        changes["is_restricted"] = {"old": user.is_restricted, "new": user_update.is_restricted}
        user.is_restricted = user_update.is_restricted

    if user_update.is_verified is not None and user_update.is_verified != user.is_verified:
        changes["is_verified"] = {"old": user.is_verified, "new": user_update.is_verified}
        user.is_verified = user_update.is_verified

    if user_update.is_admin is not None and user_update.is_admin != user.is_admin:
        changes["is_admin"] = {"old": user.is_admin, "new": user_update.is_admin}
        user.is_admin = user_update.is_admin

    db.commit()
    db.refresh(user)

    if changes:
        action = "grant_admin" if changes.get("is_admin", {}).get("new") is True \
            else "revoke_admin" if changes.get("is_admin", {}).get("new") is False \
            else "update_user"
        _log_admin_action(db, current_admin, action, user_id, changes, _get_client_ip(request))

    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Защита от self-delete
    if user.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя удалить самого себя"
        )

    # Защита от удаления последнего админа
    if user.is_admin and _count_active_admins(db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя удалить последнего администратора"
        )

    # Сохраняем детали до удаления (для лога)
    details = {
        "username": user.username,
        "email": user.email,
        "was_admin": user.is_admin,
    }

    # Удаляем файлы пользователя
    user_dir = f"uploads/{user_id}"
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)

    db.delete(user)
    db.commit()

    _log_admin_action(db, current_admin, "delete_user", user_id, details, _get_client_ip(request))

    return None


@router.get("/audit-log", response_model=list[schemas.AdminAuditLogResponse])
async def get_audit_log(
    skip: int = 0,
    limit: int = 100,
    target_user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user)
):
    """Журнал действий администраторов (последние действия сверху)"""
    query = db.query(models.AdminAuditLog)
    if target_user_id is not None:
        query = query.filter(models.AdminAuditLog.target_user_id == target_user_id)
    logs = query.order_by(models.AdminAuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return logs
