# main.py - Точка входа приложения
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import auth, tracks, admin, users, payments, albums
from database import engine, Base
import os

# Создаём таблицы в БД при запуске
Base.metadata.create_all(bind=engine)

# Создаём папку для хранения файлов
os.makedirs("uploads", exist_ok=True)

app = FastAPI(
    title="Sounduk API",
    description="Звуковое облако",
    version="1.0.0"
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