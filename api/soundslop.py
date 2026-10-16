# api/soundslop.py — генерация музыки за токены (job-паттерн, см.
# context/unified_api_spec.md «SoundSlop» и context/soundslop_design.md)
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
import token_service
from auth_utils import get_current_user
from database import get_db
from s3_utils import presigned_url_async
from soundslop_worker import process_job

router = APIRouter()

_ALLOWED_MODES = ("text", "audio", "extend")


async def _job_response(job: models.SoundSlopJob, db: Session) -> schemas.SoundSlopJobResponse:
    stream_url = None
    if job.status == "succeeded" and job.result_track_id:
        track = (
            db.query(models.Track)
            .filter(models.Track.id == job.result_track_id)
            .first()
        )
        if track is not None:
            stream_url = await presigned_url_async(str(track.file_path))
    return schemas.SoundSlopJobResponse(
        job_id=job.id,
        mode=job.mode,
        prompt=job.prompt,
        duration_sec=job.duration_sec,
        instrumental=job.instrumental,
        source_track_id=job.source_track_id,
        strength=job.strength,
        status=job.status,
        track_id=job.result_track_id,
        stream_url=stream_url,
        error=job.error,
        created_at=job.created_at,
    )


@router.post(
    "/generate",
    response_model=schemas.SoundSlopGenerateResponse,
    status_code=202,
)
async def generate(
    body: schemas.SoundSlopGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    if len(prompt) > 500:
        raise HTTPException(status_code=400, detail="prompt too long (max 500)")

    max_duration = token_service.max_duration_sec()
    duration = body.duration_sec or 120
    if duration < 10 or duration > max_duration:
        raise HTTPException(
            status_code=400,
            detail=f"duration_sec must be 10..{max_duration}",
        )

    if body.mode not in _ALLOWED_MODES:
        raise HTTPException(status_code=400, detail="unknown mode")
    if body.mode in ("audio", "extend"):
        if not body.source_track_id:
            raise HTTPException(
                status_code=400, detail="source_track_id required for audio/extend"
            )
        src = (
            db.query(models.Track)
            .filter(
                models.Track.id == body.source_track_id,
                models.Track.user_id == current_user.id,
            )
            .first()
        )
        if src is None:
            raise HTTPException(status_code=404, detail="source track not found")
        if body.strength is not None and not (0.0 <= body.strength <= 1.0):
            raise HTTPException(status_code=400, detail="strength must be 0..1")

    cost = token_service.cost_per_generation()
    job = models.SoundSlopJob(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        mode=body.mode,
        prompt=prompt,
        duration_sec=duration,
        instrumental=body.instrumental,
        source_track_id=body.source_track_id,
        strength=body.strength,
        status="queued",
        cost=cost,
    )

    # Job создаётся до списания: при нехватке токенов — удаляем (компенсация).
    # ref_id = job.id → fail воркера вернёт токены (reason=refund).
    db.add(job)
    db.commit()

    try:
        token_service.spend_tokens(
            db,
            user=current_user,
            amount=cost,
            reason="generation",
            ref_id=job.id,
        )
    except token_service.InsufficientTokens as exc:
        db.delete(job)
        db.commit()
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_tokens",
                "balance": exc.balance,
                "required": exc.required,
            },
        )
    db.refresh(current_user)

    background_tasks.add_task(process_job, job.id)
    return schemas.SoundSlopGenerateResponse(
        job_id=job.id, status="queued", balance=current_user.tokens_balance or 0
    )


@router.get("/jobs", response_model=list[schemas.SoundSlopJobResponse])
async def list_jobs(
    limit: int = 20,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(models.SoundSlopJob)
        .filter(models.SoundSlopJob.user_id == current_user.id)
        .order_by(models.SoundSlopJob.created_at.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )
    return [await _job_response(job, db) for job in jobs]


@router.get("/jobs/{job_id}", response_model=schemas.SoundSlopJobResponse)
async def get_job(
    job_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = (
        db.query(models.SoundSlopJob)
        .filter(
            models.SoundSlopJob.id == job_id,
            models.SoundSlopJob.user_id == current_user.id,
        )
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return await _job_response(job, db)
