from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Dict, Optional
import uuid
import base64

from app.database import get_db
from app.models import User, VoicePrint
from app.schemas import (
    VoiceEnrollResponse,
    VoiceVerifyChallenge,
    VoiceVerifyRequest,
    VoiceVerifyResponse,
    Token,
)
from app.services.voice_service import VoiceService
from app.core.security import get_current_active_user, create_access_token
from app.core.config import settings
from datetime import timedelta

router = APIRouter(prefix="/api/voice", tags=["voice"])

_verify_sessions: Dict[str, Dict] = {}


@router.post("/enroll", response_model=VoiceEnrollResponse)
async def enroll_voiceprint(
    audio_data: str = Form(...),
    sample_name: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    feature_vector = VoiceService.extract_feature_vector(audio_data)
    if feature_vector is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to extract voice features from audio. Please ensure the audio is clear and at least 1 second long."
        )

    voiceprint = VoicePrint(
        user_id=current_user.id,
        feature_vector=feature_vector.tolist(),
        sample_name=sample_name or f"Sample {len(current_user.voiceprints) + 1}",
    )
    db.add(voiceprint)
    db.commit()
    db.refresh(voiceprint)

    return VoiceEnrollResponse(
        success=True,
        voiceprint_id=voiceprint.id,
        message="Voiceprint enrolled successfully"
    )


@router.get("/challenge", response_model=VoiceVerifyChallenge)
def get_verify_challenge():
    session_id = str(uuid.uuid4())
    challenge_digits = VoiceService.generate_challenge_digits(4)

    _verify_sessions[session_id] = {
        "challenge_digits": challenge_digits,
    }

    return VoiceVerifyChallenge(
        challenge_digits=challenge_digits,
        session_id=session_id,
    )


@router.post("/verify", response_model=VoiceVerifyResponse)
def verify_voiceprint(
    request: VoiceVerifyRequest,
    db: Session = Depends(get_db),
):
    session = _verify_sessions.get(request.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired session. Please request a new challenge."
        )

    del _verify_sessions[request.session_id]

    feature_vector = VoiceService.extract_feature_vector(request.audio_data)
    if feature_vector is None:
        return VoiceVerifyResponse(
            success=False,
            user=None,
            similarity=None,
            message="Failed to extract voice features from audio."
        )

    all_voiceprints = db.query(VoicePrint).all()
    if not all_voiceprints:
        return VoiceVerifyResponse(
            success=False,
            user=None,
            similarity=0.0,
            message="No voiceprints found in the system."
        )

    best_user = None
    best_similarity = 0.0

    user_vectors: Dict[int, list] = {}
    for vp in all_voiceprints:
        if vp.user_id not in user_vectors:
            user_vectors[vp.user_id] = []
        user_vectors[vp.user_id].append(vp.feature_vector)

    for user_id, vectors in user_vectors.items():
        match, similarity = VoiceService.verify_voiceprints(feature_vector, vectors)
        if similarity > best_similarity:
            best_similarity = similarity
            if match:
                best_user = db.query(User).filter(User.id == user_id).first()

    threshold = settings.voiceprint_similarity_threshold
    if best_user and best_similarity >= threshold:
        return VoiceVerifyResponse(
            success=True,
            user=best_user,
            similarity=round(best_similarity, 4),
            message="Voice verification successful"
        )
    else:
        return VoiceVerifyResponse(
            success=False,
            user=None,
            similarity=round(best_similarity, 4) if best_similarity > 0 else None,
            message=f"Voice not recognized. Best similarity: {round(best_similarity, 4)}, threshold: {threshold}"
        )


@router.post("/verify-login", response_model=Token)
def verify_and_login(
    request: VoiceVerifyRequest,
    db: Session = Depends(get_db),
):
    session = _verify_sessions.get(request.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired session. Please request a new challenge."
        )

    del _verify_sessions[request.session_id]

    feature_vector = VoiceService.extract_feature_vector(request.audio_data)
    if feature_vector is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to extract voice features from audio."
        )

    all_voiceprints = db.query(VoicePrint).all()
    if not all_voiceprints:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No voiceprints found in the system."
        )

    best_user = None
    best_similarity = 0.0

    user_vectors: Dict[int, list] = {}
    for vp in all_voiceprints:
        if vp.user_id not in user_vectors:
            user_vectors[vp.user_id] = []
        user_vectors[vp.user_id].append(vp.feature_vector)

    for user_id, vectors in user_vectors.items():
        match, similarity = VoiceService.verify_voiceprints(feature_vector, vectors)
        if similarity > best_similarity:
            best_similarity = similarity
            if match:
                best_user = db.query(User).filter(User.id == user_id).first()

    threshold = settings.voiceprint_similarity_threshold
    if not best_user or best_similarity < threshold:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Voice not recognized. Best similarity: {round(best_similarity, 4)}"
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": best_user.username}, expires_delta=access_token_expires
    )

    return Token(access_token=access_token, token_type="bearer")


@router.get("/voiceprints")
def list_voiceprints(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    voiceprints = db.query(VoicePrint).filter(
        VoicePrint.user_id == current_user.id
    ).all()
    return [
        {
            "id": v.id,
            "sample_name": v.sample_name,
            "created_at": v.created_at,
        }
        for v in voiceprints
    ]


@router.delete("/voiceprints/{voiceprint_id}")
def delete_voiceprint(
    voiceprint_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    voiceprint = db.query(VoicePrint).filter(
        VoicePrint.id == voiceprint_id,
        VoicePrint.user_id == current_user.id,
    ).first()
    if not voiceprint:
        raise HTTPException(status_code=404, detail="Voiceprint not found")

    total_creds = len(current_user.credentials)
    total_voiceprints = db.query(VoicePrint).filter(
        VoicePrint.user_id == current_user.id
    ).count()
    if total_voiceprints <= 1 and total_creds == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last authentication method."
        )

    db.delete(voiceprint)
    db.commit()
    return {"message": "Voiceprint deleted successfully"}
