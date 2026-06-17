from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime


class UserBase(BaseModel):
    username: str
    email: EmailStr
    display_name: Optional[str] = None


class UserCreate(UserBase):
    tenant_id: Optional[int] = None


class UserResponse(BaseModel):
    id: int
    tenant_id: int
    username: str
    email: str
    display_name: Optional[str] = None
    role: Optional[str] = "user"
    created_at: datetime
    is_active: bool
    last_login_at: Optional[datetime] = None
    last_login_ip: Optional[str] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class WebAuthnCredentialResponse(BaseModel):
    id: int
    device_name: Optional[str] = None
    transports: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class VoicePrintResponse(BaseModel):
    id: int
    sample_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfileResponse(UserResponse):
    credentials: List[WebAuthnCredentialResponse] = []
    voiceprints: List[VoicePrintResponse] = []


class RegistrationStartResponse(BaseModel):
    challenge: str
    user_id: str
    rp_id: str
    rp_name: str
    user_name: str
    user_display_name: str
    pub_key_cred_params: list
    timeout: int
    attestation: str
    authenticator_selection: dict
    exclude_credentials: list


class RegistrationFinishRequest(BaseModel):
    credential: dict
    username: str
    device_name: Optional[str] = None


class AuthenticationStartResponse(BaseModel):
    challenge: str
    rp_id: str
    timeout: int
    user_verification: str
    allow_credentials: list


class AuthenticationFinishRequest(BaseModel):
    credential: dict


class VoiceEnrollResponse(BaseModel):
    success: bool
    voiceprint_id: int
    message: str


class VoiceVerifyChallenge(BaseModel):
    challenge_digits: str
    session_id: str


class VoiceVerifyRequest(BaseModel):
    session_id: str
    audio_data: str


class VoiceVerifyResponse(BaseModel):
    success: bool
    user: Optional[UserResponse] = None
    similarity: Optional[float] = None
    message: str
    anomaly_detected: Optional[bool] = False
    anomaly_count: Optional[int] = 0
    fallback_available: Optional[bool] = False
    fallback_method: Optional[str] = None
    service_degraded: Optional[bool] = False


class TenantResponse(BaseModel):
    id: int
    name: str
    domain: str
    language: Optional[str] = None
    accent_region: Optional[str] = None
    status: Optional[str] = None
    voiceprint_threshold: Optional[float] = None
    created_at: Optional[datetime] = None
    settings: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class LoginLogResponse(BaseModel):
    id: int
    tenant_id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    auth_method: str
    status: str
    ip_address: Optional[str] = None
    location: Optional[str] = None
    similarity_score: Optional[float] = None
    anomaly_detected: Optional[bool] = False
    fallback_triggered: Optional[bool] = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnomalyEventResponse(BaseModel):
    id: int
    tenant_id: int
    type: str
    severity: Optional[str] = "medium"
    description: Optional[str] = None
    user_id: Optional[int] = None
    status: Optional[str] = "new"
    details: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceHealthResponse(BaseModel):
    is_available: bool
    circuit_state: str
    fallback_enabled: bool
    fallback_method: str


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[Any]
