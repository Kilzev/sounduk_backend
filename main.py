# main.py - Точка входа приложения
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import auth, tracks, admin, users, payments, albums
from database import engine, Base
from db_backup import download_db_from_s3, upload_db_to_s3, start_periodic_backup, stop_periodic_backup
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    # Пытаемся восстановить БД с S3 если локальной нет
    download_db_from_s3()
    # Создаём таблицы (если БД новая)
    Base.metadata.create_all(bind=engine)
    os.makedirs("uploads", exist_ok=True)
    # Запускаем периодический бэкап
    start_periodic_backup()

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