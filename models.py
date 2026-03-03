# models.py - Модели базы данных
from sqlalchemy import Integer, String, ForeignKey, DateTime, Boolean, BigInteger
from sqlalchemy.orm import relationship, Mapped, mapped_column
from database import Base
from datetime import datetime
from typing import Optional, List

class User(Base):
    """Таблица пользователей"""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    # email: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Новые поля для админки
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    storage_limit: Mapped[int] = mapped_column(BigInteger, default=1073741824) # 1 GB default
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    
    tracks: Mapped[List["Track"]] = relationship("Track", back_populates="owner", cascade="all, delete-orphan")

    @property
    def storage_used(self) -> int:
        return sum(track.file_size for track in self.tracks)

class Track(Base):
    """Таблица треков"""
    __tablename__ = "tracks"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    album: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    owner: Mapped["User"] = relationship("User", back_populates="tracks")