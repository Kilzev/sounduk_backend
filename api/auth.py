# api/auth.py - Роуты для авторизации
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import hash_password, verify_password, create_access_token, get_current_user
from email_utils import generate_verification_code, send_verification_email, send_password_reset_email
from datetime import datetime, timedelta

router = APIRouter()

VERIFICATION_CODE_TTL_MINUTES = 10
RESEND_COOLDOWN_SECONDS = 60
MAX_REGISTRATIONS_PER_IP = 3
REGISTRATION_WINDOW_HOURS = 24


def _get_client_ip(request: Request) -> str:
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers.get("X-Real-IP").strip()
    return request.client.host


def _check_registration_rate_limit(client_ip: str, db: Session):
    """Проверяет лимит регистраций с одного IP (макс 3 за 24 часа)"""
    record = db.query(models.RegistrationLimit).filter(
        models.RegistrationLimit.ip_address == client_ip
    ).first()

    if not record:
        return

    window_start = datetime.utcnow() - timedelta(hours=REGISTRATION_WINDOW_HOURS)

    if record.first_registration_at < window_start:
        record.registrations_count = 0
        record.first_registration_at = datetime.utcnow()
        db.commit()
        return

    if record.registrations_count >= MAX_REGISTRATIONS_PER_IP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много регистраций с этого IP. Попробуйте позже."
        )


def _increment_registration_count(client_ip: str, db: Session):
    record = db.query(models.RegistrationLimit).filter(
        models.RegistrationLimit.ip_address == client_ip
    ).first()

    if not record:
        record = models.RegistrationLimit(
            ip_address=client_ip,
            registrations_count=1,
            first_registration_at=datetime.utcnow()
        )
        db.add(record)
    else:
        record.registrations_count += 1
    db.commit()


@router.post("/register", response_model=schemas.UserRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    client_ip = _get_client_ip(request)

    _check_registration_rate_limit(client_ip, db)

    if db.query(models.User).filter(models.User.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким именем уже существует"
        )

    email_lower = user_data.email.strip().lower()
    if db.query(models.User).filter(models.User.email == email_lower).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот email уже зарегистрирован"
        )

    verification_code = generate_verification_code()

    new_user = models.User(
        username=user_data.username,
        email=email_lower,
        hashed_password=hash_password(user_data.password),
        is_verified=False,
        verification_code=verification_code,
        code_sent_at=datetime.utcnow(),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    send_verification_email(email_lower, verification_code)
    _increment_registration_count(client_ip, db)

    return new_user


@router.post("/verify")
async def verify_email(data: schemas.VerifyEmailRequest, db: Session = Depends(get_db)):
    """Подтверждение email по 6-значному коду"""
    email_lower = data.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email_lower).first()

    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")

    if user.is_verified:
        return {"message": "Email уже подтверждён"}

    if not user.verification_code or not user.code_sent_at:
        raise HTTPException(status_code=400, detail="Код не был отправлен. Запросите повторно.")

    if datetime.utcnow() > user.code_sent_at + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES):
        raise HTTPException(status_code=400, detail="Код истёк. Запросите новый.")

    if data.code != user.verification_code:
        raise HTTPException(status_code=400, detail="Неверный код")

    user.is_verified = True
    user.verification_code = None
    user.code_sent_at = None
    db.commit()

    return {"message": "Email подтверждён"}


@router.post("/resend-code")
async def resend_verification_code(data: schemas.ResendCodeRequest, db: Session = Depends(get_db)):
    """Повторная отправка кода подтверждения регистрации"""
    email_lower = data.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email_lower).first()

    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")

    if user.is_verified:
        return {"message": "Email уже подтверждён"}

    if user.code_sent_at:
        seconds_since = (datetime.utcnow() - user.code_sent_at).total_seconds()
        if seconds_since < RESEND_COOLDOWN_SECONDS:
            wait = int(RESEND_COOLDOWN_SECONDS - seconds_since)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Подождите {wait} сек. перед повторной отправкой"
            )

    code = generate_verification_code()
    user.verification_code = code
    user.code_sent_at = datetime.utcnow()
    db.commit()

    send_verification_email(email_lower, code)

    return {"message": "Код отправлен повторно"}


