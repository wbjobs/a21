from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float, JSON, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base
import enum


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    TRIAL = "trial"


class UserRole(str, enum.Enum):
    USER = "user"
    TENANT_ADMIN = "tenant_admin"
    SYSTEM_ADMIN = "system_admin"


class AuthMethod(str, enum.Enum):
    WEBAUTHN = "webauthn"
    VOICEPRINT = "voiceprint"
    FALLBACK_WEBAUTHN = "fallback_webauthn"
    TEMPORARY_TOKEN = "temporary_token"


class LoginStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    FALLBACK = "fallback"
    PENDING_REVIEW = "pending_review"


class AnomalyType(str, enum.Enum):
    MULTI_LOCATION_LOGIN = "multi_location_login"
    HIGH_FREQUENCY_ATTEMPTS = "high_frequency_attempts"
    VOICEPRINT_REUSE = "voiceprint_reuse"
    UNUSUAL_DEVICE = "unusual_device"
    UNUSUAL_TIME = "unusual_time"
    CROSS_TENANT_MATCH = "cross_tenant_match"
    ABNORMAL_SIMILARITY = "abnormal_similarity"


class ReconciliationStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CONFLICT = "conflict"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    domain = Column(String(100), unique=True, nullable=False)
    language = Column(String(10), default="zh-CN")
    accent_region = Column(String(50), default="default")
    status = Column(String(20), default=TenantStatus.ACTIVE)
    model_path = Column(String(500))
    voiceprint_threshold = Column(Float, default=0.70)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    login_logs = relationship("LoginLog", back_populates="tenant", cascade="all, delete-orphan")
    anomalies = relationship("AnomalyEvent", back_populates="tenant", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tenants_domain", "domain"),
        Index("ix_tenants_status", "status"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(50), nullable=False)
    email = Column(String(100), nullable=False)
    display_name = Column(String(100))
    role = Column(String(20), default=UserRole.USER)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True))
    last_login_ip = Column(String(50))
    last_login_location = Column(String(100))

    tenant = relationship("Tenant", back_populates="users")
    credentials = relationship("WebAuthnCredential", back_populates="user", cascade="all, delete-orphan")
    voiceprints = relationship("VoicePrint", back_populates="user", cascade="all, delete-orphan")
    login_logs = relationship("LoginLog", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_users_tenant_username", "tenant_id", "username", unique=True),
        Index("ix_users_tenant_email", "tenant_id", "email", unique=True),
    )


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id = Column(String(500), unique=True, nullable=False, index=True)
    public_key = Column(String(1000), nullable=False)
    sign_count = Column(Integer, default=0)
    device_name = Column(String(100))
    device_fingerprint = Column(String(200))
    transports = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="credentials")


class VoicePrint(Base):
    __tablename__ = "voiceprints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_vector = Column(Vector(200), nullable=False)
    sample_name = Column(String(100))
    source_mic_fingerprint = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="voiceprints")

    __table_args__ = (
        Index("ix_voiceprints_tenant_user", "tenant_id", "user_id"),
    )


class LoginLog(Base):
    __tablename__ = "login_logs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(50))
    auth_method = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False)
    ip_address = Column(String(50))
    user_agent = Column(String(500))
    location = Column(String(100))
    device_fingerprint = Column(String(200))
    similarity_score = Column(Float)
    anomaly_detected = Column(Boolean, default=False)
    fallback_triggered = Column(Boolean, default=False)
    fallback_reason = Column(String(200))
    verification_details = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    tenant = relationship("Tenant", back_populates="login_logs")
    user = relationship("User", back_populates="login_logs")

    __table_args__ = (
        Index("ix_login_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_login_logs_status_created", "status", "created_at"),
    )


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), default="medium")
    description = Column(Text)
    details = Column(JSON)
    related_login_ids = Column(JSON)
    status = Column(String(20), default="new")
    reviewed_by = Column(Integer)
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    tenant = relationship("Tenant", back_populates="anomalies")

    __table_args__ = (
        Index("ix_anomalies_tenant_type_created", "tenant_id", "type", "created_at"),
    )


class FallbackCache(Base):
    __tablename__ = "fallback_caches"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    cache_token = Column(String(200), unique=True, nullable=False, index=True)
    original_auth_method = Column(String(30))
    fallback_method = Column(String(30), default="webauthn")
    ip_address = Column(String(50))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_fallback_expires", "expires_at"),
    )


class ReconciliationLog(Base):
    __tablename__ = "reconciliation_logs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    cache_token = Column(String(200), index=True)
    original_login_id = Column(Integer)
    voice_verification_status = Column(String(20))
    voice_similarity = Column(Float)
    status = Column(String(20), default=ReconciliationStatus.PENDING)
    conflict_details = Column(JSON)
    reconciled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ServiceHealth(Base):
    __tablename__ = "service_health"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String(50), unique=True, nullable=False)
    is_healthy = Column(Boolean, default=True)
    last_check = Column(DateTime(timezone=True), server_default=func.now())
    last_failure = Column(DateTime(timezone=True))
    failure_count = Column(Integer, default=0)
    status_message = Column(String(500))
    metrics = Column(JSON)
