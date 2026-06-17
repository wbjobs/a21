from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import Dict, Optional
import uuid
import base64
import numpy as np

from app.database import get_db
from app.models import User, VoicePrint, LoginStatus, AuthMethod
from app.schemas import (
    VoiceEnrollResponse,
    VoiceVerifyChallenge,
    VoiceVerifyRequest,
    VoiceVerifyResponse,
    Token,
)
from app.services.voice_service import VoiceService, get_voice_service
from app.services.model_manager import get_model_manager
from app.services.audit_service import get_audit_logger
from app.services.anomaly_service import get_anomaly_detector
from app.services.health_service import get_service_health_manager
from app.services.reconciliation_service import get_reconciliation_worker
from app.core.security import get_current_active_user, create_access_token
from app.core.config import settings
from datetime import timedelta

router = APIRouter(prefix="/api/voice", tags=["voice"])

_verify_sessions: Dict[str, Dict] = {}


def _get_tenant_id_from_user(user: Optional[User]) -> Optional[int]:
    if user and hasattr(user, 'tenant_id'):
        return user.tenant_id
    return 1


def _extract_request_info(request: Optional[Request]) -> Dict:
    info = {}
    if request:
        try:
            forwarded = request.headers.get('X-Forwarded-For')
            if forwarded:
                info['ip_address'] = forwarded.split(',')[0].strip()
            elif request.client:
                info['ip_address'] = request.client.host
            info['user_agent'] = request.headers.get('User-Agent', '')[:500]
            info['device_fingerprint'] = request.headers.get('X-Device-Fingerprint', '')
        except Exception:
            pass
    return info


@router.post("/enroll", response_model=VoiceEnrollResponse)
async def enroll_voiceprint(
    request: Request,
    audio_data: str = Form(...),
    sample_name: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    tenant_id = _get_tenant_id_from_user(current_user)

    feature_vector = VoiceService.extract_feature_vector(
        audio_data, tenant_id=tenant_id, user_id=current_user.id
    )
    if feature_vector is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to extract voice features from audio. Please ensure the audio is clear and at least 1 second long."
        )

    voiceprint = VoicePrint(
        user_id=current_user.id,
        tenant_id=tenant_id,
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
        "created_at": __import__("time").time(),
    }

    return VoiceVerifyChallenge(
        challenge_digits=challenge_digits,
        session_id=session_id,
    )


@router.get("/service-status")
def get_service_status():
    health_mgr = get_service_health_manager()
    return {
        "is_available": health_mgr.is_voiceprint_service_healthy(),
        "circuit_state": health_mgr.get_voiceprint_circuit_state(),
        "fallback_enabled": settings.enable_fallback_mode,
        "fallback_method": AuthMethod.WEBAUTHN.value,
    }


