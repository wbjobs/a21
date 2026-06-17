import io
import base64
import random
import string
import tempfile
import os
import numpy as np
import librosa
import soundfile as sf
from scipy.spatial.distance import cosine
from typing import Optional, Tuple
from app.core.config import settings


class VoiceService:
    @staticmethod
    def generate_challenge_digits(length: int = 4) -> str:
        return ''.join(random.choices(string.digits, k=length))

    @staticmethod
    def _load_audio_from_base64(base64_audio: str) -> Tuple[np.ndarray, int]:
        audio_data = base64.b64decode(base64_audio)
        audio_buffer = io.BytesIO(audio_data)
        y, sr = librosa.load(audio_buffer, sr=16000)
        return y, sr

    @staticmethod
    def _preprocess_audio(y: np.ndarray, sr: int) -> np.ndarray:
        if len(y) < sr * 0.5:
            pad_len = int(sr * 0.5) - len(y)
            y = np.pad(y, (0, pad_len), mode='constant')

        y = librosa.util.normalize(y)

        y_trimmed, _ = librosa.effects.trim(y, top_db=20)
        if len(y_trimmed) > 0:
            y = y_trimmed

        return y

    @staticmethod
    def _extract_mfcc(y: np.ndarray, sr: int) -> np.ndarray:
        n_mfcc = settings.mfcc_n_mfcc
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
        delta_mfccs = librosa.feature.delta(mfccs)
        delta2_mfccs = librosa.feature.delta(mfccs, order=2)

        combined = np.concatenate([
            np.mean(mfccs, axis=1),
            np.std(mfccs, axis=1),
            np.mean(delta_mfccs, axis=1),
            np.std(delta_mfccs, axis=1),
            np.mean(delta2_mfccs, axis=1),
            np.std(delta2_mfccs, axis=1),
        ])

        return combined

    @classmethod
    def extract_feature_vector(cls, base64_audio: str) -> Optional[np.ndarray]:
        try:
            y, sr = cls._load_audio_from_base64(base64_audio)
            y = cls._preprocess_audio(y, sr)
            feature = cls._extract_mfcc(y, sr)

            if feature.shape[0] < 200:
                pad_len = 200 - feature.shape[0]
                feature = np.pad(feature, (0, pad_len), mode='constant')
            else:
                feature = feature[:200]

            feature = feature / (np.linalg.norm(feature) + 1e-10)
            return feature
        except Exception as e:
            print(f"Error extracting voice features: {e}")
            return None

    @staticmethod
    def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
        vec1_norm = vec1 / (np.linalg.norm(vec1) + 1e-10)
        vec2_norm = vec2 / (np.linalg.norm(vec2) + 1e-10)
        return float(1.0 - cosine(vec1_norm, vec2_norm))

    @staticmethod
    def verify_voiceprints(input_feature: np.ndarray, stored_vectors: list) -> Tuple[bool, float]:
        if not stored_vectors:
            return False, 0.0

        max_similarity = 0.0
        input_vec = np.array(input_feature)

        for stored_vec in stored_vectors:
            stored_arr = np.array(stored_vec)
            similarity = VoiceService.cosine_similarity(input_vec, stored_arr)
            if similarity > max_similarity:
                max_similarity = similarity

        threshold = settings.voiceprint_similarity_threshold
        return max_similarity >= threshold, max_similarity
