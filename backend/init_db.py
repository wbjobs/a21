import os
from sqlalchemy import text
from app.database import engine, Base, SessionLocal
from app.core.config import settings


def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully with pgvector extension!")


if __name__ == "__main__":
    init_db()
