import os
from sqlalchemy import text
from app.database import engine, Base, SessionLocal
from app.core.config import settings
from app.models import Tenant, User, UserRole, TenantStatus


def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully with pgvector extension!")

    db = SessionLocal()
    try:
        default_tenant = db.query(Tenant).filter(
            Tenant.name == settings.default_tenant_name
        ).first()

        if not default_tenant:
            default_tenant = Tenant(
                name=settings.default_tenant_name,
                domain=settings.default_tenant_domain,
                language=settings.default_tenant_language,
                status=TenantStatus.ACTIVE,
                voiceprint_threshold=settings.voiceprint_similarity_threshold,
                settings={
                    "anomaly_detection": True,
                    "fallback_mode": True,
                    "max_devices_per_user": 10,
                    "max_voiceprints_per_user": 5,
                }
            )
            db.add(default_tenant)
            db.commit()
            db.refresh(default_tenant)
            print(f"Default tenant created: {default_tenant.name} (ID: {default_tenant.id})")

            existing_admin = db.query(User).filter(
                User.tenant_id == default_tenant.id,
                User.username == "admin"
            ).first()

            if not existing_admin:
                from app.core.security import get_password_hash
                admin_user = User(
                    tenant_id=default_tenant.id,
                    username="admin",
                    email="admin@default.local",
                    display_name="System Administrator",
                    role=UserRole.SYSTEM_ADMIN,
                    is_active=True,
                )
                db.add(admin_user)
                db.commit()
                print(f"Default admin user created: admin / (no password, use WebAuthn)")

    except Exception as e:
        print(f"Error creating default data: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
