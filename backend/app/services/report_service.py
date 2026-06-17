import time
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models import (
    Tenant, User, LoginLog, LoginStatus, AuthMethod,
    AnomalyEvent, AnomalyType, WebAuthnCredential, VoicePrint,
    ServiceHealth, ReconciliationLog, ReconciliationStatus
)


class ReportService:
    def get_tenant_summary(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        days: int = 7,
    ) -> Dict:
        query = db.query(Tenant)
        if tenant_id:
            query = query.filter(Tenant.id == tenant_id)
        tenants = query.all()

        cutoff = datetime.utcnow() - timedelta(days=days)

        result = []
        for tenant in tenants:
            user_count = db.query(User).filter(User.tenant_id == tenant.id).count()
            device_count = db.query(WebAuthnCredential).join(User).filter(
                User.tenant_id == tenant.id
            ).count()
            voiceprint_count = db.query(VoicePrint).filter(
                VoicePrint.tenant_id == tenant.id
            ).count()

            login_query = db.query(LoginLog).filter(
                LoginLog.tenant_id == tenant.id,
                LoginLog.created_at >= cutoff
            )
            total_logins = login_query.count()
            success_logins = login_query.filter(
                LoginLog.status == LoginStatus.SUCCESS
            ).count()
            failed_logins = login_query.filter(
                LoginLog.status == LoginStatus.FAILED
            ).count()
            fallback_logins = login_query.filter(
                LoginLog.status == LoginStatus.FALLBACK
            ).count()

            anomaly_count = db.query(AnomalyEvent).filter(
                AnomalyEvent.tenant_id == tenant.id,
                AnomalyEvent.created_at >= cutoff
            ).count()

            result.append({
                'tenant_id': tenant.id,
                'tenant_name': tenant.name,
                'domain': tenant.domain,
                'language': tenant.language,
                'status': tenant.status,
                'user_count': user_count,
                'device_count': device_count,
                'voiceprint_count': voiceprint_count,
                'period_days': days,
                'login_stats': {
                    'total': total_logins,
                    'success': success_logins,
                    'failed': failed_logins,
                    'fallback': fallback_logins,
                    'success_rate': round(
                        success_logins / total_logins, 4
                    ) if total_logins > 0 else 0,
                },
                'anomaly_count': anomaly_count,
            })

        return {
            'period_days': days,
            'tenants': result,
            'total_tenants': len(tenants),
        }

    def get_login_statistics(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        granularity: str = "day",
        days: int = 30,
    ) -> Dict:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = db.query(LoginLog).filter(LoginLog.created_at >= cutoff)

        if tenant_id:
            query = query.filter(LoginLog.tenant_id == tenant_id)
        if user_id:
            query = query.filter(LoginLog.user_id == user_id)

        logs = query.order_by(LoginLog.created_at.asc()).all()

        by_method = defaultdict(int)
        by_status = defaultdict(int)
        by_time = defaultdict(lambda: defaultdict(int))

        for log in logs:
            by_method[log.auth_method] += 1
            by_status[log.status] += 1

            if granularity == "hour":
                bucket = log.created_at.strftime("%Y-%m-%d %H:00")
            else:
                bucket = log.created_at.strftime("%Y-%m-%d")

            by_time[bucket]['total'] += 1
            if log.status == LoginStatus.SUCCESS:
                by_time[bucket]['success'] += 1
            else:
                by_time[bucket]['failed'] += 1

            if log.fallback_triggered:
                by_time[bucket]['fallback'] += 1
            if log.anomaly_detected:
                by_time[bucket]['anomaly'] += 1

        time_series = []
        for bucket in sorted(by_time.keys()):
            data = by_time[bucket]
            time_series.append({
                'period': bucket,
                'total': data['total'],
                'success': data.get('success', 0),
                'failed': data.get('failed', 0),
                'fallback': data.get('fallback', 0),
                'anomaly': data.get('anomaly', 0),
                'success_rate': round(
                    data.get('success', 0) / data['total'], 4
                ) if data['total'] > 0 else 0,
            })

        return {
            'granularity': granularity,
            'period_days': days,
            'by_method': dict(by_method),
            'by_status': dict(by_status),
            'time_series': time_series,
        }

    def get_anomaly_report(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        days: int = 30,
        min_severity: Optional[str] = None,
    ) -> Dict:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = db.query(AnomalyEvent).filter(AnomalyEvent.created_at >= cutoff)

        if tenant_id:
            query = query.filter(AnomalyEvent.tenant_id == tenant_id)
        if min_severity:
            severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            if min_severity in severity_order:
                min_level = severity_order[min_severity]
                all_events = query.all()
                events = [
                    e for e in all_events
                    if severity_order.get(e.severity, 0) >= min_level
                ]
            else:
                events = query.all()
        else:
            events = query.all()

        by_type = defaultdict(int)
        by_severity = defaultdict(int)
        by_status = defaultdict(int)
        by_tenant = defaultdict(int)
        by_day = defaultdict(int)

        for e in events:
            by_type[e.type] += 1
            by_severity[e.severity] += 1
            by_status[e.status] += 1
            by_tenant[e.tenant_id] += 1
            bucket = e.created_at.strftime("%Y-%m-%d")
            by_day[bucket] += 1

        high_risk_users = []
        user_anomaly_counts = defaultdict(int)
        for e in events:
            if e.user_id:
                user_anomaly_counts[(e.tenant_id, e.user_id)] += 1

        for (tid, uid), count in sorted(
            user_anomaly_counts.items(), key=lambda x: -x[1]
        )[:20]:
            user = db.query(User).filter(User.id == uid).first()
            high_risk_users.append({
                'tenant_id': tid,
                'user_id': uid,
                'username': user.username if user else None,
                'anomaly_count': count,
            })

        return {
            'period_days': days,
            'total_anomalies': len(events),
            'by_type': dict(by_type),
            'by_severity': dict(by_severity),
            'by_status': dict(by_status),
            'by_tenant': {
                f"tenant_{tid}": cnt for tid, cnt in by_tenant.items()
            },
            'daily_series': [
                {'date': day, 'count': cnt}
                for day, cnt in sorted(by_day.items())
            ],
            'high_risk_users': high_risk_users,
        }

    def get_service_health_report(self, db: Session) -> Dict:
        services = db.query(ServiceHealth).all()

        from app.services.health_service import get_service_health_manager
        from app.services.reconciliation_service import get_reconciliation_worker

        health_mgr = get_service_health_manager()
        recon_worker = get_reconciliation_worker()

        recon_stats = recon_worker.get_stats()

        service_map = {}
        for s in services:
            service_map[s.service_name] = {
                'is_healthy': s.is_healthy,
                'last_check': s.last_check.isoformat() if s.last_check else None,
                'last_failure': s.last_failure.isoformat() if s.last_failure else None,
                'failure_count': s.failure_count,
                'status_message': s.status_message,
                'metrics': s.metrics or {},
            }

        return {
            'services': service_map,
            'realtime': health_mgr.get_service_status(),
            'reconciliation': recon_stats,
        }

    def get_tenant_health_score(
        self,
        db: Session,
        tenant_id: int,
        days: int = 7,
    ) -> Dict:
        cutoff = datetime.utcnow() - timedelta(days=days)

        total_logins = db.query(LoginLog).filter(
            LoginLog.tenant_id == tenant_id,
            LoginLog.created_at >= cutoff
        ).count()

        if total_logins == 0:
            return {
                'tenant_id': tenant_id,
                'overall_score': 100,
                'factors': {},
                'period_days': days,
            }

        success_count = db.query(LoginLog).filter(
            LoginLog.tenant_id == tenant_id,
            LoginLog.created_at >= cutoff,
            LoginLog.status == LoginStatus.SUCCESS
        ).count()

        fallback_count = db.query(LoginLog).filter(
            LoginLog.tenant_id == tenant_id,
            LoginLog.created_at >= cutoff,
            LoginLog.fallback_triggered == True
        ).count()

        anomaly_count = db.query(AnomalyEvent).filter(
            AnomalyEvent.tenant_id == tenant_id,
            AnomalyEvent.created_at >= cutoff
        ).count()

        success_rate = success_count / total_logins
        fallback_rate = fallback_count / total_logins
        anomaly_per_1000 = (anomaly_count / total_logins) * 1000

        success_score = min(100, success_rate * 100)
        fallback_penalty = min(40, fallback_rate * 200)
        anomaly_penalty = min(30, anomaly_per_1000 * 5)

        overall_score = max(0, int(round(
            success_score - fallback_penalty - anomaly_penalty
        )))

        if overall_score >= 85:
            grade = "A"
        elif overall_score >= 70:
            grade = "B"
        elif overall_score >= 55:
            grade = "C"
        elif overall_score >= 40:
            grade = "D"
        else:
            grade = "F"

        return {
            'tenant_id': tenant_id,
            'overall_score': overall_score,
            'grade': grade,
            'period_days': days,
            'factors': {
                'success_rate': round(success_rate, 4),
                'fallback_rate': round(fallback_rate, 4),
                'anomaly_per_1000_logins': round(anomaly_per_1000, 2),
            },
            'component_scores': {
                'success_score': round(success_score, 1),
                'fallback_penalty': round(fallback_penalty, 1),
                'anomaly_penalty': round(anomaly_penalty, 1),
            },
            'raw_stats': {
                'total_logins': total_logins,
                'success_count': success_count,
                'fallback_count': fallback_count,
                'anomaly_count': anomaly_count,
            },
        }

    def get_multi_location_login_report(
        self,
        db: Session,
        tenant_id: Optional[int] = None,
        days: int = 7,
    ) -> List[Dict]:
        cutoff = datetime.utcnow() - timedelta(days=days)

        events = db.query(AnomalyEvent).filter(
            AnomalyEvent.type == AnomalyType.MULTI_LOCATION_LOGIN,
            AnomalyEvent.created_at >= cutoff
        )
        if tenant_id:
            events = events.filter(AnomalyEvent.tenant_id == tenant_id)

        result = []
        for event in events.order_by(AnomalyEvent.created_at.desc()).all():
            user = db.query(User).filter(User.id == event.user_id).first() if event.user_id else None
            result.append({
                'id': event.id,
                'tenant_id': event.tenant_id,
                'user_id': event.user_id,
                'username': user.username if user else None,
                'severity': event.severity,
                'created_at': event.created_at.isoformat(),
                'details': event.details,
                'status': event.status,
            })

        return result


_report_service_instance: Optional[ReportService] = None


def get_report_service() -> ReportService:
    global _report_service_instance
    if _report_service_instance is None:
        _report_service_instance = ReportService()
    return _report_service_instance
