from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict
import uuid

from app.database import get_db
from app.models import User, WebAuthnCredential
from app.schemas import (
    UserCreate,
    UserResponse,
    RegistrationStartResponse,
    RegistrationFinishRequest,
)
from app.services.webauthn_service import WebAuthnService
from app.core.security import get_current_active_user

router = APIRouter(prefix="/api/webauthn", tags=["webauthn"])

_registration_challenges: Dict[str, Dict] = {}


@router.post("/register/start", response_model=RegistrationStartResponse)
def start_registration(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(
        (User.username == user_data.username) | (User.email == user_data.email)
    ).first()

    user_id = str(uuid.uuid4())
    existing_credential_ids = []

    if existing_user:
        user_id = str(existing_user.id)
        existing_credential_ids = [
            c.credential_id for c in existing_user.credentials
        ]

    options, challenge = WebAuthnService.start_registration(
        user_id=user_id,
        username=user_data.username,
        display_name=user_data.display_name or user_data.username,
        existing_credential_ids=existing_credential_ids,
    )

    _registration_challenges[challenge] = {
        "username": user_data.username,
        "email": user_data.email,
        "display_name": user_data.display_name or user_data.username,
    }

    return options


@router.post("/register/finish", response_model=UserResponse)
def finish_registration(
    request: RegistrationFinishRequest,
    db: Session = Depends(get_db)
):
    found_challenge = None
    for challenge, data in _registration_challenges.items():
        if data["username"] == request.username:
            found_challenge = challenge
            break

    if not found_challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending registration found. Please start registration first."
        )

    user_data = _registration_challenges.pop(found_challenge)

    result = WebAuthnService.finish_registration(
        credential_dict=request.credential,
        challenge=found_challenge,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WebAuthn credential verification failed."
        )

    user = db.query(User).filter(User.username == user_data["username"]).first()
    if not user:
        user = User(
            username=user_data["username"],
            email=user_data["email"],
            display_name=user_data["display_name"],
        )
        db.add(user)
        db.flush()

    existing_cred = db.query(WebAuthnCredential).filter(
        WebAuthnCredential.credential_id == result["credential_id"]
    ).first()
    if existing_cred:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This device is already registered."
        )

    credential = WebAuthnCredential(
        user_id=user.id,
        credential_id=result["credential_id"],
        public_key=result["public_key"],
        sign_count=result["sign_count"],
        device_name=request.device_name or "Unknown Device",
        transports=",".join(result["transports"]) if result["transports"] else None,
    )
    db.add(credential)
    db.commit()
    db.refresh(user)

    return user


@router.get("/credentials")
def list_credentials(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    credentials = db.query(WebAuthnCredential).filter(
        WebAuthnCredential.user_id == current_user.id
    ).all()
    return [
        {
            "id": c.id,
            "device_name": c.device_name,
            "transports": c.transports,
            "created_at": c.created_at,
        }
        for c in credentials
    ]


@router.delete("/credentials/{credential_id}")
def delete_credential(
    credential_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    credential = db.query(WebAuthnCredential).filter(
        WebAuthnCredential.id == credential_id,
        WebAuthnCredential.user_id == current_user.id,
    ).first()
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    total_creds = db.query(WebAuthnCredential).filter(
        WebAuthnCredential.user_id == current_user.id
    ).count()
    total_voiceprints = len(current_user.voiceprints)
    if total_creds <= 1 and total_voiceprints == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last authentication method."
        )

    db.delete(credential)
    db.commit()
    return {"message": "Credential deleted successfully"}
