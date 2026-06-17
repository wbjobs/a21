import json
import time
import threading
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import Request

from app.models import (
    LoginLog, LoginStatus, AuthMethod,
    AnomalyEvent, AnomalyType
)


class AuditLogger:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def _extract_request_info(self, request: Optional[Request]) -> Dict[str, Any]:
        if request is None:
            return {}

        ip_address = None
        try:
            forwarded = request.headers.get('X-Forwarded-For')
            if forwarded:
                ip_address = forwarded.split(',')[0].strip()
            else:
                ip_address = request.client.host if request.client else None
        except Exception:
            pass

        user_agent = request.headers.get('User-Agent', '')[:500]

        return {
            'ip_address': ip_address,
            'user_agent': user_agent,
        }

    def log_login(
        self,
        db: Session,
        tenant_id: int,
        user_id: Optional[int],
        username: Optional[str],
        auth_method: str,
        status: str,
        request: Optional[Request] = None,
        similarity_score: Optional[float] = None,
        anomaly_detected: bool = False,
        fallback_triggered: bool = False,
        fallback_reason: Optional[str] = None,
        verification_details: Optional[Dict] = None,
        location: Optional[str] = None,
        device_fingerprint: Optional[str] = None,
    ) -> LoginLog:
        req_info = self._extract_request_info(request)

        log_entry = LoginLog(
            tenant_id=tenant_id,
            user_id=user_id,
            username=username,
            auth_method=auth_method,
            status=status,
            ip_address=req_info.get('ip_address'),
            user_agent=req_info.get('user_agent'),
            location=location,
            device_fingerprint=device_fingerprint,
            similarity_score=similarity_score,
            anomaly_detected=anomaly_detected,
            fallback_triggered=fallback_triggered,
            fallback_reason=fallback_reason,
            verification_details=verification_details,
        )

        db.add(log_entry)

        if status == LoginStatus.SUCCESS and user_id:
            from app.models import User
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.last_login_at = datetime.utcnow()
                user.last_login_ip = req_info.get('ip_address')
                user.last_login_location = location

        db.flush()
        return log_entry

    def log_anomaly(
        self,
        db: Session,
        tenant_id: int,
        anomaly_type: str,
        user_id: Optional[int] = None,
        description: Optional[str] = None,
        severity: str = "medium",
        details: Optional[Dict] = None,
        related_login_ids: Optional[List[int]] = None,
    ) -> AnomalyEvent:
        event = AnomalyEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            type=anomaly_type,
            severity=severity,
            description=description,
            details=details,
            related_login_ids=related_login_ids,
            status="new",
        )
        db.add(event)
        db.flush()
        return event

    def query_login_logs(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        auth_method: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        ip_address: Optional[str] = None,
        anomaly_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        query = db.query(LoginLog)

        if tenant_id:
            query = query.filter(LoginLog.tenant_id == tenant_id)
        if user_id:
            query = query.filter(LoginLog.user_id == user_id)
        if status:
            query = query.filter(LoginLog.status == status)
        if auth_method:
            query = query.filter(LoginLog.auth_method == auth_method)
        if start_time:
            query = query.filter(LoginLog.created_at >= start_time)
        if end_time:
            query = query.filter(LoginLog.created_at <= end_time)
        if ip_address:
            query = query.filter(LoginLog.ip_address.like(f"%{ip_address}%"))
        if anomaly_only:
            query = query.filter(LoginLog.anomaly_detected == True)

        total = query.count()

        query = query.order_by(LoginLog.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        logs = query.all()
        return logs, total

    def query_anomaly_events(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        anomaly_type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        query = db.query(AnomalyEvent)

        if tenant_id:
            query = query.filter(AnomalyEvent.tenant_id == tenant_id)
        if user_id:
            query = query.filter(AnomalyEvent.user_id == user_id)
        if anomaly_type:
            query = query.filter(AnomalyEvent.type == anomaly_type)
        if severity:
            query = query.filter(AnomalyEvent.severity == severity)
        if status:
            query = query.filter(AnomalyEvent.status == status)
        if start_time:
            query = query.filter(AnomalyEvent.created_at >= start_time)
        if end_time:
            query = query.filter(AnomalyEvent.created_at <= end_time)

        total = query.count()
        query = query.order_by(AnomalyEvent.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        events = query.all()
        return events, total


_audit_logger_instance: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AuditLogger()
    return _audit_logger_instance
