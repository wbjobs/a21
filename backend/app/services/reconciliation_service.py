import os
import time
import json
import base64
import tempfile
import threading
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session
import numpy as np

from app.models import (
    ReconciliationLog, ReconciliationStatus,
    FallbackCache, VoicePrint, LoginLog, LoginStatus
)
from app.services.model_manager import get_model_manager
from app.services.voice_service import get_voice_service


class PendingVerificationCache:
    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.getenv('FALLBACK_CACHE_DIR', 'backend/fallback_cache')
        self.cache_dir = Path(base_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _get_cache_path(self, cache_token: str) -> Path:
        return self.cache_dir / f"{cache_token}.json"

    def store_pending_verification(
        self,
        cache_token: str,
        tenant_id: int,
        user_id: int,
        audio_b64: Optional[str] = None,
        raw_feature: Optional[List[float]] = None,
        metadata: Optional[Dict] = None,
    ):
        data = {
            'cache_token': cache_token,
            'tenant_id': tenant_id,
            'user_id': user_id,
            'audio_b64': audio_b64,
            'raw_feature': raw_feature,
            'metadata': metadata or {},
            'stored_at': datetime.utcnow().isoformat(),
        }

        with self._lock:
            with open(self._get_cache_path(cache_token), 'w', encoding='utf-8') as f:
                json.dump(data, f)

    def load_pending_verification(self, cache_token: str) -> Optional[Dict]:
        path = self._get_cache_path(cache_token)
        if not path.exists():
            return None

        with self._lock:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        return data

    def remove_pending_verification(self, cache_token: str):
        path = self._get_cache_path(cache_token)
        if path.exists():
            with self._lock:
                try:
                    path.unlink()
                except Exception:
                    pass

    def list_pending_tokens(self, max_age_hours: int = 24) -> List[str]:
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        tokens = []

        with self._lock:
            for path in self.cache_dir.glob("*.json"):
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    if mtime >= cutoff:
                        tokens.append(path.stem)
                    else:
                        path.unlink()
                except Exception:
                    pass

        return tokens


class ReconciliationWorker:
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

        self.pending_cache = PendingVerificationCache()
        self._worker_thread = None
        self._worker_running = False
        self._processed_count = 0
        self._conflict_count = 0

        self._start_worker()

    def _start_worker(self):
        if self._worker_thread is not None:
            return

        self._worker_running = True

        def worker_loop():
            while self._worker_running:
                try:
                    self._process_batch()
                except Exception as e:
                    print(f"Reconciliation worker error: {e}")
                time.sleep(10)

        self._worker_thread = threading.Thread(target=worker_loop, daemon=True)
        self._worker_thread.start()

    def _process_batch(self):
        from app.database import SessionLocal
        db = SessionLocal()

        try:
            pending = db.query(ReconciliationLog).filter(
                ReconciliationLog.status == ReconciliationStatus.PENDING
            ).limit(20).all()

            for recon in pending:
                try:
                    self._reconcile_one(db, recon)
                except Exception as e:
                    print(f"Failed to reconcile {recon.id}: {e}")
                    recon.status = ReconciliationStatus.FAILED
                    recon.conflict_details = {'error': str(e)}
                    recon.reconciled_at = datetime.utcnow()

            db.commit()
        finally:
            db.close()

    def _reconcile_one(self, db: Session, recon: ReconciliationLog):
        cache_data = self.pending_cache.load_pending_verification(recon.cache_token)

        if cache_data is None:
            recon.status = ReconciliationStatus.FAILED
            recon.conflict_details = {'error': 'cache_data_missing'}
            recon.reconciled_at = datetime.utcnow()
            return

        tenant_id = cache_data['tenant_id']
        user_id = cache_data['user_id']

        input_feature = None
        if cache_data.get('raw_feature'):
            input_feature = np.array(cache_data['raw_feature'], dtype=np.float32)
        elif cache_data.get('audio_b64'):
            try:
                audio_bytes = base64.b64decode(cache_data['audio_b64'])
                voice_service = get_voice_service()
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name
                try:
                    input_feature = voice_service.extract_mfcc_from_file(tmp_path)
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception as e:
                recon.status = ReconciliationStatus.FAILED
                recon.conflict_details = {'error': 'audio_decode_failed', 'detail': str(e)}
                recon.reconciled_at = datetime.utcnow()
                return

        if input_feature is None:
            recon.status = ReconciliationStatus.FAILED
            recon.conflict_details = {'error': 'no_feature_or_audio'}
            recon.reconciled_at = datetime.utcnow()
            return

        stored_vectors = db.query(VoicePrint.feature_vector).filter(
            VoicePrint.tenant_id == tenant_id,
            VoicePrint.user_id == user_id,
        ).all()

        stored_list = [np.array(v[0]) for v in stored_vectors]

        if not stored_list:
            recon.status = ReconciliationStatus.FAILED
            recon.conflict_details = {'error': 'no_registered_voiceprints'}
            recon.reconciled_at = datetime.utcnow()
            return

        mm = get_model_manager()
        success, similarity, details = mm.verify_voiceprints(
            input_feature=input_feature,
            stored_vectors=stored_list,
            tenant_id=tenant_id,
            user_id=user_id,
            use_dtw_alignment=True,
            db=db,
        )

        recon.voice_similarity = float(similarity)
        recon.voice_verification_status = "success" if success else "failed"

        if success:
            recon.status = ReconciliationStatus.COMPLETED
        else:
            recon.status = ReconciliationStatus.CONFLICT
            recon.conflict_details = {
                'reason': 'voice_verification_failed_after_fallback',
                'similarity': float(similarity),
                'threshold': details.get('threshold'),
                'details': details,
            }
            self._conflict_count += 1

        recon.reconciled_at = datetime.utcnow()
        self._processed_count += 1

        self.pending_cache.remove_pending_verification(recon.cache_token)

        if recon.status == ReconciliationStatus.CONFLICT:
            from app.services.audit_service import get_audit_logger
            get_audit_logger().log_anomaly(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                anomaly_type="reconciliation_conflict",
                description=(
                    f"降级登录对账冲突：用户 {user_id} 在降级模式下通过WebAuthn登录，"
                    f"但恢复服务后声纹验证失败（相似度: {similarity:.4f}）"
                ),
                severity="high",
                details=recon.conflict_details,
            )

    def submit_pending_reconciliation(
        self,
        db: Session,
        tenant_id: int,
        user_id: int,
        cache_token: str,
        original_login_id: Optional[int] = None,
        audio_b64: Optional[str] = None,
        raw_feature: Optional[List[float]] = None,
        metadata: Optional[Dict] = None,
    ) -> ReconciliationLog:
        if audio_b64 or raw_feature:
            self.pending_cache.store_pending_verification(
                cache_token=cache_token,
                tenant_id=tenant_id,
                user_id=user_id,
                audio_b64=audio_b64,
                raw_feature=raw_feature,
                metadata=metadata,
            )

        from app.services.health_service import get_service_health_manager
        health_mgr = get_service_health_manager()
        recon = health_mgr.create_reconciliation_task(
            db=db,
            tenant_id=tenant_id,
            cache_token=cache_token,
            original_login_id=original_login_id,
        )
        return recon

    def get_stats(self) -> Dict:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            total_pending = db.query(ReconciliationLog).filter(
                ReconciliationLog.status == ReconciliationStatus.PENDING
            ).count()
            total_completed = db.query(ReconciliationLog).filter(
                ReconciliationLog.status == ReconciliationStatus.COMPLETED
            ).count()
            total_conflicts = db.query(ReconciliationLog).filter(
                ReconciliationLog.status == ReconciliationStatus.CONFLICT
            ).count()
            total_failed = db.query(ReconciliationLog).filter(
                ReconciliationLog.status == ReconciliationStatus.FAILED
            ).count()
        finally:
            db.close()

        return {
            'processed_count': self._processed_count,
            'conflict_count': self._conflict_count,
            'pending_cache_files': len(self.pending_cache.list_pending_tokens()),
            'db_pending': total_pending,
            'db_completed': total_completed,
            'db_conflicts': total_conflicts,
            'db_failed': total_failed,
        }

    def stop(self):
        self._worker_running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)


_reconciliation_worker_instance: Optional[ReconciliationWorker] = None


def get_reconciliation_worker() -> ReconciliationWorker:
    global _reconciliation_worker_instance
    if _reconciliation_worker_instance is None:
        _reconciliation_worker_instance = ReconciliationWorker()
    return _reconciliation_worker_instance
