# schemas.py - Схемы для валидации данных
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
    storage_limit: int
    storage_used: int = 0
    is_premium: bool
    is_verified: bool = False

    class Config:
        from_attributes = True

class AdminUserResponse(UserResponse):
    is_admin: bool
    is_premium: bool
    storage_limit: int
    is_restricted: bool
    storage_used: int = 0

class UserRegisterResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
    storage_limit: int
    is_premium: bool
    is_verified: bool = False

    class Config:
        from_attributes = True

class UserUpdateAdmin(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_premium: Optional[bool] = None
    storage_limit: Optional[int] = None
    is_restricted: Optional[bool] = None
    is_verified: Optional[bool] = None
    is_admin: Optional[bool] = None

class UserUpdateSelf(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None

class StorageUsageResponse(BaseModel):
    storage_limit: int
    storage_used: int
    percentage: float

class UserStorageResponse(BaseModel):
    used_space: int
    storage_limit: int
    used_percentage: float

class VerifyEmailRequest(BaseModel):
    email: str
    code: str

class ResendCodeRequest(BaseModel):
    email: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
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

class AdminAuditLogResponse(BaseModel):
    id: int
    admin_id: int
    admin_username: str
    action: str
    target_user_id: Optional[int] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

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
    is_frozen: bool = False
    
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
