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
from pathlib import Path
from s3_utils import get_s3_client, S3_BUCKET_NAME

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


def _normalize_possible_s3_key(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    if path_value.startswith("/"):
        return None
    if "://" in path_value:
        parts = path_value.split("/", 3)
        if len(parts) < 4:
            return None
        return parts[3]
    return path_value


def _collect_user_s3_keys(user_id: int, tracks: list[models.Track]) -> set[str]:
    keys: set[str] = set()
    for track in tracks:
        for value in (track.file_path, track.cover_path):
            key = _normalize_possible_s3_key(value)
            if key:
                keys.add(key)
    # Common user-scoped prefixes (legacy/new layouts).
    prefixes = (
        f"{user_id}/",
        f"uploads/{user_id}/",
        f"user_{user_id}/",
    )
    try:
        s3 = get_s3_client()
        paginator = s3.get_paginator("list_objects_v2")
        for prefix in prefixes:
            for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj.get("Key")
                    if key:
                        keys.add(key)
    except Exception:
        # Prefix scan is best-effort only; explicit keys from DB are still used.
        pass
    return keys


def _delete_s3_keys(keys: list[str]) -> int:
    if not keys:
        return 0
    s3 = get_s3_client()
    deleted = 0
    for i in range(0, len(keys), 1000):
        chunk = keys[i : i + 1000]
        s3.delete_objects(
            Bucket=S3_BUCKET_NAME,
            Delete={"Objects": [{"Key": k} for k in chunk]},
        )
        deleted += len(chunk)
    return deleted


def _cleanup_user_tracks_data(
    user_id: int,
    db: Session,
    delete_db_records: bool,
    dry_run: bool,
) -> schemas.AdminUserTracksCleanupResponse:
    tracks = db.query(models.Track).filter(models.Track.user_id == user_id).all()
    track_ids = {t.id for t in tracks}
    errors: list[str] = []

    local_deleted = 0
    local_missing = 0
    for t in tracks:
        for value in (t.file_path, t.cover_path):
            if not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                continue
            if path.exists():
                if not dry_run:
                    try:
                        path.unlink()
                    except Exception as e:
                        errors.append(f"local_delete_failed:{path}:{e}")
                        continue
                local_deleted += 1
            else:
                local_missing += 1

    s3_deleted = 0
    try:
        s3_keys = sorted(_collect_user_s3_keys(user_id, tracks))
        if not dry_run and s3_keys:
            s3_deleted = _delete_s3_keys(s3_keys)
        elif dry_run:
            s3_deleted = len(s3_keys)
    except Exception as e:
        errors.append(f"s3_cleanup_failed:{e}")

    db_deleted = 0
    if delete_db_records and track_ids:
        if not dry_run:
            db_deleted = db.query(models.Track).filter(models.Track.user_id == user_id).delete()
            db.commit()
        else:
            db_deleted = len(track_ids)

    return schemas.AdminUserTracksCleanupResponse(
        user_id=user_id,
        tracks_in_db=len(track_ids),
        local_files_deleted=local_deleted,
        local_files_missing=local_missing,
        s3_objects_deleted=s3_deleted,
        db_tracks_deleted=db_deleted,
        dry_run=dry_run,
        errors=errors,
    )


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


@router.post(
    "/users/{user_id}/tracks/cleanup",
    response_model=schemas.AdminUserTracksCleanupResponse,
)
async def cleanup_user_tracks(
    user_id: int,
    payload: schemas.AdminUserTracksCleanupRequest,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    expected = f"DELETE USER {user_id} TRACKS"
    if payload.confirm.strip() != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Неверное подтверждение. Ожидается: '{expected}'",
        )

    return _cleanup_user_tracks_data(
        user_id=user_id,
        db=db,
        delete_db_records=True,
        dry_run=payload.dry_run,
    )


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

    # Удаляем треки пользователя (локальные файлы + S3 + записи tracks),
    # затем удаляем самого пользователя.
    _cleanup_user_tracks_data(
        user_id=user_id,
        db=db,
        delete_db_records=True,
        dry_run=False,
    )

    # Дополнительная страховка: удаляем директорию пользователя целиком.
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
