import io
import base64
import random
import string
import numpy as np
import librosa
from scipy.signal import wiener
from typing import Optional, Tuple, Dict, Any, List
from sqlalchemy.orm import Session
from app.core.config import settings
from app.services.model_manager import get_model_manager
from app.services.health_service import get_service_health_manager


class VoiceService:
    @staticmethod
    def generate_challenge_digits(length: int = 4) -> str:
        return ''.join(random.choices(string.digits, k=length))

    @staticmethod
    def is_service_available() -> bool:
        health_mgr = get_service_health_manager()
        return health_mgr.is_voiceprint_service_healthy()

    @staticmethod
    def _load_audio_from_base64(base64_audio: str) -> Tuple[np.ndarray, int]:
        audio_data = base64.b64decode(base64_audio)
        audio_buffer = io.BytesIO(audio_data)
        y, sr = librosa.load(audio_buffer, sr=16000, mono=True)
        return y, sr

    @staticmethod
    def _load_audio_from_bytes(audio_bytes: bytes) -> Tuple[np.ndarray, int]:
        audio_buffer = io.BytesIO(audio_bytes)
        y, sr = librosa.load(audio_buffer, sr=16000, mono=True)
        return y, sr

    @staticmethod
    def _advanced_preprocessing(y: np.ndarray, sr: int) -> np.ndarray:
        if len(y) < sr * 0.5:
            pad_len = int(sr * 0.5) - len(y)
            y = np.pad(y, (0, pad_len), mode='constant')

        max_len = int(sr * 5)
        if len(y) > max_len:
            y = y[:max_len]

        try:
            y = wiener(y, mysize=5)
        except Exception:
            pass

        y = librosa.effects.preemphasis(y, coef=0.97)

        y_trimmed, _ = librosa.effects.trim(y, top_db=25)
        if len(y_trimmed) > sr * 0.3:
            y = y_trimmed

        y = librosa.util.normalize(y)

        rms = np.sqrt(np.mean(y ** 2))
        target_rms = 0.15
        if rms > 0.01:
            gain = target_rms / (rms + 1e-10)
            gain = np.clip(gain, 0.5, 3.0)
            y = y * gain

        y = librosa.util.normalize(y)

        return y

    @staticmethod
    def _extract_enhanced_mfcc(y: np.ndarray, sr: int) -> np.ndarray:
        n_mfcc = settings.mfcc_n_mfcc

        mfccs = librosa.feature.mfcc(
            y=y,
            sr=sr,
            n_mfcc=n_mfcc,
            n_fft=512,
            hop_length=256,
            fmin=20,
            fmax=8000,
        )

        delta_mfccs = librosa.feature.delta(mfccs)
        delta2_mfccs = librosa.feature.delta(mfccs, order=2)

        mfcc_mean = np.mean(mfccs, axis=1)
        mfcc_std = np.std(mfccs, axis=1)
        delta_mean = np.mean(delta_mfccs, axis=1)
        delta_std = np.std(delta_mfccs, axis=1)
        delta2_mean = np.mean(delta2_mfccs, axis=1)
        delta2_std = np.std(delta2_mfccs, axis=1)

        combined = np.concatenate([
            mfcc_mean,
            mfcc_std,
            delta_mean,
            delta_std,
            delta2_mean,
            delta2_std,
        ])

        if combined.shape[0] < 200:
            pad_len = 200 - combined.shape[0]
            combined = np.pad(combined, (0, pad_len), mode='constant')
        else:
            combined = combined[:200]

        return combined.astype(np.float32)

    @classmethod
    def extract_raw_mfcc(cls, base64_audio: str) -> Optional[np.ndarray]:
        try:
            y, sr = cls._load_audio_from_base64(base64_audio)
            y = cls._advanced_preprocessing(y, sr)
            return cls._extract_enhanced_mfcc(y, sr)
        except Exception as e:
            print(f"Error extracting raw MFCC: {e}")
            return None

    @classmethod
    def extract_mfcc_from_file(cls, file_path: str) -> Optional[np.ndarray]:
        try:
            y, sr = librosa.load(file_path, sr=16000, mono=True)
            y = cls._advanced_preprocessing(y, sr)
            return cls._extract_enhanced_mfcc(y, sr)
        except Exception as e:
            print(f"Error extracting MFCC from file: {e}")
            return None

    @classmethod
    def extract_feature_vector(
        cls,
        base64_audio: str,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        try:
            raw_feature = cls.extract_raw_mfcc(base64_audio)
            if raw_feature is None:
                return None

            mm = get_model_manager()
            normalizer = mm.get_normalizer(tenant_id)
            return normalizer.normalize(raw_feature, user_id=user_id)
        except Exception as e:
            print(f"Error extracting voice features: {e}")
            return None

    @classmethod
    def verify_voiceprints(
        cls,
        input_feature: np.ndarray,
        stored_vectors: List[np.ndarray],
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        use_dtw: bool = True,
        db: Optional[Session] = None,
    ) -> Tuple[bool, float, Dict[str, Any]]:
        health_mgr = get_service_health_manager()

        if not stored_vectors:
            health_mgr.record_voiceprint_failure()
            return False, 0.0, {"error": "No stored voiceprints", "service_degraded": False}

        if not health_mgr.is_voiceprint_service_healthy():
            return False, 0.0, {
                "error": "voiceprint_service_unavailable",
                "fallback_required": True,
                "fallback_method": "webauthn",
                "service_degraded": True,
            }

        try:
            mm = get_model_manager()
            success, similarity, details = mm.verify_voiceprints(
                input_feature=input_feature,
                stored_vectors=stored_vectors,
                tenant_id=tenant_id,
                user_id=user_id,
                use_dtw_alignment=use_dtw,
                db=db,
            )
            health_mgr.record_voiceprint_success()
            return success, similarity, details
        except Exception as e:
            print(f"Voiceprint verification error: {e}")
            health_mgr.record_voiceprint_failure()
            return False, 0.0, {
                "error": str(e),
                "fallback_required": health_mgr.should_use_fallback(),
                "fallback_method": "webauthn",
                "service_degraded": True,
            }

    @classmethod
    def extract_feature_sequence(
        cls,
        base64_audio: str,
        tenant_id: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        try:
            y, sr = cls._load_audio_from_base64(base64_audio)
            y = cls._advanced_preprocessing(y, sr)

            n_mfcc = settings.mfcc_n_mfcc
            mfccs = librosa.feature.mfcc(
                y=y, sr=sr, n_mfcc=n_mfcc, hop_length=256
            )
            delta = librosa.feature.delta(mfccs)
            delta2 = librosa.feature.delta(mfccs, order=2)

            features = np.vstack([mfccs, delta, delta2]).T.astype(np.float32)

            mm = get_model_manager()
            normalizer = mm.get_normalizer(tenant_id)
            return normalizer.normalize_sequence(features)
        except Exception as e:
            print(f"Error extracting feature sequence: {e}")
            return None

    @classmethod
    def get_embedding(
        cls,
        feature_vector: np.ndarray,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> np.ndarray:
        mm = get_model_manager()
        normalizer = mm.get_normalizer(tenant_id)
        model = mm.get_model(tenant_id)
        normalized = normalizer.normalize(feature_vector, user_id=user_id)
        return model.get_embedding(normalized)


_voice_service_instance: Optional[VoiceService] = None


def get_voice_service() -> VoiceService:
    global _voice_service_instance
    if _voice_service_instance is None:
        _voice_service_instance = VoiceService()
    return _voice_service_instance
