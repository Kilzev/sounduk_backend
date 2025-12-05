# models.py - Модели базы данных
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    """Таблица пользователей"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Новые поля для лимитов
    role = Column(String, default="user") # user, subscriber, admin
    used_space = Column(Integer, default=0) # Использовано байт
    storage_limit = Column(Integer, default=314572800) # Лимит байт (300MB по умолчанию)

    tracks = relationship("Track", back_populates="owner", cascade="all, delete-orphan")

class Track(Base):
    """Таблица треков"""
    __tablename__ = "tracks"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    artist = Column(String, nullable=False)
    album = Column(String, nullable=True)
    duration = Column(Integer, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    owner = relationship("User", back_populates="tracks")