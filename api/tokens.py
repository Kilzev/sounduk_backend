# api/tokens.py — баланс токенов SoundSlop, rewarded-начисления, обмен на хранилище
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
import token_service
from auth_utils import get_current_user
from database import get_db

router = APIRouter()


@router.get("/balance", response_model=schemas.TokenBalanceResponse)
async def get_balance(current_user: models.User = Depends(get_current_user)):
    return schemas.TokenBalanceResponse(
        balance=current_user.tokens_balance or 0,
        cost_per_generation=token_service.cost_per_generation(),
        max_duration_sec=token_service.max_duration_sec(),
        tokens_per_gb=token_service.tokens_per_gb(),
    )


@router.post("/ad-reward", response_model=schemas.AdRewardResponse)
async def ad_reward(
    body: schemas.AdRewardRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Начислить токены за показ rewarded-рекламы (РСЯ).

    Идемпотентно по idempotency_key (клиент генерирует на показ).
    Дневной лимит — 429 при превышении.
    """
    if not body.idempotency_key.strip():
        raise HTTPException(status_code=400, detail="idempotency_key required")

    # Повтор коллбека — не считаем в лимит и не начисляем второй раз.
    existing = (
        db.query(models.TokenTransaction)
        .filter(
            models.TokenTransaction.reason == "ad_reward",
            models.TokenTransaction.ref_id == body.idempotency_key,
        )
        .first()
    )
    if existing is not None:
        db.refresh(current_user)
        return schemas.AdRewardResponse(
            balance=current_user.tokens_balance or 0, granted=0
        )

    if token_service.ad_rewards_today(db, current_user.id) >= token_service.ad_daily_limit():
        raise HTTPException(
            status_code=429, detail="daily ad reward limit reached"
        )

    granted = token_service.ad_reward_tokens()
    token_service.apply_transaction(
        db,
        user=current_user,
        delta=granted,
        reason="ad_reward",
        ref_id=body.idempotency_key,
    )
    db.refresh(current_user)
    return schemas.AdRewardResponse(
        balance=current_user.tokens_balance or 0, granted=granted
    )


@router.post("/redeem-storage", response_model=schemas.RedeemStorageResponse)
async def redeem_storage(
    body: schemas.RedeemStorageRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Обмен токенов на постоянное хранилище (навечно, без подписки)."""
    if body.gb <= 0:
        raise HTTPException(status_code=400, detail="gb must be positive")
    cost = body.gb * token_service.tokens_per_gb()
    try:
        txn = token_service.spend_tokens(
            db,
            user=current_user,
            amount=cost,
            reason="storage_redeem",
            ref_id=f"redeem:{uuid.uuid4()}",
        )
    except token_service.InsufficientTokens as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_tokens",
                "balance": exc.balance,
                "required": exc.required,
            },
        )
    if txn is not None:
        current_user.storage_limit = (current_user.storage_limit or 0) + body.gb * (
            1024**3
        )
        db.add(current_user)
        db.commit()
    db.refresh(current_user)
    return schemas.RedeemStorageResponse(
        balance=current_user.tokens_balance or 0,
        storage_limit=current_user.storage_limit,
        spent=cost,
    )
