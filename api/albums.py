from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from database import get_db
import models
from auth_utils import get_current_user
from s3_utils import get_s3_client, S3_BUCKET_NAME
import json
from botocore.exceptions import ClientError
from typing import List, Dict, Any, Union

router = APIRouter()

@router.get("", response_model=Union[List[Any], Dict[str, Any]])
async def get_albums(
    current_user: models.User = Depends(get_current_user)
):
    """
    Получает сохраненный JSON с альбомами из S3.
    Если файла нет, возвращает пустой список.
    """
    s3_key = f"albums/{current_user.id}/data.json"
    s3_client = get_s3_client()

    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        content = response['Body'].read().decode('utf-8')
        return json.loads(content)
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == "NoSuchKey":
            # Если файла еще нет, возвращаем пустой список
            return []
        else:
            print(f"S3 Error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка при получении данных альбомов"
            )
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )

@router.post("", status_code=status.HTTP_200_OK)
async def save_albums(
    albums_data: Union[List[Any], Dict[str, Any]] = Body(...),
    current_user: models.User = Depends(get_current_user)
):
    """
    Сохраняет (перезаписывает) JSON с альбомами в S3.
    Принимает любой JSON (список или объект).
    """
    s3_key = f"albums/{current_user.id}/data.json"
    s3_client = get_s3_client()

    try:
        json_content = json.dumps(albums_data, ensure_ascii=False)
        
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=json_content.encode('utf-8'),
            ContentType='application/json'
        )
        
        return {"status": "success", "message": "Albums saved"}
        
    except Exception as e:
        print(f"S3 Upload Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка сохранения данных"
        )
