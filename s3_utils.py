import asyncio
import logging
import os
import time

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

S3_CONNECT_TIMEOUT = max(5, int(os.getenv("S3_CONNECT_TIMEOUT", "10")))
S3_READ_TIMEOUT = max(10, int(os.getenv("S3_READ_TIMEOUT", "30")))
S3_UPLOAD_READ_TIMEOUT = max(60, int(os.getenv("S3_UPLOAD_READ_TIMEOUT", "600")))
S3_MAX_ATTEMPTS = max(2, int(os.getenv("S3_MAX_ATTEMPTS", "4")))
S3_UPLOAD_MAX_ATTEMPTS = max(2, int(os.getenv("S3_UPLOAD_MAX_ATTEMPTS", "5")))
S3_UPLOAD_RETRY_BASE_SEC = max(1, int(os.getenv("S3_UPLOAD_RETRY_BASE_SEC", "2")))

# Virtual-hosted: https://{bucket}.s3.{region}.storage.selcloud.ru/...
# Path-style URLs do not get Selectel CORS headers (OPTIONS 405).
_S3_ADDRESSING = {"addressing_style": "virtual"}

S3_CLIENT_CONFIG = Config(
    connect_timeout=S3_CONNECT_TIMEOUT,
    read_timeout=S3_READ_TIMEOUT,
    retries={"max_attempts": S3_MAX_ATTEMPTS, "mode": "standard"},
    s3=_S3_ADDRESSING,
)

S3_UPLOAD_CLIENT_CONFIG = Config(
    connect_timeout=S3_CONNECT_TIMEOUT,
    read_timeout=S3_UPLOAD_READ_TIMEOUT,
    retries={"max_attempts": S3_MAX_ATTEMPTS, "mode": "adaptive"},
    s3=_S3_ADDRESSING,
)


def _build_s3_client(config: Config):
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT_URL,
        region_name=S3_REGION_NAME,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        config=config,
    )


def get_s3_client():
    logger.debug(
        "s3_client create connect_timeout=%s read_timeout=%s bucket=%s",
        S3_CLIENT_CONFIG.connect_timeout,
        S3_CLIENT_CONFIG.read_timeout,
        S3_BUCKET_NAME,
    )
    return _build_s3_client(S3_CLIENT_CONFIG)


def get_s3_upload_client():
    logger.debug(
        "s3_upload_client create connect_timeout=%s read_timeout=%s bucket=%s",
        S3_UPLOAD_CLIENT_CONFIG.connect_timeout,
        S3_UPLOAD_CLIENT_CONFIG.read_timeout,
        S3_BUCKET_NAME,
    )
    return _build_s3_client(S3_UPLOAD_CLIENT_CONFIG)


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


def upload_bytes_to_s3(
    file_bytes: bytes,
    object_name: str,
    *,
    content_type: str = "application/octet-stream",
) -> None:
    from io import BytesIO

    from boto3.s3.transfer import TransferConfig

    transfer_config = TransferConfig(
        multipart_threshold=8 * 1024 * 1024,
        multipart_chunksize=8 * 1024 * 1024,
        max_concurrency=2,
        use_threads=True,
    )
    last_error: Exception | None = None
    for attempt in range(1, S3_UPLOAD_MAX_ATTEMPTS + 1):
        try:
            s3_client = get_s3_upload_client()
            s3_client.upload_fileobj(
                BytesIO(file_bytes),
                S3_BUCKET_NAME,
                object_name,
                ExtraArgs={"ContentType": content_type},
                Config=transfer_config,
            )
            if attempt > 1:
                logger.info(
                    "s3_upload_ok key=%s bytes=%s attempt=%s",
                    object_name,
                    len(file_bytes),
                    attempt,
                )
            return
        except Exception as exc:
            last_error = exc
            if attempt >= S3_UPLOAD_MAX_ATTEMPTS:
                break
            delay = min(S3_UPLOAD_RETRY_BASE_SEC * (2 ** (attempt - 1)), 30)
            logger.warning(
                "s3_upload_retry key=%s bytes=%s attempt=%s/%s delay=%ss error=%s",
                object_name,
                len(file_bytes),
                attempt,
                S3_UPLOAD_MAX_ATTEMPTS,
                delay,
                exc,
            )
            time.sleep(delay)
    assert last_error is not None
    raise last_error


async def upload_bytes_to_s3_async(
    file_bytes: bytes,
    object_name: str,
    *,
    content_type: str = "application/octet-stream",
) -> None:
    await asyncio.to_thread(
        upload_bytes_to_s3,
        file_bytes,
        object_name,
        content_type=content_type,
    )


def upload_file_to_s3(file_obj, object_name):
    s3_client = get_s3_upload_client()
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
