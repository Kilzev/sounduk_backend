# api/auth.py - Роуты для авторизации
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import hash_password, verify_password, create_access_token, get_current_user
import secrets

router = APIRouter()

@router.post("/register", response_model=schemas.UserRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(models.User).filter(
        models.User.username == user_data.username
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким именем уже существует"
        )
    
    recovery_code = secrets.token_hex(4)
    hashed_recovery_code = hash_password(recovery_code)
    
    new_user = models.User(
        username=user_data.username,
        # email=user_data.email,
        hashed_password=hash_password(user_data.password),
        recovery_code_enc=hashed_recovery_code
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return schemas.UserRegisterResponse(
        id=new_user.id,
        username=new_user.username,
        created_at=new_user.created_at,
        recovery_code=recovery_code,
        storage_limit=new_user.storage_limit,
        is_premium=new_user.is_premium
    )

@router.post("/recover", status_code=status.HTTP_200_OK)
async def recover_password(recovery_data: schemas.RecoveryRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == recovery_data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if not user.recovery_code_enc or not verify_password(recovery_data.recovery_code, user.recovery_code_enc):
        raise HTTPException(status_code=400, detail="Неверный код восстановления или имя пользователя")
    
    user.hashed_password = hash_password(recovery_data.new_password)
    
    new_recovery_code = secrets.token_hex(4)
    user.recovery_code_enc = hash_password(new_recovery_code)
    
    db.commit()
    
    return {"message": "Пароль успешно сброшен", "new_recovery_code": new_recovery_code}

@router.post("/login", response_model=schemas.Token)
async def login(user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.username == user_data.username
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    if not verify_password(user_data.password, str(user.hashed_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    access_token = create_access_token(data={"sub": user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@router.get("/me", response_model=schemas.UserResponse)
async def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user