@router.post("/verify", response_model=VoiceVerifyResponse)
def verify_voiceprint(
    request: Request,
    verify_request: VoiceVerifyRequest,
    db: Session = Depends(get_db),
):
    session = _verify_sessions.get(verify_request.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired session. Please request a new challenge."
        )

    del _verify_sessions[verify_request.session_id]

    req_info = _extract_request_info(request)
    voice_service = get_voice_service()
    health_mgr = get_service_health_manager()
    audit = get_audit_logger()
    anomaly_detector = get_anomaly_detector()

    raw_feature = voice_service.extract_raw_mfcc(verify_request.audio_data)
    if raw_feature is None:
        return VoiceVerifyResponse(
            success=False,
            user=None,
            similarity=None,
            message="Failed to extract voice features from audio."
        )

    service_down = not health_mgr.is_voiceprint_service_healthy()

    if service_down and settings.enable_fallback_mode:
        return VoiceVerifyResponse(
            success=False,
            user=None,
            similarity=None,
            message="Voiceprint service is currently unavailable. Please use WebAuthn authentication.",
            fallback_available=True,
            fallback_method=AuthMethod.WEBAUTHN.value,
            service_degraded=True,
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
    best_details = None

    user_vectors: Dict[int, list] = {}
    for vp in all_voiceprints:
        if vp.user_id not in user_vectors:
            user_vectors[vp.user_id] = []
        user_vectors[vp.user_id].append(vp.feature_vector)

    for user_id, vectors in user_vectors.items():
        match, similarity, details = voice_service.verify_voiceprints(
            raw_feature, vectors,
            tenant_id=None,
            user_id=user_id,
            use_dtw=True,
            db=db,
        )
        if similarity > best_similarity:
            best_similarity = similarity
            best_details = details
            if match:
                best_user = db.query(User).filter(User.id == user_id).first()

    threshold = settings.voiceprint_similarity_threshold
    success = best_user is not None and best_similarity >= threshold

    anomaly_events = []
    if settings.enable_anomaly_detection:
        try:
            anomaly_events = anomaly_detector.run_all_checks(
                db=db,
                tenant_id=1,
                user_id=best_user.id if best_user else None,
                request_info=req_info,
                auth_method=AuthMethod.VOICEPRINT.value,
                similarity=best_similarity,
                threshold=threshold,
                input_feature=raw_feature,
            )
        except Exception as e:
            print(f"Anomaly detection error: {e}")

    has_anomaly = len(anomaly_events) > 0

    try:
        audit.log_login(
            db=db,
            tenant_id=1,
            user_id=best_user.id if best_user else None,
            username=best_user.username if best_user else None,
            auth_method=AuthMethod.VOICEPRINT.value,
            status=LoginStatus.SUCCESS if success else LoginStatus.FAILED,
            request=request,
            similarity_score=best_similarity,
            anomaly_detected=has_anomaly,
            verification_details=best_details,
        )
        db.commit()
    except Exception as e:
        print(f"Audit logging error: {e}")
        db.rollback()

    if success:
        details_msg = f"Method: {best_details.get('method', 'advanced')}"
        if best_details and best_details.get('best_match'):
            bm = best_details['best_match']
            details_msg += f" | Model: {bm.get('model_similarity', 'N/A')}"
        return VoiceVerifyResponse(
            success=True,
            user=best_user,
            similarity=round(best_similarity, 4),
            message=f"Voice verification successful. {details_msg}",
            anomaly_detected=has_anomaly,
            anomaly_count=len(anomaly_events),
        )
    else:
        details_msg = f"Best similarity: {round(best_similarity, 4)}, threshold: {threshold}"
        if best_details and best_details.get('best_match'):
            bm = best_details['best_match']
            details_msg += f" | Model: {bm.get('model_similarity', 'N/A')}, DTW: {bm.get('dtw_similarity', 'N/A')}"
        return VoiceVerifyResponse(
            success=False,
            user=None,
            similarity=round(best_similarity, 4) if best_similarity > 0 else None,
            message=f"Voice not recognized. {details_msg}",
        )


@router.post("/verify-login")
def verify_and_login(
    request: Request,
    verify_request: VoiceVerifyRequest,
    db: Session = Depends(get_db),
):
    session = _verify_sessions.get(verify_request.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired session. Please request a new challenge."
        )

    del _verify_sessions[verify_request.session_id]

    req_info = _extract_request_info(request)
    voice_service = get_voice_service()
    health_mgr = get_service_health_manager()
    audit = get_audit_logger()
    anomaly_detector = get_anomaly_detector()

    raw_feature = voice_service.extract_raw_mfcc(verify_request.audio_data)
    if raw_feature is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to extract voice features from audio."
        )

    service_down = not health_mgr.is_voiceprint_service_healthy()

    if service_down and settings.enable_fallback_mode:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Voiceprint service is currently unavailable.",
                "fallback_available": True,
                "fallback_method": AuthMethod.WEBAUTHN.value,
                "service_degraded": True,
            }
        )

    all_voiceprints = db.query(VoicePrint).all()
    if not all_voiceprints:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No voiceprints found in the system."
        )

    best_user = None
    best_similarity = 0.0
    best_details = None

    user_vectors: Dict[int, list] = {}
    for vp in all_voiceprints:
        if vp.user_id not in user_vectors:
            user_vectors[vp.user_id] = []
        user_vectors[vp.user_id].append(vp.feature_vector)

    for user_id, vectors in user_vectors.items():
        match, similarity, details = voice_service.verify_voiceprints(
            raw_feature, vectors,
            tenant_id=None,
            user_id=user_id,
            use_dtw=True,
            db=db,
        )
        if similarity > best_similarity:
            best_similarity = similarity
            best_details = details
            if match:
                best_user = db.query(User).filter(User.id == user_id).first()

    threshold = settings.voiceprint_similarity_threshold
    success = best_user is not None and best_similarity >= threshold

    anomaly_events = []
    if settings.enable_anomaly_detection and success:
        try:
            anomaly_events = anomaly_detector.run_all_checks(
                db=db,
                tenant_id=1,
                user_id=best_user.id if best_user else None,
                request_info=req_info,
                auth_method=AuthMethod.VOICEPRINT.value,
                similarity=best_similarity,
                threshold=threshold,
                input_feature=raw_feature,
            )
        except Exception as e:
            print(f"Anomaly detection error: {e}")

    has_anomaly = len(anomaly_events) > 0

    try:
        login_log = audit.log_login(
            db=db,
            tenant_id=1,
            user_id=best_user.id if best_user else None,
            username=best_user.username if best_user else None,
            auth_method=AuthMethod.VOICEPRINT.value,
            status=LoginStatus.SUCCESS if success else LoginStatus.FAILED,
            request=request,
            similarity_score=best_similarity,
            anomaly_detected=has_anomaly,
            verification_details=best_details,
        )
        db.commit()
    except Exception as e:
        print(f"Audit logging error: {e}")
        db.rollback()

    if not success:
        details_msg = f"Best similarity: {round(best_similarity, 4)}, threshold: {threshold}"
        if best_details and best_details.get('best_match'):
            bm = best_details['best_match']
            details_msg += f" | Model: {bm.get('model_similarity', 'N/A')}, DTW: {bm.get('dtw_similarity', 'N/A')}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Voice not recognized. {details_msg}"
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": best_user.username}, expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "anomaly_detected": has_anomaly,
        "anomaly_count": len(anomaly_events),
        "similarity_score": round(best_similarity, 4),
    }


