# schemas.py - Схемы для валидации данных
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class UserCreate(BaseModel):
    username: str
    password: str
    # email: Optional[EmailStr] = None

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    # email: Optional[str]
    created_at: datetime
    storage_limit: int
    storage_used: int = 0
    is_premium: bool
    
    class Config:
        from_attributes = True

class AdminUserResponse(UserResponse):
    is_admin: bool
    is_premium: bool
    storage_limit: int
    is_restricted: bool
    storage_used: int = 0

class UserRegisterResponse(UserResponse):
    recovery_code: str

class UserUpdateAdmin(BaseModel):
    username: Optional[str] = None
    # email: Optional[str] = None
    password: Optional[str] = None  # To reset password
    is_premium: Optional[bool] = None
    storage_limit: Optional[int] = None
    is_restricted: Optional[bool] = None
    recovery_code: Optional[str] = None # For admin to see or reset if needed (usually handled separately)

class UserUpdateSelf(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None

class StorageUsageResponse(BaseModel):
    storage_limit: int
    storage_used: int
    percentage: float

class RecoveryRequest(BaseModel):
    username: str
    recovery_code: str
    new_password: str

class PaymentRequest(BaseModel):
    product_id: Optional[str] = "storage_pack_1gb" # default
    days: int = 30 

class PaymentResponse(BaseModel):
    is_premium: bool
    expires_at: Optional[datetime]

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
class PaymentStatusResponse(BaseModel):
    status: str

class PaymentCreateResponse(BaseModel):
    payment_id: str
    confirmation_url: Optional[str] = None
