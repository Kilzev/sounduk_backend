# token_service.py — ledger токенов SoundSlop (списание/начисление, идемпотентность)
#
# Правила (context/unified_api_spec.md, «SoundSlop + Токены»):
# - баланс = производное ledger `token_transactions`; users.tokens_balance — кэш;
# - списание/начисление атомарно (одна транзакция БД);
# - идемпотентность по (reason, ref_id): повторная операция → None, баланс не двигается.
import logging
import os
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models

tokens_logger = logging.getLogger("sounduk.tokens")


class InsufficientTokens(Exception):
    """Баланс меньше требуемой суммы."""

    def __init__(self, balance: int, required: int):
        super().__init__(f"insufficient tokens: balance={balance} required={required}")
        self.balance = balance
        self.required = required


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        tokens_logger.warning("bad %s=%r, using %d", name, raw, default)
        return default


def cost_per_generation() -> int:
    return _int_env("SOUNDSLOP_COST_PER_TRACK", 10)


def max_duration_sec() -> int:
    return _int_env("SOUNDSLOP_MAX_DURATION_SEC", 180)


def tokens_per_gb() -> int:
    return _int_env("TOKENS_PER_GB_PERMANENT", 40)


def ad_reward_tokens() -> int:
    return _int_env("SOUNDSLOP_AD_REWARD_TOKENS", 1)


def ad_daily_limit() -> int:
    return _int_env("SOUNDSLOP_AD_DAILY_LIMIT", 10)


def apply_transaction(
    db: Session,
    *,
    user: models.User,
    delta: int,
    reason: str,
    ref_id: str | None = None,
) -> models.TokenTransaction | None:
    """Записать транзакцию в ledger и сдвинуть кэш-баланс.

    Возвращает созданную запись или None, если пара (reason, ref_id)
    уже обработана (идемпотентный повтор — webhook retry, дабл-клик).
    """
    if delta == 0:
        raise ValueError("delta must be non-zero")

    new_balance = (user.tokens_balance or 0) + delta
    if new_balance < 0:
        raise InsufficientTokens(balance=user.tokens_balance or 0, required=-delta)

    txn = models.TokenTransaction(
        user_id=user.id, delta=delta, reason=reason, ref_id=ref_id
    )
    user.tokens_balance = new_balance
    db.add(txn)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Уникальный (reason, ref_id) уже есть — повтор webhook'а/коллбека.
        db.rollback()
        db.refresh(user)
        return None
    return txn


def spend_tokens(
    db: Session,
    *,
    user: models.User,
    amount: int,
    reason: str,
    ref_id: str | None = None,
) -> models.TokenTransaction | None:
    """Списать amount токенов. Бросает InsufficientTokens при нехватке."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    return apply_transaction(
        db, user=user, delta=-amount, reason=reason, ref_id=ref_id
    )


def ad_rewards_today(db: Session, user_id: int) -> int:
    """Сколько rewarded-начислений пользователь получил сегодня (UTC)."""
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(models.TokenTransaction)
        .filter(
            models.TokenTransaction.user_id == user_id,
            models.TokenTransaction.reason == "ad_reward",
            models.TokenTransaction.created_at >= day_start,
        )
        .count()
    )
