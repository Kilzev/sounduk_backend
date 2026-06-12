import json

from fastapi import APIRouter, Depends, HTTPException, status

import models
import schemas
from auth_utils import get_current_user
from s3_utils import (
    S3_BUCKET_NAME,
    get_object_async,
    upload_bytes_to_s3_async,
)

router = APIRouter()

_EQ_SETTINGS_S3_PATH = "eq_settings/{user_id}/equalizer.json"


def _eq_key(user_id: int) -> str:
    return _EQ_SETTINGS_S3_PATH.format(user_id=user_id)


@router.get(
    "/equalizer",
    response_model=schemas.EqualizerSettingsLoadResponse,
    summary="Load saved equalizer settings",
)
async def load_equalizer_settings(
    current_user: models.User = Depends(get_current_user),
):
    key = _eq_key(current_user.id)
    try:
        response = await get_object_async(key)
        body = await response["Body"].read()
        data = json.loads(body)
        return schemas.EqualizerSettingsLoadResponse(
            enabled=data.get("enabled", False),
            gains=data.get("gains", []),
        )
    except Exception:
        return schemas.EqualizerSettingsLoadResponse(enabled=False, gains=[])


@router.put(
    "/equalizer",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Save equalizer settings",
)
async def save_equalizer_settings(
    body: schemas.EqualizerSettingsSaveRequest,
    current_user: models.User = Depends(get_current_user),
):
    key = _eq_key(current_user.id)
    data = json.dumps({
        "enabled": body.enabled,
        "gains": body.gains,
    }).encode("utf-8")
    try:
        await upload_bytes_to_s3_async(data, key, content_type="application/json")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save equalizer settings",
        )
