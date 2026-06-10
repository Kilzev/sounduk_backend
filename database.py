# database.py - Настройка базы данных
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'database.db')}"

# NullPool: соединение открывается на запрос и сразу закрывается — нет QueuePool deadlock
# при медленных S3-вызовах на одном uvicorn worker.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    """Создаёт сессию БД для каждого запроса"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()