import os
import time
import uuid
import threading
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
from sqlalchemy.orm import Session

from app.models import (
    ServiceHealth, FallbackCache, ReconciliationLog,
    ReconciliationStatus, AuthMethod
)
from app.core.config import settings


class CircuitState(str, Enum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


class ServiceCircuitBreaker:
    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        half_open_max_calls: int = 3,
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if (self._last_failure_time and
                        time.time() - self._last_failure_time >= self.timeout_seconds):
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
            return self._state

    def allow_request(self) -> bool:
        current_state = self.state
        if current_state == CircuitState.OPEN:
            return False
        if current_state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._success_count >= self.half_open_max_calls:
                    return False
        return True

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._success_count += 1
            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._success_count = 0

    def reset(self):
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None

    def get_metrics(self) -> Dict[str, Any]:
        return {
            'state': self.state.value,
            'failure_count': self._failure_count,
            'success_count': self._success_count,
            'last_failure_time': self._last_failure_time,
            'failure_threshold': self.failure_threshold,
            'timeout_seconds': self.timeout_seconds,
        }


class ServiceHealthManager:
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

        self._circuits: Dict[str, ServiceCircuitBreaker] = {}
        self._voiceprint_circuit = ServiceCircuitBreaker(
            service_name="voiceprint",
            failure_threshold=getattr(settings, 'circuit_failure_threshold', 5),
            timeout_seconds=getattr(settings, 'circuit_timeout_seconds', 60),
        )
        self._circuits["voiceprint"] = self._voiceprint_circuit

        self._monitor_thread = None
        self._monitor_running = False
        self._start_monitor()

    def _start_monitor(self):
        if self._monitor_thread is not None:
            return

        self._monitor_running = True

        def monitor_loop():
            while self._monitor_running:
                try:
                    self._check_voiceprint_service()
                except Exception as e:
                    print(f"Health monitor error: {e}")
                time.sleep(15)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _check_voiceprint_service(self):
        try:
            from app.services.model_manager import get_model_manager
            mm = get_model_manager()
            model = mm.get_model(0)
            import numpy as np
            test_feature = np.random.randn(200).astype(np.float32)
            _ = model.get_embedding(test_feature)
            self._voiceprint_circuit.record_success()
            self._sync_health_to_db(
                "voiceprint", is_healthy=True,
                message="Service operational",
                metrics=self._voiceprint_circuit.get_metrics()
            )
        except Exception as e:
            print(f"Voiceprint service health check failed: {e}")
            self._voiceprint_circuit.record_failure()
            self._sync_health_to_db(
                "voiceprint", is_healthy=False,
                message=str(e),
                metrics=self._voiceprint_circuit.get_metrics()
            )

    def _sync_health_to_db(
        self,
        service_name: str,
        is_healthy: bool,
        message: str = "",
        metrics: Optional[Dict] = None,
    ):
        try:
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                health = db.query(ServiceHealth).filter(
                    ServiceHealth.service_name == service_name
                ).first()

                if health is None:
                    health = ServiceHealth(service_name=service_name)
                    db.add(health)

                health.is_healthy = is_healthy
                health.last_check = datetime.utcnow()
                health.status_message = message[:500] if message else ""
                health.metrics = metrics or {}

                if not is_healthy:
                    health.last_failure = datetime.utcnow()
                    health.failure_count = (health.failure_count or 0) + 1

                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"Failed to sync health to DB: {e}")

    def is_voiceprint_service_healthy(self) -> bool:
        return self._voiceprint_circuit.allow_request()

    def record_voiceprint_success(self):
        self._voiceprint_circuit.record_success()

    def record_voiceprint_failure(self):
        self._voiceprint_circuit.record_failure()

    def get_voiceprint_circuit_state(self) -> str:
        return self._voiceprint_circuit.state.value

    def get_service_status(self) -> Dict[str, Any]:
        return {
            'voiceprint': {
                'is_healthy': self.is_voiceprint_service_healthy(),
                'circuit_state': self.get_voiceprint_circuit_state(),
                'metrics': self._voiceprint_circuit.get_metrics(),
                'fallback_mode': not self.is_voiceprint_service_healthy(),
                'fallback_method': AuthMethod.WEBAUTHN.value,
            }
        }

    def create_fallback_cache(
        self,
        db: Session,
        tenant_id: int,
        user_id: int,
        original_auth_method: str,
        ip_address: Optional[str] = None,
        ttl_minutes: int = 30,
    ) -> FallbackCache:
        cache_token = f"fb_{uuid.uuid4().hex}"
        cache = FallbackCache(
            tenant_id=tenant_id,
            user_id=user_id,
            cache_token=cache_token,
            original_auth_method=original_auth_method,
            fallback_method=AuthMethod.WEBAUTHN.value,
            ip_address=ip_address,
            expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
            is_used=False,
        )
        db.add(cache)
        db.flush()
        return cache

    def validate_fallback_cache(
        self,
        db: Session,
        cache_token: str,
    ) -> Optional[FallbackCache]:
        cache = db.query(FallbackCache).filter(
            FallbackCache.cache_token == cache_token,
            FallbackCache.is_used == False,
            FallbackCache.expires_at > datetime.utcnow(),
        ).first()

        if cache:
            cache.is_used = True
            cache.used_at = datetime.utcnow()
            db.flush()
            return cache
        return None

    def create_reconciliation_task(
        self,
        db: Session,
        tenant_id: int,
        cache_token: str,
        original_login_id: Optional[int] = None,
    ) -> ReconciliationLog:
        recon = ReconciliationLog(
            tenant_id=tenant_id,
            cache_token=cache_token,
            original_login_id=original_login_id,
            status=ReconciliationStatus.PENDING,
        )
        db.add(recon)
        db.flush()
        return recon

    def should_use_fallback(self) -> bool:
        use_fallback = getattr(settings, 'enable_fallback_mode', True)
        return use_fallback and not self.is_voiceprint_service_healthy()

    def force_circuit_open(self, service_name: str = "voiceprint"):
        circuit = self._circuits.get(service_name)
        if circuit:
            for _ in range(circuit.failure_threshold):
                circuit.record_failure()

    def force_circuit_closed(self, service_name: str = "voiceprint"):
        circuit = self._circuits.get(service_name)
        if circuit:
            circuit.reset()


_health_manager_instance: Optional[ServiceHealthManager] = None


def get_service_health_manager() -> ServiceHealthManager:
    global _health_manager_instance
    if _health_manager_instance is None:
        _health_manager_instance = ServiceHealthManager()
    return _health_manager_instance
