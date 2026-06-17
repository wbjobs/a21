import os
import pickle
import threading
import time
from typing import Optional, Tuple, List
from pathlib import Path
import numpy as np
import torch

from app.services.siamese_model import VoiceprintSiameseModel
from app.services.feature_normalizer import AdaptiveNormalizer
from app.core.config import settings


class ModelManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.model_dir = Path(os.getenv('MODEL_DIR', 'backend/models'))
        self.model_path = self.model_dir / 'voiceprint_siamese.pt'
        self.normalizer_path = self.model_dir / 'normalizer.pkl'

        self._model: Optional[VoiceprintSiameseModel] = None
        self._normalizer: Optional[AdaptiveNormalizer] = None

        self._model_last_modified = None
        self._normalizer_last_modified = None
        self._watch_thread = None
        self._watch_running = False

        self._init_models()
        self._start_file_watcher()

    def _init_models(self):
        self.model_dir.mkdir(parents=True, exist_ok=True)

        if self.model_path.exists():
            try:
                self._load_model()
            except Exception as e:
                print(f"Warning: Failed to load model: {e}")
                self._create_default_model()
        else:
            print("No pre-trained model found, creating default model...")
            self._create_default_model()

        if self.normalizer_path.exists():
            try:
                self._load_normalizer()
            except Exception as e:
                print(f"Warning: Failed to load normalizer: {e}")
                self._create_default_normalizer()
        else:
            self._create_default_normalizer()

    def _create_default_model(self):
        print("Creating default Siamese model...")
        self._model = VoiceprintSiameseModel(
            input_dim=200,
            embedding_dim=128,
            margin=0.5
        )
        self._model.model.eval()
        self._model_last_modified = time.time()

    def _create_default_normalizer(self):
        print("Creating default feature normalizer...")
        self._normalizer = AdaptiveNormalizer(feature_dim=200)
        self._normalizer_last_modified = time.time()

    def _load_model(self):
        print(f"Loading model from {self.model_path}...")
        self._model = VoiceprintSiameseModel(input_dim=200, embedding_dim=128)
        self._model.load(str(self.model_path))
        self._model.model.eval()
        self._model_last_modified = os.path.getmtime(self.model_path)
        print("Model loaded successfully")

    def _load_normalizer(self):
        print(f"Loading normalizer from {self.normalizer_path}...")
        with open(self.normalizer_path, 'rb') as f:
            self._normalizer = pickle.load(f)
        self._normalizer_last_modified = os.path.getmtime(self.normalizer_path)
        print("Normalizer loaded successfully")

    def _reload_if_updated(self):
        try:
            if self.model_path.exists():
                current_mtime = os.path.getmtime(self.model_path)
                if self._model_last_modified is None or current_mtime > self._model_last_modified:
                    print(f"Model file changed, reloading...")
                    self._load_model()

            if self.normalizer_path.exists():
                current_mtime = os.path.getmtime(self.normalizer_path)
                if self._normalizer_last_modified is None or current_mtime > self._normalizer_last_modified:
                    print(f"Normalizer file changed, reloading...")
                    self._load_normalizer()
        except Exception as e:
            print(f"Error reloading models: {e}")

    def _start_file_watcher(self):
        if self._watch_thread is not None:
            return

        self._watch_running = True

        def watch_loop():
            while self._watch_running:
                try:
                    self._reload_if_updated()
                except Exception as e:
                    print(f"File watcher error: {e}")
                time.sleep(5)

        self._watch_thread = threading.Thread(target=watch_loop, daemon=True)
        self._watch_thread.start()

    def stop_watcher(self):
        self._watch_running = False
        if self._watch_thread:
            self._watch_thread.join()

    @property
    def model(self) -> VoiceprintSiameseModel:
        if self._model is None:
            self._create_default_model()
        return self._model

    @property
    def normalizer(self) -> AdaptiveNormalizer:
        if self._normalizer is None:
            self._create_default_normalizer()
        return self._normalizer

    def is_model_trained(self) -> bool:
        return self.model_path.exists()

    def get_model_info(self) -> dict:
        return {
            "model_path": str(self.model_path),
            "model_exists": self.model_path.exists(),
            "normalizer_path": str(self.normalizer_path),
            "normalizer_exists": self.normalizer_path.exists(),
            "model_last_modified": self._model_last_modified,
            "normalizer_last_modified": self._normalizer_last_modified,
            "input_dim": 200,
            "embedding_dim": self.model.embedding_dim if self._model else 128,
            "is_trained": self.is_model_trained(),
        }

    def reload_models(self):
        print("Manual model reload triggered")
        if self.model_path.exists():
            self._load_model()
        if self.normalizer_path.exists():
            self._load_normalizer()

    def verify_voiceprints(
        self,
        input_feature: np.ndarray,
        stored_vectors: List[np.ndarray],
        user_id: Optional[int] = None,
        use_dtw_alignment: bool = True
    ) -> Tuple[bool, float, dict]:
        normalized_input = self.normalizer.normalize(input_feature, user_id=user_id)

        if use_dtw_alignment and len(stored_vectors) > 0:
            from app.services.dtw_aligner import DynamicTimeWarping
            dtw = DynamicTimeWarping(window_size=30)

            best_similarity = 0.0
            dtw_costs = []

            for stored_vec in stored_vectors:
                normalized_stored = self.normalizer.normalize(
                    np.array(stored_vec),
                    user_id=user_id
                )

                _, _, dtw_cost, _ = dtw.align(
                    normalized_input.reshape(-1, 1),
                    normalized_stored.reshape(-1, 1)
                )
                dtw_costs.append(dtw_cost)

                model_similarity = self.model.compute_similarity(
                    normalized_input,
                    normalized_stored
                )

                dtw_similarity = 1.0 / (1.0 + dtw_cost)

                combined_similarity = 0.6 * model_similarity + 0.4 * dtw_similarity

                if combined_similarity > best_similarity:
                    best_similarity = combined_similarity

            threshold = getattr(settings, 'voiceprint_similarity_threshold', 0.7)
            success = best_similarity >= threshold

            return success, best_similarity, {
                "model_similarity": model_similarity if stored_vectors else 0,
                "dtw_costs": dtw_costs,
                "threshold": threshold,
            }

        else:
            max_similarity = 0.0
            for stored_vec in stored_vectors:
                normalized_stored = self.normalizer.normalize(
                    np.array(stored_vec),
                    user_id=user_id
                )
                similarity = self.model.compute_similarity(
                    normalized_input,
                    normalized_stored
                )
                if similarity > max_similarity:
                    max_similarity = similarity

            threshold = getattr(settings, 'voiceprint_similarity_threshold', 0.7)
            success = max_similarity >= threshold

            return success, max_similarity, {
                "model_similarity": max_similarity,
                "dtw_used": False,
                "threshold": threshold,
            }

    def extract_enhanced_feature(
        self,
        raw_feature: np.ndarray,
        user_id: Optional[int] = None
    ) -> np.ndarray:
        normalized = self.normalizer.normalize(raw_feature, user_id=user_id)
        embedding = self.model.get_embedding(normalized)
        enhanced = np.concatenate([normalized, embedding])
        return enhanced


def get_model_manager() -> ModelManager:
    return ModelManager()
