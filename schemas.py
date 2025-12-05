# schemas.py - Схемы для валидации данных
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[EmailStr] = None

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    created_at: datetime
    role: str
    used_space: int
    storage_limit: int
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TrackUpload(BaseModel):
    title: str
    artist: str
    album: Optional[str] = None
    duration: int

class TrackResponse(BaseModel):
    id: str
    title: str
    artist: str
    album: Optional[str]
    duration: int
    file_size: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class TracksList(BaseModel):
    tracks: list[TrackResponse]
    total: int