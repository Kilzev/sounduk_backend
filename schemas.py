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


class AdminUserTracksCleanupRequest(BaseModel):
    confirm: str
    dry_run: bool = False


class AdminUserTracksCleanupResponse(BaseModel):
    user_id: int
    tracks_in_db: int
    local_files_deleted: int
    local_files_missing: int
    s3_objects_deleted: int
    db_tracks_deleted: int
    dry_run: bool
    errors: list[str] = []

class TrackUpload(BaseModel):
    title: str
    artist: str
    album: Optional[str] = None
    duration: int


class TrackUpdateRequest(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    cover_url: Optional[str] = None
    clear_cover: bool = False

class TrackResponse(BaseModel):
    id: str
    title: str
    artist: str
    album: Optional[str]
    duration: int
    file_size: int
    created_at: datetime
    is_frozen: bool = False
    has_cover: bool = False

    class Config:
        from_attributes = True

class TracksList(BaseModel):
    tracks: list[TrackResponse]
    total: int
    unchanged: bool = False
    revision: Optional[int] = None
    next_cursor: Optional[str] = None
    has_more: bool = False


class StreamTokenResponse(BaseModel):
    token: str
    url: str
    presigned_url: Optional[str] = None
    expires_in: Optional[int] = None


class LibraryRevisionResponse(BaseModel):
    revision: int
class PaymentStatusResponse(BaseModel):
    status: str

class PaymentCreateResponse(BaseModel):
    payment_id: str
    confirmation_url: Optional[str] = None


class ImportedTrack(BaseModel):
    id: str
    title: str
    artist: str
    album: Optional[str] = None
    file_size: int
    s3_key: str


class TrackImportResponse(BaseModel):
    imported: list[ImportedTrack]
    total: int


class YouTubeImportRequest(BaseModel):
    youtube_url: str
    album_id: Optional[str] = None


class YouTubeImportJobCreateRequest(BaseModel):
    youtube_url: str
    album_id: Optional[str] = None
    client_request_id: Optional[str] = None


class DirectTrackImportItem(BaseModel):
    file_url: str
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: Optional[int] = None


class DirectTrackImportRequest(BaseModel):
    file_url: str
    album_id: Optional[str] = None


class DirectBatchImportRequest(BaseModel):
    tracks: list[DirectTrackImportItem]
    album_id: Optional[str] = None


class DirectImportJobCreateRequest(BaseModel):
    tracks: list[DirectTrackImportItem]
    album_id: Optional[str] = None
    client_request_id: Optional[str] = None


class ImportJobResponse(BaseModel):
    id: str
    status: str
    album_id: Optional[str] = None
    total_items: int
    processed_items: int
    running_items: int = 0
    success_items: int
    failed_items: int
    skipped_items: int
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ImportJobItemResponse(BaseModel):
    id: int
    position: int
    file_url: str
    status: str
    retry_count: int
    error_message: Optional[str] = None
    imported_track_id: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: Optional[int] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class ImportJobItemsListResponse(BaseModel):
    items: list[ImportJobItemResponse]
    total: int


class ImportJobCreateResponse(BaseModel):
    job_id: str
    status: str


class ImportJobRetryResponse(BaseModel):
    job_id: str
    status: str
    queued_items: int


# --- User Settings (Equalizer) ---

class EqualizerSettingsLoadResponse(BaseModel):
    enabled: bool = False
    gains: list[float] = []


class EqualizerSettingsSaveRequest(BaseModel):
    enabled: bool
    gains: list[float]
