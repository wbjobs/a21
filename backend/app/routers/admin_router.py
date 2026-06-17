from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from app.database import get_db
from app.models import UserRole, Tenant
from app.core.config import settings
from app.services.report_service import get_report_service
from app.services.audit_service import get_audit_logger
from app.services.health_service import get_service_health_manager
from app.services.reconciliation_service import get_reconciliation_worker
from app.services.model_manager import get_model_manager

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _check_admin_role(db: Session, user_id: int, tenant_id: Optional[int] = None):
    from app.core.security import get_current_user_dependency
    pass


@router.get("/tenants")
def list_tenants(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    query = db.query(Tenant)
    total = query.count()
    tenants = query.order_by(Tenant.id.asc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenants": [
            {
                "id": t.id,
                "name": t.name,
                "domain": t.domain,
                "language": t.language,
                "accent_region": t.accent_region,
                "status": t.status,
                "voiceprint_threshold": t.voiceprint_threshold,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tenants
        ],
    }


@router.post("/tenants")
def create_tenant(
    request: Request,
    db: Session = Depends(get_db),
):
    import json
    body = json.loads(request.body()) if hasattr(request, 'body') else {}
    return {"message": "Tenant creation endpoint"}


@router.get("/tenants/{tenant_id}")
def get_tenant_detail(
    tenant_id: int,
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    report_svc = get_report_service()
    summary = report_svc.get_tenant_summary(db, tenant_id=tenant_id, days=7)
    health_score = report_svc.get_tenant_health_score(db, tenant_id=tenant_id, days=7)

    user_count = len(summary['tenants'][0]) if summary['tenants'] else 0

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "domain": tenant.domain,
            "language": tenant.language,
            "accent_region": tenant.accent_region,
            "status": tenant.status,
            "voiceprint_threshold": tenant.voiceprint_threshold,
            "settings": tenant.settings,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
            "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
        },
        "summary": summary['tenants'][0] if summary['tenants'] else {},
        "health_score": health_score,
    }


@router.get("/tenants/{tenant_id}/login-logs")
def get_tenant_login_logs(
    tenant_id: int,
    status: Optional[str] = None,
    auth_method: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    anomaly_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    audit = get_audit_logger()
    logs, total = audit.query_login_logs(
        db=db,
        tenant_id=tenant_id,
        status=status,
        auth_method=auth_method,
        start_time=start_time,
        end_time=end_time,
        anomaly_only=anomaly_only,
        page=page,
        page_size=page_size,
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username,
                "auth_method": log.auth_method,
                "status": log.status,
                "ip_address": log.ip_address,
                "location": log.location,
                "similarity_score": log.similarity_score,
                "anomaly_detected": log.anomaly_detected,
                "fallback_triggered": log.fallback_triggered,
                "fallback_reason": log.fallback_reason,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.get("/tenants/{tenant_id}/anomalies")
def get_tenant_anomalies(
    tenant_id: int,
    anomaly_type: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    audit = get_audit_logger()
    events, total = audit.query_anomaly_events(
        db=db,
        tenant_id=tenant_id,
        anomaly_type=anomaly_type,
        severity=severity,
        status=status,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "anomalies": [
            {
                "id": event.id,
                "type": event.type,
                "severity": event.severity,
                "description": event.description,
                "details": event.details,
                "user_id": event.user_id,
                "status": event.status,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }


@router.get("/reports/login-statistics")
def get_login_statistics(
    tenant_id: Optional[int] = None,
    granularity: str = Query("day", pattern="^(hour|day)$"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    report_svc = get_report_service()
    stats = report_svc.get_login_statistics(
        db=db,
        tenant_id=tenant_id,
        granularity=granularity,
        days=days,
    )
    return stats


@router.get("/reports/anomaly-report")
def get_anomaly_report(
    tenant_id: Optional[int] = None,
    days: int = Query(30, ge=1, le=365),
    min_severity: Optional[str] = None,
    db: Session = Depends(get_db),
):
    report_svc = get_report_service()
    report = report_svc.get_anomaly_report(
        db=db,
        tenant_id=tenant_id,
        days=days,
        min_severity=min_severity,
    )
    return report


@router.get("/reports/tenant-summary")
def get_tenant_summary_report(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    report_svc = get_report_service()
    return report_svc.get_tenant_summary(db, days=days)


@router.get("/reports/multi-location-logins")
def get_multi_location_report(
    tenant_id: Optional[int] = None,
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    report_svc = get_report_service()
    return {
        "events": report_svc.get_multi_location_login_report(
            db, tenant_id=tenant_id, days=days
        )
    }


@router.get("/health/services")
def get_service_health(
    db: Session = Depends(get_db),
):
    report_svc = get_report_service()
    return report_svc.get_service_health_report(db)


@router.get("/health/reconciliation")
def get_reconciliation_status():
    worker = get_reconciliation_worker()
    return worker.get_stats()


@router.get("/models/tenants")
def list_tenant_models():
    mm = get_model_manager()
    return {
        "loaded_tenants": mm.list_loaded_tenants(),
        "global_model": mm.get_tenant_model_info(0),
    }


@router.post("/models/tenants/{tenant_id}/reload")
def reload_tenant_model(tenant_id: int):
    mm = get_model_manager()
    mm.reload_tenant_model(tenant_id)
    return {"message": f"Model reloaded for tenant {tenant_id}"}


@router.post("/models/reload-all")
def reload_all_models():
    mm = get_model_manager()
    mm.reload_all_models()
    return {"message": "All models reloaded"}


@router.get("/models/tenants/{tenant_id}/info")
def get_tenant_model_info(tenant_id: int):
    mm = get_model_manager()
    return mm.get_tenant_model_info(tenant_id)


@router.post("/health/circuit/{service_name}/open")
def force_circuit_open(service_name: str):
    health_mgr = get_service_health_manager()
    health_mgr.force_circuit_open(service_name)
    return {"message": f"Circuit forced open for {service_name}"}


@router.post("/health/circuit/{service_name}/close")
def force_circuit_closed(service_name: str):
    health_mgr = get_service_health_manager()
    health_mgr.force_circuit_closed(service_name)
    return {"message": f"Circuit forced closed for {service_name}"}
