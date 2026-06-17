import time
import threading
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
import numpy as np

from app.models import (
    LoginLog, LoginStatus, AnomalyType, AnomalyEvent,
    User, VoicePrint
)
from app.services.audit_service import get_audit_logger


class RateLimiter:
    def __init__(self):
        self._attempts: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def record_attempt(self, key: str):
        now = time.time()
        with self._lock:
            self._attempts[key].append(now)
            cutoff = now - 300
            self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]

    def count_recent(self, key: str, seconds: int = 300) -> int:
        now = time.time()
        cutoff = now - seconds
        with self._lock:
            return len([t for t in self._attempts.get(key, []) if t > cutoff])

    def is_rate_limited(self, key: str, max_attempts: int = 10, seconds: int = 300) -> bool:
        return self.count_recent(key, seconds) >= max_attempts

    def cleanup_old(self):
        now = time.time()
        cutoff = now - 600
        with self._lock:
            for key in list(self._attempts.keys()):
                self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]
                if not self._attempts[key]:
                    del self._attempts[key]


class AnomalyDetector:
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
        self.rate_limiter = RateLimiter()

    def check_high_frequency_attempts(
        self,
        db: Session,
        tenant_id: int,
        user_id: Optional[int],
        ip_address: Optional[str],
        username: Optional[str],
    ) -> List[AnomalyEvent]:
        events = []
        now = time.time()

        keys_to_check = []
        if ip_address:
            keys_to_check.append(('ip', f"tenant_{tenant_id}_ip_{ip_address}", ip_address))
        if user_id:
            keys_to_check.append(('user', f"tenant_{tenant_id}_user_{user_id}", str(user_id)))
        if username:
            keys_to_check.append(('username', f"tenant_{tenant_id}_username_{username.lower()}", username))

        for key_type, rate_key, identifier in keys_to_check:
            self.rate_limiter.record_attempt(rate_key)
            count_5min = self.rate_limiter.count_recent(rate_key, 300)
            count_1min = self.rate_limiter.count_recent(rate_key, 60)

            if count_5min >= 15 or count_1min >= 5:
                description = (
                    f"高频登录尝试检测：{key_type}={identifier} 在"
                    f"{count_1min if count_1min >= 5 else count_5min}次尝试"
                )
                event = get_audit_logger().log_anomaly(
                    db=db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    anomaly_type=AnomalyType.HIGH_FREQUENCY_ATTEMPTS,
                    description=description,
                    severity="high" if count_5min >= 25 else "medium",
                    details={
                        'key_type': key_type,
                        'identifier': identifier,
                        'attempts_1min': count_1min,
                        'attempts_5min': count_5min,
                        'threshold_1min': 5,
                        'threshold_5min': 15,
                    }
                )
                events.append(event)

        return events

    def check_multi_location_login(
        self,
        db: Session,
        tenant_id: int,
        user_id: int,
        current_ip: Optional[str],
        current_location: Optional[str],
        time_window_minutes: int = 30,
    ) -> List[AnomalyEvent]:
        if not user_id:
            return []

        cutoff = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        recent_logins = db.query(LoginLog).filter(
            LoginLog.tenant_id == tenant_id,
            LoginLog.user_id == user_id,
            LoginLog.status == LoginStatus.SUCCESS,
            LoginLog.created_at >= cutoff,
        ).all()

        events = []
        seen_locations = set()
        seen_ips = set()

        if current_location:
            seen_locations.add(current_location)
        if current_ip:
            seen_ips.add(current_ip)

        for login in recent_logins:
            if login.location and login.location != current_location:
                seen_locations.add(login.location)
            if login.ip_address and login.ip_address != current_ip:
                seen_ips.add(login.ip_address)

        distinct_locations = len([l for l in seen_locations if l])
        distinct_ips = len([ip for ip in seen_ips if ip])

        if distinct_locations >= 3 or distinct_ips >= 3:
            description = (
                f"多地登录检测：用户 {user_id} 在 {time_window_minutes} 分钟内"
                f"从 {distinct_locations} 个地点 / {distinct_ips} 个IP登录"
            )
            related_ids = [l.id for l in recent_logins[-10:]]
            event = get_audit_logger().log_anomaly(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                anomaly_type=AnomalyType.MULTI_LOCATION_LOGIN,
                description=description,
                severity="high",
                details={
                    'distinct_locations': distinct_locations,
                    'distinct_ips': distinct_ips,
                    'locations_list': list(seen_locations),
                    'ips_list': list(seen_ips),
                    'time_window_minutes': time_window_minutes,
                },
                related_login_ids=related_ids,
            )
            events.append(event)

        return events

    def check_voiceprint_reuse(
        self,
        db: Session,
        tenant_id: int,
        user_id: int,
        input_feature: np.ndarray,
        similarity_threshold: float = 0.85,
    ) -> List[AnomalyEvent]:
        events = []

        cutoff = datetime.utcnow() - timedelta(minutes=60)
        other_users_vp = db.query(VoicePrint).filter(
            VoicePrint.tenant_id == tenant_id,
            VoicePrint.user_id != user_id,
        ).all()

        if not other_users_vp:
            return events

        try:
            from app.services.model_manager import get_model_manager
            mm = get_model_manager()
            normalizer = mm.get_normalizer(tenant_id)
            model = mm.get_model(tenant_id)

            normalized_input = normalizer.normalize(input_feature, user_id=user_id)

            high_similarity_matches = []
            for vp in other_users_vp:
                stored_vec = np.array(vp.feature_vector)
                normalized_stored = normalizer.normalize(stored_vec, user_id=vp.user_id)
                sim = model.compute_similarity(normalized_input, normalized_stored)

                if sim >= similarity_threshold:
                    high_similarity_matches.append({
                        'other_user_id': vp.user_id,
                        'voiceprint_id': vp.id,
                        'similarity': round(float(sim), 4),
                    })

            if high_similarity_matches:
                description = (
                    f"声纹复用检测：用户 {user_id} 的声纹与其他 {len(high_similarity_matches)} 个用户高度相似"
                )
                event = get_audit_logger().log_anomaly(
                    db=db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    anomaly_type=AnomalyType.VOICEPRINT_REUSE,
                    description=description,
                    severity="high",
                    details={
                        'matches': high_similarity_matches,
                        'threshold': similarity_threshold,
                        'total_checked': len(other_users_vp),
                    }
                )
                events.append(event)

        except Exception as e:
            print(f"Voiceprint reuse check failed: {e}")

        return events

    def check_unusual_device(
        self,
        db: Session,
        tenant_id: int,
        user_id: int,
        device_fingerprint: Optional[str],
    ) -> List[AnomalyEvent]:
        if not user_id or not device_fingerprint:
            return []

        recent_devices = db.query(LoginLog).filter(
            LoginLog.tenant_id == tenant_id,
            LoginLog.user_id == user_id,
            LoginLog.status == LoginStatus.SUCCESS,
            LoginLog.device_fingerprint.isnot(None),
        ).distinct(LoginLog.device_fingerprint).limit(10).all()

        known_devices = {l.device_fingerprint for l in recent_devices if l.device_fingerprint}

        if known_devices and device_fingerprint not in known_devices:
            description = (
                f"未知设备登录：用户 {user_id} 从新设备登录，"
                f"已记录设备数: {len(known_devices)}"
            )
            event = get_audit_logger().log_anomaly(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                anomaly_type=AnomalyType.UNUSUAL_DEVICE,
                description=description,
                severity="medium",
                details={
                    'device_fingerprint': device_fingerprint,
                    'known_device_count': len(known_devices),
                }
            )
            return [event]

        return []

    def check_abnormal_similarity(
        self,
        db: Session,
        tenant_id: int,
        user_id: int,
        similarity: float,
        threshold: float,
    ) -> List[AnomalyEvent]:
        if not user_id:
            return []

        margin = similarity - threshold
        if 0 <= margin <= 0.02:
            description = (
                f"声纹相似度临界：用户 {user_id} 验证相似度 {similarity:.4f} "
                f"仅略高于阈值 {threshold:.4f} (差距 {margin:.4f})"
            )
            event = get_audit_logger().log_anomaly(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                anomaly_type=AnomalyType.ABNORMAL_SIMILARITY,
                description=description,
                severity="low",
                details={
                    'similarity': similarity,
                    'threshold': threshold,
                    'margin': margin,
                }
            )
            return [event]

        return []

    def run_all_checks(
        self,
        db: Session,
        tenant_id: int,
        user_id: Optional[int],
        request_info: Dict,
        auth_method: str,
        similarity: Optional[float] = None,
        threshold: Optional[float] = None,
        input_feature: Optional[np.ndarray] = None,
    ) -> List[AnomalyEvent]:
        all_events = []

        try:
            all_events.extend(self.check_high_frequency_attempts(
                db, tenant_id, user_id,
                request_info.get('ip_address'),
                request_info.get('username')
            ))
        except Exception as e:
            print(f"High frequency check failed: {e}")

        if user_id and auth_method.startswith('voiceprint'):
            try:
                all_events.extend(self.check_multi_location_login(
                    db, tenant_id, user_id,
                    request_info.get('ip_address'),
                    request_info.get('location')
                ))
            except Exception as e:
                print(f"Multi-location check failed: {e}")

        if user_id and input_feature is not None and auth_method.startswith('voiceprint'):
            try:
                all_events.extend(self.check_voiceprint_reuse(
                    db, tenant_id, user_id, input_feature
                ))
            except Exception as e:
                print(f"Voiceprint reuse check failed: {e}")

        if user_id:
            try:
                all_events.extend(self.check_unusual_device(
                    db, tenant_id, user_id,
                    request_info.get('device_fingerprint')
                ))
            except Exception as e:
                print(f"Unusual device check failed: {e}")

        if user_id and similarity is not None and threshold is not None:
            try:
                all_events.extend(self.check_abnormal_similarity(
                    db, tenant_id, user_id, similarity, threshold
                ))
            except Exception as e:
                print(f"Abnormal similarity check failed: {e}")

        return all_events


_detector_instance: Optional[AnomalyDetector] = None


def get_anomaly_detector() -> AnomalyDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = AnomalyDetector()
    return _detector_instance
