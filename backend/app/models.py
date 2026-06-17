from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    credentials = relationship("WebAuthnCredential", back_populates="user", cascade="all, delete-orphan")
    voiceprints = relationship("VoicePrint", back_populates="user", cascade="all, delete-orphan")


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id = Column(String(500), unique=True, nullable=False, index=True)
    public_key = Column(String(1000), nullable=False)
    sign_count = Column(Integer, default=0)
    device_name = Column(String(100))
    transports = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="credentials")


class VoicePrint(Base):
    __tablename__ = "voiceprints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feature_vector = Column(Vector(200), nullable=False)
    sample_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="voiceprints")
