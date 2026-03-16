# models.py - Модели базы данных
from sqlalchemy import Integer, String, ForeignKey, DateTime, Boolean, BigInteger, Text, LargeBinary, JSON
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
    plain_password: Mapped[Optional[str]] = mapped_column(String, nullable=True) # Для удобства просмотра админом (небезопасно для продакшена!)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Новые поля для админки
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    premium_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    storage_limit: Mapped[int] = mapped_column(BigInteger, default=1073741824) # 1 GB default
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Резервный доступ (храним зашифрованным, но обратимым, чтобы показывать пользователю)
    recovery_code_enc: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    tracks: Mapped[List["Track"]] = relationship("Track", back_populates="owner", cascade="all, delete-orphan")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    albums: Mapped[List["Album"]] = relationship("Album", back_populates="owner", cascade="all, delete-orphan")

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
    cover_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    owner: Mapped["User"] = relationship("User", back_populates="tracks")
class Payment(Base):
    """Таблица платежей"""
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True) # YooKassa payment_id
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="RUB")
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="payments")

class Album(Base):
    """Таблица альбомов"""
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_art: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    track_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    owner: Mapped["User"] = relationship("User", back_populates="albums")

class IpBlock(Base):
    """Таблица для отслеживания неудачных входов (защита от брутфорса)"""
    __tablename__ = "ip_blocks"

    ip_address: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

