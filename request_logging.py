# request_logging.py - HTTP middleware для диагностики запросов
import logging
import time
from typing import Optional

from fastapi import FastAPI, Request
from jose import JWTError, jwt

from auth_utils import SECRET_KEY, ALGORITHM

logger = logging.getLogger("sounduk.http")

SLOW_REQUEST_MS = 3000


def _sanitize_path(path: str) -> str:
    if "/play/" in path:
        idx = path.index("/play/")
        return f"{path[: idx + 6]}***"
    return path


def _extract_user_id(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            return None
        token_type = payload.get("type")
        if token_type == "stream":
            return f"stream:{sub}"
        return str(sub)
    except JWTError:
        return None


def register_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        path = _sanitize_path(request.url.path)
        user_id = _extract_user_id(request)

        try:
            response = await call_next(request)
            duration_ms = int((time.perf_counter() - start) * 1000)
            user_part = f" user={user_id}" if user_id else ""
            msg = (
                f"{request.method} {path} {response.status_code} "
                f"{duration_ms}ms{user_part}"
            )
            if duration_ms >= SLOW_REQUEST_MS:
                logger.warning(f"SLOW {msg}")
            else:
                logger.info(msg)
            return response
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            user_part = f" user={user_id}" if user_id else ""
            logger.exception(
                f"ERROR {request.method} {path} {duration_ms}ms{user_part}"
            )
            raise
