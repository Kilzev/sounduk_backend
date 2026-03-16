# api/auth.py - Роуты для авторизации
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import hash_password, verify_password, create_access_token, get_current_user
import secrets
import string
from datetime import datetime, timedelta

router = APIRouter()

def generate_recovery_code() -> str:
    """Генерирует надежный код восстановления вида ABCD-1234-EFGH-5678"""
    charset = string.ascii_uppercase + string.digits
    return '-'.join(''.join(secrets.choice(charset) for _ in range(4)) for _ in range(4))

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
    
    recovery_code = generate_recovery_code()
    hashed_recovery_code = hash_password(recovery_code)
    
    new_user = models.User(
        username=user_data.username,
        # email=user_data.email,
        hashed_password=hash_password(user_data.password),
        plain_password=user_data.password,
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
async def recover_password(request: Request, recovery_data: schemas.RecoveryRequest, db: Session = Depends(get_db)):
    client_ip = request.client.host
    if request.headers.get("X-Forwarded-For"):
        client_ip = request.headers.get("X-Forwarded-For").split(",")[0].strip()
    elif request.headers.get("X-Real-IP"):
        client_ip = request.headers.get("X-Real-IP").strip()

    ip_record = db.query(models.IpBlock).filter(models.IpBlock.ip_address == client_ip).first()
    
    # Для /recover проверяем только "hard" лимиты на восстановление, 
    # чтобы забаненный на /login мог использовать /recover.
    # Если заблокирован именно из-за подбора ключей (recover_blocked_until) - не пускаем.
    # Но мы будем использовать поля: failed_attempts для login, 
    # если хотим разделить блокировки. В нашем случае, проще всего сделать так:
    # если идет к /recover с заблокированного через /login IP, мы все равно даем ему шанс 
    # попробовать восстановить пароль, если он не заблокирован по лимиту ВОССТАНОВЛЕНИЯ.
    # Чтобы не усложнять БД, введем логику: эндпоинт recover смотрит только на попытки в самом recover. 
    # Однако, у нас одно поле failed_attempts. 
    # Давайте просто разрешим доступ к /recover, игнорируя проверку blocked_until от логина, 
    # но только ПРИ УСПЕШНОМ вводе кода мы сбросим блокировку. А при НЕУСПЕШНОМ - накинем еще.
    # То есть, бан IP по логину НЕ мешает зайти в /recover.

    # НО, если он забанен жестко (например, на 24 часа), то, возможно, мы его не пустим.
    # Сделаем так: игнорируем бан, кроме баннов на 24 часа? Нет, лучше игнорировать бан вообще, 
    # НО если он ошибается в recovery - жестко баним обратно.
    
    # Не выбрасываем 429 сразу при входе в /recover. 
    # Проверка пароля будет ниже. Если код правильный - снимем бан.
    # Но если он будет брутфорсить сам recovery, мы будем увеличивать failed_attempts.
    
    # Проверяем, не забанен ли он перманентно за сам recovery (если попыток > 10)
    if ip_record and ip_record.blocked_until and ip_record.failed_attempts >= 10:
        if datetime.utcnow() < ip_record.blocked_until:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много попыток восстановления. Попробуйте позже."
            )

    user = db.query(models.User).filter(models.User.username == recovery_data.username).first()
    
    if not user or not user.recovery_code_enc or not verify_password(recovery_data.recovery_code, user.recovery_code_enc):
        if not ip_record:
            ip_record = models.IpBlock(ip_address=client_ip, failed_attempts=1)
            db.add(ip_record)
        else:
            if ip_record.blocked_until and datetime.utcnow() >= ip_record.blocked_until:
                ip_record.failed_attempts = 1
                ip_record.blocked_until = None
            else:
                ip_record.failed_attempts += 1
            
            # Более строгие лимиты для попыток восстановления
            if ip_record.failed_attempts >= 10:
                ip_record.blocked_until = datetime.utcnow() + timedelta(hours=24)
            elif ip_record.failed_attempts >= 5:
                ip_record.blocked_until = datetime.utcnow() + timedelta(minutes=10)
            elif ip_record.failed_attempts >= 3:
                ip_record.blocked_until = datetime.utcnow() + timedelta(seconds=45)
                
        db.commit()
        raise HTTPException(status_code=400, detail="Неверный код восстановления или имя пользователя")
    
    if ip_record:
        ip_record.failed_attempts = 0
        ip_record.blocked_until = None

    user.hashed_password = hash_password(recovery_data.new_password)
    user.plain_password = recovery_data.new_password
    
    new_recovery_code = generate_recovery_code()
    user.recovery_code_enc = hash_password(new_recovery_code)
    
    db.commit()
    
    return {"message": "Пароль успешно сброшен", "new_recovery_code": new_recovery_code}

@router.post("/login", response_model=schemas.Token)
async def login(request: Request, user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    # Получаем IP-адрес клиента с учетом прокси (Nginx)
    client_ip = request.client.host
    if request.headers.get("X-Forwarded-For"):
        client_ip = request.headers.get("X-Forwarded-For").split(",")[0].strip()
    elif request.headers.get("X-Real-IP"):
        client_ip = request.headers.get("X-Real-IP").strip()

    # Проверяем, не заблокирован ли IP
    ip_record = db.query(models.IpBlock).filter(models.IpBlock.ip_address == client_ip).first()
    
    if ip_record and ip_record.blocked_until:
        if datetime.utcnow() < ip_record.blocked_until:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много попыток входа с этого IP. Попробуйте позже."
            )

    user = db.query(models.User).filter(
        models.User.username == user_data.username
    ).first()
    
    # Логика при неверном логине или пароле
    if not user or not verify_password(user_data.password, str(user.hashed_password)):
        if not ip_record:
            ip_record = models.IpBlock(ip_address=client_ip, failed_attempts=1)
            db.add(ip_record)
        else:
            # Если блокировка истекла, сбрасываем попытки
            if ip_record.blocked_until and datetime.utcnow() >= ip_record.blocked_until:
                ip_record.failed_attempts = 1
                ip_record.blocked_until = None
            else:
                ip_record.failed_attempts += 1
            
            # Применяем блокировки по количеству попыток
            if ip_record.failed_attempts >= 7:
                ip_record.blocked_until = datetime.utcnow() + timedelta(days=30)
            elif ip_record.failed_attempts >= 5:
                ip_record.blocked_until = datetime.utcnow() + timedelta(minutes=10)
            elif ip_record.failed_attempts >= 3:
                ip_record.blocked_until = datetime.utcnow() + timedelta(seconds=45)
                
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    # Сброс попыток при успешной авторизации
    if ip_record:
        ip_record.failed_attempts = 0
        ip_record.blocked_until = None
        db.commit()
    
    access_token = create_access_token(data={"sub": user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@router.get("/me", response_model=schemas.UserResponse)
async def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user