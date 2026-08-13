from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_user, get_verified_user
from datetime import datetime, timedelta
from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification
import httpx
import ipaddress
import logging
import os
import uuid
import json
from typing import Optional

router = APIRouter()
payments_logger = logging.getLogger("sounduk.payments")

# --- Конфигурация YooKassa ---
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "your_shop_id")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "your_secret_key")

# Dev-only: mock payment + YooKassa auth-fail fallbacks. Default off for prod.
def _payment_mock_enabled() -> bool:
    return os.getenv("ENABLE_PAYMENT_MOCK", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _payments_geo_enforce() -> bool:
    return os.getenv("PAYMENTS_GEO_ENFORCE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _payments_allowed_countries() -> set[str]:
    raw = os.getenv("PAYMENTS_ALLOWED_COUNTRIES", "RU")
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _is_private_or_local_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    )


def _lookup_country_code(ip: str) -> Optional[str]:
    """Resolve ISO country for a public IP. Returns None on failure / private IP."""
    forced = os.getenv("PAYMENTS_GEO_FORCE_COUNTRY", "").strip().upper()
    if forced:
        return forced

    if not ip or ip == "unknown" or _is_private_or_local_ip(ip):
        return None

    try:
        # Free ip-api.com (HTTP). fields=status,countryCode keeps payload tiny.
        with httpx.Client(timeout=2.5) as client:
            resp = client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,countryCode"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                return None
            code = (data.get("countryCode") or "").strip().upper()
            return code or None
    except Exception as exc:
        payments_logger.warning("geo_lookup_fail ip=%s error=%s", ip, type(exc).__name__)
        return None


def _payment_eligibility(request: Request) -> schemas.PaymentEligibilityResponse:
    """
    Play RU gate: YooKassa only when client country is in allowlist.
    When PAYMENTS_GEO_ENFORCE is off, always allowed (local/dev).
    Lookup failure → not allowed (fail closed) while enforce is on.
    """
    if not _payments_geo_enforce():
        return schemas.PaymentEligibilityResponse(
            allowed=True,
            country=None,
            message_key="payment_region_ok",
        )

    ip = _client_ip(request)
    country = _lookup_country_code(ip)
    allowed = bool(country and country in _payments_allowed_countries())
    return schemas.PaymentEligibilityResponse(
        allowed=allowed,
        country=country,
        message_key="payment_region_ok" if allowed else "payment_region_unavailable",
    )


def _require_payment_region(request: Request) -> None:
    eligibility = _payment_eligibility(request)
    if eligibility.allowed:
        return
    payments_logger.info(
        "payment_geo_denied country=%s ip=%s",
        eligibility.country,
        _client_ip(request),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="payment_region_unavailable",
    )

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

# Карта товаров: ID -> {цена, описание, лимит, дни}
PRODUCTS = {
    "storage_pack_3gb": {
        "price": "65.00",
        "description": "Тариф 3 ГБ",
        "limit": 3 * 1024 * 1024 * 1024,
        "days": 30
    },
    "storage_pack_5gb": {
        "price": "99.00",
        "description": "Тариф 5 ГБ",
        "limit": 5 * 1024 * 1024 * 1024,
        "days": 30
    },
    "storage_pack_20gb": {
        "price": "220.00",
        "description": "Тариф 20 ГБ",
        "limit": 20 * 1024 * 1024 * 1024,
        "days": 30
    }
}

def grant_premium_access(db: Session, user: models.User, product_id: str):
    """Выдает премиум и место пользователю."""
    product = PRODUCTS.get(product_id)
    if not product:
        # Fallback to default
        target_limit = 1 * 1024 * 1024 * 1024
        days = 30
    else:
        target_limit = product["limit"]
        days = product["days"]

    # Обновляем лимит (устанавливаем новый, т.к. это тариф)
    user.storage_limit = target_limit
    user.is_premium = True
    
    current_time = datetime.now()
    if user.premium_expires_at and user.premium_expires_at > current_time:
        user.premium_expires_at += timedelta(days=days)
    else:
        user.premium_expires_at = current_time + timedelta(days=days)

    db.add(user) # ensure tracked
    db.commit()
    db.refresh(user)


@router.get("/eligibility", response_model=schemas.PaymentEligibilityResponse)
async def payment_eligibility(
    http_request: Request,
    current_user: models.User = Depends(get_current_user),
):
    """Whether this client may start YooKassa checkout (geo allowlist)."""
    _ = current_user
    return _payment_eligibility(http_request)


@router.post("/create", response_model=schemas.PaymentCreateResponse)
async def create_payment(
    payment_in: schemas.PaymentRequest,
    http_request: Request,
    current_user: models.User = Depends(get_verified_user),
    db: Session = Depends(get_db)
):
    """
    Создание платежа в ЮKassa.
    """
    _require_payment_region(http_request)

    product = PRODUCTS.get(payment_in.product_id)
    if not product:
        raise HTTPException(status_code=400, detail="Неверный ID товара")

    try:
        idempotence_key = str(uuid.uuid4())
        payment = Payment.create({
            "amount": {
                "value": product["price"],
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://sounduk.ru/payment/success"
            },
            "capture": True,
            "description": f"{product['description']} (User: {current_user.id})",
            "metadata": {
                "user_id": current_user.id,
                "product_id": payment_in.product_id
            }
        }, idempotence_key)

        # Сохраняем в БД
        db_payment = models.Payment(
            id=payment.id,
            user_id=current_user.id,
            product_id=payment_in.product_id,
            amount=int(float(product["price"])), # Store as int for simplicity matching existing model type
            status=payment.status,
            currency="RUB"
        )
        db.add(db_payment)
        db.commit()

        confirmation_url = payment.confirmation.confirmation_url

        return schemas.PaymentCreateResponse(
            payment_id=payment.id,
            confirmation_url=confirmation_url
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"YooKassa Error: {e}")
        error_str = str(e)
        if _payment_mock_enabled() and (
            "Authentication failed" in error_str
            or "401" in error_str
            or "invalid_credentials" in error_str
        ):
             # MOCK RESPONSE FOR DEV WITHOUT KEYS
             fake_id = str(uuid.uuid4())
             db_payment = models.Payment(
                id=fake_id,
                user_id=current_user.id,
                product_id=payment_in.product_id,
                amount=int(float(product["price"])),
                status="pending",
                currency="RUB"
            )
             db.add(db_payment)
             db.commit()
             return schemas.PaymentCreateResponse(
                 payment_id=fake_id,
                 confirmation_url="https://yoomoney.ru/checkout/payments/mock"
             )
        raise HTTPException(status_code=500, detail=f"Ошибка создания платежа: {str(e)}")


@router.get("/{payment_id}/status", response_model=schemas.PaymentStatusResponse)
async def check_payment_status(
    payment_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Проверка статуса платежа (Polling).
    """
    db_payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not db_payment:
        raise HTTPException(status_code=404, detail="Платеж не найден")

    if db_payment.user_id != current_user.id and not getattr(current_user, 'is_admin', False):
         raise HTTPException(status_code=403, detail="Доступ запрещен")

    try:
        # Запрос к ЮKassa
        kassa_payment = Payment.find_one(payment_id)
        status_kassa = kassa_payment.status

        if status_kassa != db_payment.status:
            db_payment.status = status_kassa
            db.commit()
            
            if status_kassa == "succeeded":
                grant_premium_access(db, current_user, db_payment.product_id)

        return schemas.PaymentStatusResponse(status=status_kassa)

    except Exception as e:
        print(f"Check status error: {e}")
        error_str = str(e)
        if _payment_mock_enabled() and (
            "Authentication failed" in error_str
            or "401" in error_str
            or "invalid_credentials" in error_str
        ):
             if db_payment.status == "pending":
                  db_payment.status = "succeeded"
                  db.commit()
                  grant_premium_access(db, current_user, db_payment.product_id)
                  return schemas.PaymentStatusResponse(status="succeeded")

        return schemas.PaymentStatusResponse(status=db_payment.status)


@router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        event_json = await request.json()
        notification_object = WebhookNotification(event_json)
        # TODO: Check IP/Signature if possible (YooKassa SDK usually verifies signature if setup correctly)
        
        if notification_object.event == "payment.succeeded":
            payment = notification_object.object
            payment_id = payment.id
            metadata = payment.metadata
            user_id = int(metadata.get("user_id"))
            product_id = metadata.get("product_id")

            db_payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
            if db_payment:
                db_payment.status = "succeeded"
            else:
                # Create if missing (unexpected but possible)
                product = PRODUCTS.get(product_id)
                price = int(float(product["price"])) if product else 0
                db_payment = models.Payment(
                    id=payment_id,
                    user_id=user_id,
                    product_id=product_id,
                    amount=price,
                    status="succeeded",
                    currency="RUB"
                )
                db.add(db_payment)
            
            db.commit()
            
            user = db.query(models.User).filter(models.User.id == user_id).first()
            if user:
                grant_premium_access(db, user, product_id)
        
        return Response(status_code=200)
    except Exception as e:
        print(f"Webhook error: {e}")
        return Response(status_code=500)

@router.post("/mock", response_model=schemas.PaymentResponse)
async def mock_payment_legacy(
    payment: schemas.PaymentRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not _payment_mock_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )
    grant_premium_access(db, current_user, payment.product_id)
    return schemas.PaymentResponse(
        is_premium=True,
        expires_at=current_user.premium_expires_at
    )
