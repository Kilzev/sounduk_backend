# main.py - Точка входа приложения
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import auth, tracks, albums, users
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

# Разрешаем запросы с Flutter приложения и веб-сайта
origins = [
    "http://localhost",
    "http://localhost:8080", # Локальная разработка
    "http://localhost:3000",
    "https://sounduk.ru",
    "https://www.sounduk.ru",
    "https://api.sounduk.ru",
    "*" # Оставляем звездочку для мобильных приложений, если они используют WebView или специфичные клиенты
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роуты
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(tracks.router, prefix="/api/tracks", tags=["Tracks"])
app.include_router(albums.router, prefix="/api/albums", tags=["Albums"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])

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