@router.post("/fallback-login")
def fallback_login(
    request: Request,
    db: Session = Depends(get_db),
):
    health_mgr = get_service_health_manager()
    if health_mgr.is_voiceprint_service_healthy():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voiceprint service is healthy. Fallback mode not required."
        )

    if not settings.enable_fallback_mode:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voiceprint service unavailable and fallback mode is disabled."
        )

    return {
        "message": "Fallback mode is active. Please use WebAuthn authentication instead.",
        "fallback_method": AuthMethod.WEBAUTHN.value,
        "service_degraded": True,
    }


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


@router.get("/model/info")
def get_model_info(
    current_user: User = Depends(get_current_active_user),
):
    model_manager = get_model_manager()
    tenant_id = _get_tenant_id_from_user(current_user)
    return model_manager.get_tenant_model_info(tenant_id)


@router.post("/model/reload")
def reload_model(
    current_user: User = Depends(get_current_active_user),
):
    model_manager = get_model_manager()
    tenant_id = _get_tenant_id_from_user(current_user)
    model_manager.reload_tenant_model(tenant_id)
    return {
        "message": "Model reloaded successfully",
        "info": model_manager.get_tenant_model_info(tenant_id),
    }


@router.post("/model/train")
def train_model(
    background_tasks: BackgroundTasks,
    n_epochs: int = 50,
    current_user: User = Depends(get_current_active_user),
):
    if not hasattr(current_user, 'role') or current_user.role not in ("tenant_admin", "system_admin", "admin"):
        if current_user.username != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can trigger model training"
            )

    def run_training():
        import subprocess
        import sys
        subprocess.run([
            sys.executable, "scripts/train_siamese.py",
            "--epochs", str(n_epochs),
            "--output", "backend/models/voiceprint_siamese.pt"
        ], cwd="backend")

    background_tasks.add_task(run_training)
    return {"message": "Model training started in background"}


@router.get("/model/threshold")
def get_threshold(
    current_user: Optional[User] = Depends(get_current_active_user),
):
    tenant_id = _get_tenant_id_from_user(current_user) if current_user else 1
    mm = get_model_manager()
    from app.database import get_db as _get_db
    db = next(_get_db())
    threshold = mm.get_threshold(tenant_id, db)
    db.close()

    return {
        "threshold": threshold,
        "tenant_id": tenant_id,
        "description": "Similarity threshold for voice verification (0-1)",
        "recommended_range": "0.65-0.85 for Siamese model",
    }
