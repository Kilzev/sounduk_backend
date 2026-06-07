# main.py - Точка входа приложения
import logging
import os

from dotenv import load_dotenv

load_dotenv()

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _configure_app_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, force=True)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    for name in ("sounduk.http", "sounduk.tracks", "sounduk.s3"):
        app_logger = logging.getLogger(name)
        app_logger.setLevel(logging.INFO)
        app_logger.handlers = [handler]
        app_logger.propagate = False


_configure_app_logging()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import auth, tracks, admin, users, payments, albums
from database import engine, Base
from db_backup import upload_db_to_s3, stop_periodic_backup, run_startup_once
from request_logging import register_request_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    _configure_app_logging()
    # SQLite: startup (S3 restore, backup thread) только в одном worker.
    run_startup_once()
    Base.metadata.create_all(bind=engine)
    os.makedirs("uploads", exist_ok=True)

    yield

    # --- Shutdown ---
    stop_periodic_backup()
    upload_db_to_s3()


app = FastAPI(
    title="Sounduk API",
    description="Звуковое облако",
    version="1.0.0",
    lifespan=lifespan,
)

# Разрешаем запросы с Flutter приложения
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_request_logging(app)

# Подключаем роуты
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(tracks.router, prefix="/api/tracks", tags=["Tracks"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"])
app.include_router(albums.router, prefix="/api/albums", tags=["Albums"])

@app.get("/")
async def root():
    """Проверка работы сервера"""
    return {
        "message": "Sounduk API работает! 🎵",
        "docs": "/docs",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", reload=True)