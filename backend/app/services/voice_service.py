import io
import base64
import random
import string
import numpy as np
import librosa
from scipy.signal import wiener
from typing import Optional, Tuple, Dict, Any
from app.core.config import settings
from app.services.model_manager import get_model_manager


class VoiceService:
    @staticmethod
    def generate_challenge_digits(length: int = 4) -> str:
        return ''.join(random.choices(string.digits, k=length))

    @staticmethod
    def _load_audio_from_base64(base64_audio: str) -> Tuple[np.ndarray, int]:
        audio_data = base64.b64decode(base64_audio)
        audio_buffer = io.BytesIO(audio_data)
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
        mfcc_median = np.median(mfccs, axis=1)
        mfcc_max = np.max(mfccs, axis=1)
        mfcc_min = np.min(mfccs, axis=1)

        delta_mean = np.mean(delta_mfccs, axis=1)
        delta_std = np.std(delta_mfccs, axis=1)

        delta2_mean = np.mean(delta2_mfccs, axis=1)
        delta2_std = np.std(delta2_mfccs, axis=1)

        zcr = librosa.feature.zero_crossing_rate(y=y)
        zcr_mean = np.mean(zcr)
        zcr_std = np.std(zcr)

        rms = librosa.feature.rms(y=y)
        rms_mean = np.mean(rms)
        rms_std = np.std(rms)

        spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
        spec_cent_mean = np.mean(spectral_centroid)
        spec_cent_std = np.std(spectral_centroid)

        spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)
        spec_bw_mean = np.mean(spectral_bandwidth)
        spec_bw_std = np.std(spectral_bandwidth)

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

        return combined

    @classmethod
    def extract_feature_vector(
        cls,
        base64_audio: str,
        user_id: Optional[int] = None
    ) -> Optional[np.ndarray]:
        try:
            y, sr = cls._load_audio_from_base64(base64_audio)
            y = cls._advanced_preprocessing(y, sr)
            raw_feature = cls._extract_enhanced_mfcc(y, sr)

            model_manager = get_model_manager()
            normalized_feature = model_manager.normalizer.normalize(
                raw_feature,
                user_id=user_id
            )

            return normalized_feature
        except Exception as e:
            print(f"Error extracting voice features: {e}")
            return None

    @classmethod
    def extract_feature_sequence(
        cls,
        base64_audio: str
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

            features = np.vstack([mfccs, delta, delta2]).T

            model_manager = get_model_manager()
            normalized_sequence = model_manager.normalizer.normalize_sequence(
                features
            )

            return normalized_sequence
        except Exception as e:
            print(f"Error extracting feature sequence: {e}")
            return None

    @classmethod
    def align_and_compare(
        cls,
        input_feature: np.ndarray,
        stored_vector: np.ndarray,
        user_id: Optional[int] = None
    ) -> Tuple[float, Dict[str, Any]]:
        from app.services.dtw_aligner import DynamicTimeWarping

        model_manager = get_model_manager()

        input_norm = model_manager.normalizer.normalize(
            input_feature, user_id=user_id
        )
        stored_norm = model_manager.normalizer.normalize(
            stored_vector, user_id=user_id
        )

        model_similarity = model_manager.model.compute_similarity(
            input_norm, stored_norm
        )

        dtw = DynamicTimeWarping(window_size=50, distance_metric='cosine')
        _, _, dtw_cost, _ = dtw.align(
            input_norm.reshape(-1, 1),
            stored_norm.reshape(-1, 1)
        )
        dtw_similarity = 1.0 / (1.0 + dtw_cost * 5)

        cosine_sim = float(
            np.dot(input_norm / (np.linalg.norm(input_norm) + 1e-10),
                   stored_norm / (np.linalg.norm(stored_norm) + 1e-10))
        )

        weights = getattr(settings, 'similarity_weights', {
            'model': 0.5,
            'dtw': 0.3,
            'cosine': 0.2
        })
        combined_similarity = (
            weights.get('model', 0.5) * model_similarity +
            weights.get('dtw', 0.3) * dtw_similarity +
            weights.get('cosine', 0.2) * cosine_sim
        )

        details = {
            'model_similarity': round(model_similarity, 4),
            'dtw_similarity': round(dtw_similarity, 4),
            'dtw_cost': round(dtw_cost, 4),
            'cosine_similarity': round(cosine_sim, 4),
            'combined_similarity': round(combined_similarity, 4),
        }

        return combined_similarity, details

    @classmethod
    def verify_voiceprints(
        cls,
        input_feature: np.ndarray,
        stored_vectors: list,
        user_id: Optional[int] = None,
        use_dtw: bool = True
    ) -> Tuple[bool, float, Dict[str, Any]]:
        if not stored_vectors:
            return False, 0.0, {"error": "No stored voiceprints"}

        threshold = settings.voiceprint_similarity_threshold
        max_similarity = 0.0
        all_details = []
        best_details = {}

        for idx, stored_vec in enumerate(stored_vectors):
            stored_arr = np.array(stored_vec)

            if use_dtw:
                similarity, details = cls.align_and_compare(
                    input_feature, stored_arr, user_id
                )
                details['voiceprint_index'] = idx
                all_details.append(details)
            else:
                model_manager = get_model_manager()
                input_norm = model_manager.normalizer.normalize(
                    input_feature, user_id=user_id
                )
                stored_norm = model_manager.normalizer.normalize(
                    stored_arr, user_id=user_id
                )
                similarity = model_manager.model.compute_similarity(
                    input_norm, stored_norm
                )
                details = {
                    'voiceprint_index': idx,
                    'model_similarity': round(similarity, 4),
                }
                all_details.append(details)

            if similarity > max_similarity:
                max_similarity = similarity
                best_details = details

        success = max_similarity >= threshold

        result_details = {
            'threshold': threshold,
            'best_match': best_details,
            'all_matches': all_details,
            'num_stored_voiceprints': len(stored_vectors),
            'method': 'dtw+siamese+cosine' if use_dtw else 'siamese+cosine',
        }

        return success, max_similarity, result_details

    @classmethod
    def get_embedding(
        cls,
        feature_vector: np.ndarray,
        user_id: Optional[int] = None
    ) -> np.ndarray:
        model_manager = get_model_manager()
        normalized = model_manager.normalizer.normalize(
            feature_vector, user_id=user_id
        )
        return model_manager.model.get_embedding(normalized)
