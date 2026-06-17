from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import webauthn_router, voice_router, auth_router, admin_router
from app import models

models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="WebAuthn & Voiceprint Authentication System (Enterprise)",
    description="A passwordless authentication system using WebAuthn and voiceprint recognition with multi-tenant support",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(webauthn_router.router)
app.include_router(voice_router.router)
app.include_router(admin_router.router)


@app.on_event("startup")
async def startup_event():
    from app.services.health_service import get_service_health_manager
    from app.services.reconciliation_service import get_reconciliation_worker
    from app.services.model_manager import get_model_manager
    from app.services.audit_service import get_audit_logger
    from app.services.anomaly_service import get_anomaly_detector

    _ = get_service_health_manager()
    _ = get_reconciliation_worker()
    _ = get_model_manager()
    _ = get_audit_logger()
    _ = get_anomaly_detector()

    print("All enterprise services initialized")


@app.get("/")
def root():
    return {
        "message": "WebAuthn & Voiceprint Authentication API",
        "version": "2.0.0",
        "edition": "Enterprise",
        "features": [
            "Multi-tenant support",
            "Per-tenant voiceprint models",
            "Anomaly detection",
            "Audit logging",
            "Circuit breaker fallback",
            "Async reconciliation",
        ],
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    from app.services.health_service import get_service_health_manager
    health_mgr = get_service_health_manager()

    return {
        "status": "healthy",
        "version": "2.0.0",
        "services": health_mgr.get_service_status(),
    }
