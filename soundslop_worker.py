# soundslop_worker.py — фоновая обработка SoundSlop job'ов
#
# Job-паттерн (context/soundslop_design.md §4): HTTP-запрос только ставит
# задачу в очередь (202), генерация идёт здесь. При любой ошибке —
# fail + автоматический refund потраченных токенов (идемпотентно по
# ref_id "{job_id}:refund").
import asyncio
import logging
import os
import uuid

import httpx

import models
from database import SessionLocal
from s3_utils import presigned_url_async, upload_bytes_to_s3_async
from soundslop_provider import submit_generation
from token_service import apply_transaction

worker_logger = logging.getLogger("sounduk.soundslop")

_AUDIO_EXT_BY_MIME = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
}


def _fail_and_refund(db, job: models.SoundSlopJob, exc: Exception) -> None:
    # str() у httpx/asyncio timeout-исключений пуст — сохраняем тип ошибки,
    # иначе в job.error попадает пустая строка и диагностика слепнет.
    error = str(exc) or type(exc).__name__
    job.status = "failed"
    job.error = f"{type(exc).__name__}: {error}"[:1000]
    db.add(job)
    db.commit()
    user = db.query(models.User).filter(models.User.id == job.user_id).first()
    if user and job.cost > 0:
        apply_transaction(
            db,
            user=user,
            delta=job.cost,
            reason="refund",
            ref_id=f"{job.id}:refund",
        )
    worker_logger.warning("soundslop job=%s failed: %s", job.id, error)


def _download_audio_sync(url: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=300.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        return resp.content, _AUDIO_EXT_BY_MIME.get(content_type, ".mp3")


async def _download_audio(url: str) -> tuple[bytes, str]:
    # ВАЖНО: скачиваем в потоке sync-клиентом. httpx/anyio под uvloop
    # (uvicorn[standard] в проде) зависает на чтении с CDN fal.media —
    # воспроизведено 2026-10-16 (default loop: 2с, uvloop: ReadTimeout).
    return await asyncio.to_thread(_download_audio_sync, url)


async def process_job(job_id: str) -> None:
    """Обработать один job. Своя сессия БД (фоновая задача FastAPI)."""
    db = SessionLocal()
    try:
        job = (
            db.query(models.SoundSlopJob)
            .filter(models.SoundSlopJob.id == job_id)
            .first()
        )
        if job is None or job.status not in ("queued", "running"):
            return
        job.status = "running"
        db.add(job)
        db.commit()

        try:
            source_audio_url = None
            if job.mode in ("audio", "extend"):
                if not job.source_track_id:
                    raise ValueError("source_track_id is required for audio/extend")
                src = (
                    db.query(models.Track)
                    .filter(
                        models.Track.id == job.source_track_id,
                        models.Track.user_id == job.user_id,
                    )
                    .first()
                )
                if src is None:
                    raise ValueError("source track not found or not owned by user")
                source_audio_url = await presigned_url_async(str(src.file_path))
                if not source_audio_url:
                    raise ValueError("cannot get source track url")

            audio_url = await submit_generation(
                mode=job.mode,
                prompt=job.prompt,
                duration_sec=job.duration_sec,
                instrumental=job.instrumental,
                source_audio_url=source_audio_url,
                strength=job.strength,
            )
            audio_bytes, ext = await _download_audio(audio_url)

            s3_key = f"slop/{job.user_id}/{job.id}{ext}"
            await upload_bytes_to_s3_async(
                audio_bytes,
                s3_key,
                content_type=f"audio/{ext.lstrip('.')}",
            )

            track_id = str(uuid.uuid4())
            title = job.prompt.strip().splitlines()[0][:60] or "SoundSlop track"
            track = models.Track(
                id=track_id,
                user_id=job.user_id,
                title=title,
                artist="SoundSlop",
                album=None,
                duration=job.duration_sec,
                file_path=s3_key,
                file_size=len(audio_bytes),
            )
            db.add(track)
            job.status = "succeeded"
            job.result_track_id = track_id
            db.add(job)
            db.commit()
            worker_logger.info(
                "soundslop job=%s succeeded track=%s bytes=%d",
                job.id,
                track_id,
                len(audio_bytes),
            )
        except Exception as exc:  # noqa: BLE001 — любой сбой = fail + refund
            db.rollback()
            job = (
                db.query(models.SoundSlopJob)
                .filter(models.SoundSlopJob.id == job_id)
                .first()
            )
            if job is not None:
                _fail_and_refund(db, job, exc)
    finally:
        db.close()


def slop_storage_enabled() -> bool:
    """Провайдер сконфигурирован (иначе job'ы сразу упадут с refund)."""
    return bool(os.getenv("SOUNDSLOP_PROVIDER_KEYS", "").strip())
