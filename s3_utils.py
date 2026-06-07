import asyncio
import logging
import os

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sounduk.s3")

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_REGION_NAME = os.getenv("S3_REGION_NAME")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")

STREAM_PRESIGNED_TTL = max(300, int(os.getenv("STREAM_PRESIGNED_TTL", "1800")))
STREAM_PRESIGNED_ENABLED = (
    os.getenv("STREAM_PRESIGNED_ENABLED", "false").strip().lower()
    in {"1", "true", "yes"}
)

S3_CLIENT_CONFIG = Config(
    connect_timeout=5,
    read_timeout=20,
    retries={"max_attempts": 2, "mode": "standard"},
)


def get_s3_client():
    logger.debug(
        "s3_client create connect_timeout=%s read_timeout=%s bucket=%s",
        S3_CLIENT_CONFIG.connect_timeout,
        S3_CLIENT_CONFIG.read_timeout,
        S3_BUCKET_NAME,
    )
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT_URL,
        region_name=S3_REGION_NAME,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        config=S3_CLIENT_CONFIG,
    )


def generate_presigned_url(object_name, expiration=3600):
    s3_client = get_s3_client()
    try:
        response = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': object_name},
            ExpiresIn=expiration,
        )
    except Exception as e:
        logger.error("presigned_url fail key=%s error=%s", object_name, e)
        return None
    return response


async def presigned_url_async(object_name: str, expiration: int = 3600) -> str | None:
    return await asyncio.to_thread(generate_presigned_url, object_name, expiration)


async def head_object_async(object_key: str) -> dict:
    def _head():
        return get_s3_client().head_object(Bucket=S3_BUCKET_NAME, Key=object_key)

    return await asyncio.to_thread(_head)


async def get_object_async(object_key: str, range_value: str | None = None) -> dict:
    def _get():
        kwargs: dict = {"Bucket": S3_BUCKET_NAME, "Key": object_key}
        if range_value:
            kwargs["Range"] = range_value
        return get_s3_client().get_object(**kwargs)

    return await asyncio.to_thread(_get)


def upload_file_to_s3(file_obj, object_name):
    s3_client = get_s3_client()
    try:
        s3_client.upload_fileobj(file_obj, S3_BUCKET_NAME, object_name)
    except Exception as e:
        logger.error("upload fail key=%s error=%s", object_name, e)
        return False
    return True


def delete_file_from_s3(object_name):
    s3_client = get_s3_client()
    try:
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=object_name)
    except Exception as e:
        logger.error("delete fail key=%s error=%s", object_name, e)
        return False
    return True
