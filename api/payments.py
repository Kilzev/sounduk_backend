from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth_utils import get_current_user
from datetime import datetime, timedelta
from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification
import os
import uuid
import json

router = APIRouter()

# --- Конфигурация YooKassa ---
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "your_shop_id")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "your_secret_key")

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

# Карта товаров: ID -> {цена, описание, лимит, дни}
PRODUCTS = {
    "storage_pack_3gb": {
        "price": "99.00",
        "description": "Тариф 3 ГБ",
        "limit": 3 * 1024 * 1024 * 1024,
        "days": 30
    },
    "storage_pack_5gb": {
        "price": "149.00",
        "description": "Тариф 5 ГБ",
        "limit": 5 * 1024 * 1024 * 1024,
        "days": 30
    },
    "storage_pack_20gb": {
        "price": "399.00",
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


@router.post("/create", response_model=schemas.PaymentCreateResponse)
async def create_payment(
    request: schemas.PaymentRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Создание платежа в ЮKassa.
    """
    product = PRODUCTS.get(request.product_id)
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
                "product_id": request.product_id
            }
        }, idempotence_key)

        # Сохраняем в БД
        db_payment = models.Payment(
            id=payment.id,
            user_id=current_user.id,
            product_id=request.product_id,
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

    except Exception as e:
        print(f"YooKassa Error: {e}")
        # Для удобства разработки, если ключи не заданы, возвращаем заглушку
        error_str = str(e)
        if "Authentication failed" in error_str or "401" in error_str or "invalid_credentials" in error_str:
             # MOCK RESPONSE FOR DEV WITHOUT KEYS
             fake_id = str(uuid.uuid4())
             db_payment = models.Payment(
                id=fake_id,
                user_id=current_user.id,
                product_id=request.product_id,
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
        # MOCK FOR DEV
        error_str = str(e)
        if "Authentication failed" in error_str or "401" in error_str or "invalid_credentials" in error_str:
             # Simulating success after some time? Let's just return pending or simulated success
             # For dev purposes, if we hit check status on a dev ID, let's mark it success
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
    grant_premium_access(db, current_user, payment.product_id)
    return schemas.PaymentResponse(
        is_premium=True,
        expires_at=current_user.premium_expires_at
    )
