from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    username: str
    email: EmailStr
    display_name: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    display_name: Optional[str] = None
    created_at: datetime
    is_active: bool

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
