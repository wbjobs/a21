from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Dict

from app.database import get_db
from app.models import User, WebAuthnCredential
from app.schemas import (
    UserProfileResponse,
    AuthenticationStartResponse,
    AuthenticationFinishRequest,
    Token,
)
from app.services.webauthn_service import WebAuthnService
from app.core.security import get_current_active_user, create_access_token
from app.core.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

_auth_challenges: Dict[str, Dict] = {}


@router.post("/webauthn/start", response_model=AuthenticationStartResponse)
def start_authentication(
    username: str = None,
    db: Session = Depends(get_db)
):
    credential_ids = []

    if username:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        credential_ids = [c.credential_id for c in user.credentials]

    options, challenge = WebAuthnService.start_authentication(
        credential_ids=credential_ids if credential_ids else None
    )

    _auth_challenges[challenge] = {
        "username": username,
    }

    return options


@router.post("/webauthn/finish", response_model=Token)
def finish_authentication(
    request: AuthenticationFinishRequest,
    db: Session = Depends(get_db)
):
    credential_id_b64 = request.credential.get("id")
    if not credential_id_b64:
        raise HTTPException(status_code=400, detail="Invalid credential")

    credential_record = db.query(WebAuthnCredential).filter(
        WebAuthnCredential.credential_id == credential_id_b64
    ).first()

    if not credential_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credential not registered"
        )

    found_challenge = None
    for challenge in list(_auth_challenges.keys()):
        found_challenge = challenge
        break

    if not found_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending authentication found. Please start authentication first."
        )

    del _auth_challenges[found_challenge]

    result = WebAuthnService.finish_authentication(
        credential_dict=request.credential,
        challenge=found_challenge,
        public_key=credential_record.public_key,
        stored_sign_count=credential_record.sign_count,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WebAuthn authentication failed."
        )

    credential_record.sign_count = result["new_sign_count"]
    db.commit()

    user = credential_record.user

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserProfileResponse)
def get_profile(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    db.refresh(current_user)
    return current_user
