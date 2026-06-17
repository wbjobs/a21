import os
import pickle
import threading
import time
import uuid
from typing import Optional, Tuple, List, Dict
from pathlib import Path
import numpy as np
import torch

from app.services.siamese_model import VoiceprintSiameseModel
from app.services.feature_normalizer import AdaptiveNormalizer
from app.core.config import settings
from app.database import get_db
from app.models import Tenant


class TenantModelContainer:
    def __init__(self, tenant_id: int, model_dir: Path):
        self.tenant_id = tenant_id
        self.model_dir = model_dir
        self.model: Optional[VoiceprintSiameseModel] = None
        self.normalizer: Optional[AdaptiveNormalizer] = None
        self.model_last_modified: Optional[float] = None
        self.normalizer_last_modified: Optional[float] = None
        self.lock = threading.RLock()
        self.load_count = 0

    @property
    def model_path(self) -> Path:
        return self.model_dir / f"tenant_{self.tenant_id}" / "voiceprint_siamese.pt"

    @property
    def normalizer_path(self) -> Path:
        return self.model_dir / f"tenant_{self.tenant_id}" / "normalizer.pkl"

    def ensure_dirs(self):
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self, force_reload: bool = False):
        with self.lock:
            if self.model is not None and not force_reload:
                if not self._needs_reload():
                    return

            self.ensure_dirs()

            if self.model_path.exists():
                try:
                    print(f"[Tenant {self.tenant_id}] Loading model from {self.model_path}")
                    self.model = VoiceprintSiameseModel(input_dim=200, embedding_dim=128)
                    self.model.load(str(self.model_path))
                    self.model.model.eval()
                    self.model_last_modified = os.path.getmtime(self.model_path)
                except Exception as e:
                    print(f"[Tenant {self.tenant_id}] Failed to load model: {e}")
                    self._create_default_model()
            else:
                print(f"[Tenant {self.tenant_id}] No custom model found, using default")
                self._create_default_model()

            if self.normalizer_path.exists():
                try:
                    print(f"[Tenant {self.tenant_id}] Loading normalizer from {self.normalizer_path}")
                    with open(self.normalizer_path, 'rb') as f:
                        self.normalizer = pickle.load(f)
                    self.normalizer_last_modified = os.path.getmtime(self.normalizer_path)
                except Exception as e:
                    print(f"[Tenant {self.tenant_id}] Failed to load normalizer: {e}")
                    self._create_default_normalizer()
            else:
                self._create_default_normalizer()

            self.load_count += 1

    def _needs_reload(self) -> bool:
        try:
            if self.model_path.exists():
                mtime = os.path.getmtime(self.model_path)
                if self.model_last_modified is None or mtime > self.model_last_modified:
                    return True
            if self.normalizer_path.exists():
                mtime = os.path.getmtime(self.normalizer_path)
                if self.normalizer_last_modified is None or mtime > self.normalizer_last_modified:
                    return True
        except Exception:
            pass
        return False

    def _create_default_model(self):
        self.model = VoiceprintSiameseModel(
            input_dim=200,
            embedding_dim=128,
            margin=0.5
        )
        self.model.model.eval()
        self.model_last_modified = time.time()

    def _create_default_normalizer(self):
        self.normalizer = AdaptiveNormalizer(feature_dim=200)
        self.normalizer_last_modified = time.time()

    def check_and_reload(self):
        if self._needs_reload():
            print(f"[Tenant {self.tenant_id}] Model files updated, reloading...")
            self.load(force_reload=True)


