# soundslop_provider.py — адаптер провайдера генерации музыки (fal.ai)
#
# Дизайн (context/soundslop_design.md §3):
# - модель — конфигом (env), смена без правок кода;
# - пул ключей SOUNDSLOP_PROVIDER_KEYS (через запятую): round-robin + skip при 429;
# - опциональный прокси SOUNDSLOP_PROXY (паттерн jump-хоста);
# - синхронный endpoint fal.run: вызов ждёт результат — выполняется в фоновой
#   задаче воркера, пользовательский HTTP не держит (1 uvicorn worker).
import itertools
import logging
import os
from typing import Any, Optional

import httpx

provider_logger = logging.getLogger("sounduk.soundslop")

_FAL_BASE = "https://fal.run"

# Подтверждено на момент интеграции (2026-10): Stable Audio 3 Medium на fal.
# MiniMax Music 2.0 (~$0.03/песня с вокалом) — задать через env после smoke.
DEFAULT_MODEL_TEXT = "fal-ai/stable-audio-3/medium/text-to-audio"
DEFAULT_MODEL_AUDIO = "fal-ai/stable-audio-3/medium/audio-to-audio"

_key_cycle: Optional[itertools.cycle] = None


class ProviderNotConfigured(Exception):
    """Нет ни одного ключа провайдера (SOUNDSLOP_PROVIDER_KEYS пуст)."""


class ProviderError(Exception):
    """Провайдер отклонил/не смог выполнить генерацию."""


def _provider_keys() -> list[str]:
    raw = os.getenv("SOUNDSLOP_PROVIDER_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _next_key() -> str:
    global _key_cycle
    keys = _provider_keys()
    if not keys:
        raise ProviderNotConfigured("SOUNDSLOP_PROVIDER_KEYS is empty")
    if _key_cycle is None or len(keys) == 1:
        _key_cycle = itertools.cycle(keys)
    return next(_key_cycle)


def _model_for(mode: str) -> str:
    if mode in ("audio", "extend"):
        return os.getenv("SOUNDSLOP_FAL_MODEL_AUDIO", DEFAULT_MODEL_AUDIO)
    return os.getenv("SOUNDSLOP_FAL_MODEL_TEXT", DEFAULT_MODEL_TEXT)


def _build_payload(
    *,
    mode: str,
    prompt: str,
    duration_sec: int,
    instrumental: bool,
    source_audio_url: Optional[str],
    strength: Optional[float],
) -> dict[str, Any]:
    """Тело запроса под модель. Поля Stable Audio 3 на fal;
    при смене модели через env сверить со схемой модели в доке fal."""
    if mode == "text":
        return {
            "prompt": prompt,
            "seconds_total": duration_sec,
            # instrumental поддерживается не всеми моделями — мягкий хинт в промпте
        }
    # audio / extend: audio-to-audio (extend v1.1 — та же модель-семья)
    payload: dict[str, Any] = {
        "prompt": prompt,
        "audio_url": source_audio_url,
        "strength": strength if strength is not None else 0.7,
    }
    return payload


def _extract_audio_url(data: Any) -> Optional[str]:
    """Терпимый разбор ответа: первая http(s)-ссылка на аудио в дереве."""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and value.startswith("http") and (
                "audio" in key or key == "url"
            ):
                return value
        for value in data.values():
            found = _extract_audio_url(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_audio_url(item)
            if found:
                return found
    return None


async def submit_generation(
    *,
    mode: str,
    prompt: str,
    duration_sec: int,
    instrumental: bool,
    source_audio_url: Optional[str] = None,
    strength: Optional[float] = None,
    timeout_sec: float = 600.0,
) -> str:
    """Отправить генерацию в fal и дождаться результата.

    Возвращает URL готового аудио. Бросает ProviderNotConfigured /
    ProviderError — воркер переводит job в failed + refund.
    """
    model = _model_for(mode)
    payload = _build_payload(
        mode=mode,
        prompt=prompt,
        duration_sec=duration_sec,
        instrumental=instrumental,
        source_audio_url=source_audio_url,
        strength=strength,
    )
    proxy = os.getenv("SOUNDSLOP_PROXY") or None
    keys_tried: set[str] = set()
    last_error: Optional[Exception] = None

    # Пул: до len(keys) попыток (skip ключа при 429).
    for _ in range(max(1, len(_provider_keys()))):
        key = _next_key()
        if key in keys_tried:
            break
        keys_tried.add(key)
        try:
            async with httpx.AsyncClient(
                timeout=timeout_sec, proxy=proxy
            ) as client:
                resp = await client.post(
                    f"{_FAL_BASE}/{model}",
                    json=payload,
                    headers={
                        "Authorization": f"Key {key}",
                        "Accept": "application/json",
                    },
                )
            if resp.status_code == 429:
                provider_logger.warning(
                    "fal 429 model=%s key#%d — пробуем следующий ключ",
                    model,
                    len(keys_tried),
                )
                continue
            if resp.status_code >= 400:
                raise ProviderError(
                    f"fal {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
            audio_url = _extract_audio_url(data)
            if not audio_url:
                raise ProviderError(f"fal: no audio url in response: {str(data)[:300]}")
            return audio_url
        except httpx.HTTPError as exc:
            last_error = exc
            provider_logger.warning("fal http error: %s", exc)

    if last_error:
        raise ProviderError(f"fal network error: {last_error}")
    raise ProviderError("fal: all provider keys rate-limited")