@router.post("/forgot-password")
async def forgot_password(data: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Запрос сброса пароля — отправляет код на email"""
    email_lower = data.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email_lower).first()

    # Чтобы не раскрывать существование email, возвращаем одинаковый ответ
    if not user:
        return {"message": "Если такой email существует, код отправлен"}

    # Cooldown
    if user.code_sent_at:
        seconds_since = (datetime.utcnow() - user.code_sent_at).total_seconds()
        if seconds_since < RESEND_COOLDOWN_SECONDS:
            wait = int(RESEND_COOLDOWN_SECONDS - seconds_since)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Подождите {wait} сек. перед повторным запросом"
            )

    code = generate_verification_code()
    user.verification_code = code
    user.code_sent_at = datetime.utcnow()
    db.commit()

    send_password_reset_email(email_lower, code)

    return {"message": "Если такой email существует, код отправлен"}


@router.post("/reset-password")
async def reset_password(request: Request, data: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    """Сброс пароля по коду из email"""
    client_ip = _get_client_ip(request)

    ip_record = db.query(models.IpBlock).filter(models.IpBlock.ip_address == client_ip).first()
    if ip_record and ip_record.blocked_until and ip_record.failed_attempts >= 10:
        if datetime.utcnow() < ip_record.blocked_until:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много попыток сброса. Попробуйте позже."
            )

    email_lower = data.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email_lower).first()

    def _register_failure():
        nonlocal ip_record
        if not ip_record:
            ip_record = models.IpBlock(ip_address=client_ip, failed_attempts=1)
            db.add(ip_record)
        else:
            if ip_record.blocked_until and datetime.utcnow() >= ip_record.blocked_until:
                ip_record.failed_attempts = 1
                ip_record.blocked_until = None
            else:
                ip_record.failed_attempts += 1
            if ip_record.failed_attempts >= 10:
                ip_record.blocked_until = datetime.utcnow() + timedelta(hours=24)
            elif ip_record.failed_attempts >= 5:
                ip_record.blocked_until = datetime.utcnow() + timedelta(minutes=10)
            elif ip_record.failed_attempts >= 3:
                ip_record.blocked_until = datetime.utcnow() + timedelta(seconds=45)
        db.commit()

    if not user or not user.verification_code or not user.code_sent_at:
        _register_failure()
        raise HTTPException(status_code=400, detail="Неверный код или email")

    if datetime.utcnow() > user.code_sent_at + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES):
        _register_failure()
        raise HTTPException(status_code=400, detail="Код истёк. Запросите новый.")

    if data.code != user.verification_code:
        _register_failure()
        raise HTTPException(status_code=400, detail="Неверный код или email")

    # Успех — сбрасываем пароль
    user.hashed_password = hash_password(data.new_password)
    user.verification_code = None
    user.code_sent_at = None
    # При сбросе пароля автоматически верифицируем email (т.к. пользователь доказал владение)
    user.is_verified = True
    db.commit()

    if ip_record:
        ip_record.failed_attempts = 0
        ip_record.blocked_until = None
        db.commit()

    return {"message": "Пароль успешно сброшен"}


@router.post("/login", response_model=schemas.Token)
async def login(request: Request, user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    client_ip = _get_client_ip(request)

    ip_record = db.query(models.IpBlock).filter(models.IpBlock.ip_address == client_ip).first()

    if ip_record and ip_record.blocked_until:
        if datetime.utcnow() < ip_record.blocked_until:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много попыток входа с этого IP. Попробуйте позже."
            )

    email_lower = user_data.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email_lower).first()

    if not user or not verify_password(user_data.password, str(user.hashed_password)):
        if not ip_record:
            ip_record = models.IpBlock(ip_address=client_ip, failed_attempts=1)
            db.add(ip_record)
        else:
            if ip_record.blocked_until and datetime.utcnow() >= ip_record.blocked_until:
                ip_record.failed_attempts = 1
                ip_record.blocked_until = None
            else:
                ip_record.failed_attempts += 1

            if ip_record.failed_attempts >= 7:
                ip_record.blocked_until = datetime.utcnow() + timedelta(days=30)
            elif ip_record.failed_attempts >= 5:
                ip_record.blocked_until = datetime.utcnow() + timedelta(minutes=10)
            elif ip_record.failed_attempts >= 3:
                ip_record.blocked_until = datetime.utcnow() + timedelta(seconds=45)

        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль"
        )

    if ip_record:
        ip_record.failed_attempts = 0
        ip_record.blocked_until = None
        db.commit()

    # JWT sub = user.id (устойчив к смене email/username)
    access_token = create_access_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.get("/me", response_model=schemas.UserResponse)
async def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user