class MultiTenantModelManager:
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
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self._tenants: Dict[int, TenantModelContainer] = {}
        self._global_container = TenantModelContainer(tenant_id=0, model_dir=self.model_dir)
        self._global_container.load()

        self._watch_thread = None
        self._watch_running = False
        self._start_file_watcher()

    def _get_tenant_container(self, tenant_id: int) -> TenantModelContainer:
        if tenant_id not in self._tenants:
            with self._lock:
                if tenant_id not in self._tenants:
                    container = TenantModelContainer(tenant_id=tenant_id, model_dir=self.model_dir)
                    container.load()
                    self._tenants[tenant_id] = container
        return self._tenants[tenant_id]

    def get_model(self, tenant_id: int) -> VoiceprintSiameseModel:
        if tenant_id is None or tenant_id <= 0:
            return self._global_container.model
        container = self._get_tenant_container(tenant_id)
        return container.model

    def get_normalizer(self, tenant_id: int) -> AdaptiveNormalizer:
        if tenant_id is None or tenant_id <= 0:
            return self._global_container.normalizer
        container = self._get_tenant_container(tenant_id)
        return container.normalizer

    def get_threshold(self, tenant_id: int, db=None) -> float:
        if tenant_id and tenant_id > 0 and db:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant and tenant.voiceprint_threshold:
                return tenant.voiceprint_threshold
        return getattr(settings, 'voiceprint_similarity_threshold', 0.70)

    def verify_voiceprints(
        self,
        input_feature: np.ndarray,
        stored_vectors: List[np.ndarray],
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        use_dtw_alignment: bool = True,
        db=None
    ) -> Tuple[bool, float, dict]:
        normalizer = self.get_normalizer(tenant_id)
        model = self.get_model(tenant_id)
        threshold = self.get_threshold(tenant_id, db)
        weights = getattr(settings, 'similarity_weights', {
            'model': 0.5, 'dtw': 0.3, 'cosine': 0.2
        })

        normalized_input = normalizer.normalize(input_feature, user_id=user_id)

        if use_dtw_alignment and len(stored_vectors) > 0:
            from app.services.dtw_aligner import DynamicTimeWarping
            dtw = DynamicTimeWarping(window_size=getattr(settings, 'dtw_window_size', 50))

            best_similarity = 0.0
            all_details = []
            best_detail = {}

            for idx, stored_vec in enumerate(stored_vectors):
                normalized_stored = normalizer.normalize(
                    np.array(stored_vec),
                    user_id=user_id
                )

                _, _, dtw_cost, _ = dtw.align(
                    normalized_input.reshape(-1, 1),
                    normalized_stored.reshape(-1, 1)
                )

                model_sim = model.compute_similarity(normalized_input, normalized_stored)
                dtw_sim = 1.0 / (1.0 + dtw_cost * 5)
                cos_sim = float(
                    np.dot(
                        normalized_input / (np.linalg.norm(normalized_input) + 1e-10),
                        normalized_stored / (np.linalg.norm(normalized_stored) + 1e-10)
                    )
                )

                combined = (
                    weights.get('model', 0.5) * model_sim +
                    weights.get('dtw', 0.3) * dtw_sim +
                    weights.get('cosine', 0.2) * cos_sim
                )

                detail = {
                    'voiceprint_index': idx,
                    'model_similarity': round(model_sim, 4),
                    'dtw_similarity': round(dtw_sim, 4),
                    'dtw_cost': round(dtw_cost, 4),
                    'cosine_similarity': round(cos_sim, 4),
                    'combined_similarity': round(combined, 4),
                }
                all_details.append(detail)

                if combined > best_similarity:
                    best_similarity = combined
                    best_detail = detail

            success = best_similarity >= threshold
            return success, best_similarity, {
                'threshold': threshold,
                'tenant_id': tenant_id,
                'best_match': best_detail,
                'all_matches': all_details,
                'weights': weights,
                'method': 'tenant_dtw_siamese_cosine',
            }

        else:
            max_similarity = 0.0
            for stored_vec in stored_vectors:
                normalized_stored = normalizer.normalize(
                    np.array(stored_vec),
                    user_id=user_id
                )
                sim = model.compute_similarity(normalized_input, normalized_stored)
                if sim > max_similarity:
                    max_similarity = sim

            success = max_similarity >= threshold
            return success, max_similarity, {
                'threshold': threshold,
                'tenant_id': tenant_id,
                'model_similarity': max_similarity,
                'dtw_used': False,
                'method': 'tenant_siamese',
            }

    def get_tenant_model_info(self, tenant_id: int) -> dict:
        if tenant_id <= 0:
            container = self._global_container
        else:
            container = self._get_tenant_container(tenant_id)

        return {
            'tenant_id': tenant_id,
            'model_path': str(container.model_path),
            'model_exists': container.model_path.exists(),
            'normalizer_path': str(container.normalizer_path),
            'normalizer_exists': container.normalizer_path.exists(),
            'model_last_modified': container.model_last_modified,
            'normalizer_last_modified': container.normalizer_last_modified,
            'load_count': container.load_count,
        }

    def reload_tenant_model(self, tenant_id: int):
        if tenant_id <= 0:
            self._global_container.load(force_reload=True)
        elif tenant_id in self._tenants:
            self._tenants[tenant_id].load(force_reload=True)

    def reload_all_models(self):
        print("Reloading all tenant models...")
        self._global_container.load(force_reload=True)
        for tenant_id, container in self._tenants.items():
            try:
                container.load(force_reload=True)
            except Exception as e:
                print(f"Failed to reload model for tenant {tenant_id}: {e}")

    def _start_file_watcher(self):
        if self._watch_thread is not None:
            return

        self._watch_running = True

        def watch_loop():
            while self._watch_running:
                try:
                    self._global_container.check_and_reload()
                    for container in self._tenants.values():
                        container.check_and_reload()
                except Exception as e:
                    print(f"Model watcher error: {e}")
                time.sleep(10)

        self._watch_thread = threading.Thread(target=watch_loop, daemon=True)
        self._watch_thread.start()

    def list_loaded_tenants(self) -> list:
        return [
            self.get_tenant_model_info(tid)
            for tid in self._tenants.keys()
        ]

    def train_tenant_model(
        self,
        tenant_id: int,
        features: List[np.ndarray],
        labels: List[int],
        n_epochs: int = 50
    ) -> Tuple[bool, str]:
        try:
            from scripts.train_siamese import VoiceprintDataset, train_model
            import tempfile

            container = self._get_tenant_container(tenant_id)
            container.ensure_dirs()

            temp_dir = Path(tempfile.mkdtemp())
            temp_model_path = temp_dir / "temp_model.pt"

            model = train_model(
                output_path=str(temp_model_path),
                feature_dim=200,
                embedding_dim=128,
                n_epochs=n_epochs,
                batch_size=min(64, max(8, len(features) // 4)),
            )

            if temp_model_path.exists():
                import shutil
                shutil.copy(str(temp_model_path), str(container.model_path))
                print(f"[Tenant {tenant_id}] Model trained and saved")
                container.load(force_reload=True)
                return True, "Model trained successfully"

            return False, "Model training produced no output"
        except Exception as e:
            print(f"[Tenant {tenant_id}] Model training failed: {e}")
            return False, str(e)


_model_manager_instance: Optional[MultiTenantModelManager] = None


def get_model_manager() -> MultiTenantModelManager:
    global _model_manager_instance
    if _model_manager_instance is None:
        _model_manager_instance = MultiTenantModelManager()
    return _model_manager_instance
