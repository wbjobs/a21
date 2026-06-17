from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import webauthn_router, voice_router, auth_router
from app import models

models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="WebAuthn & Voiceprint Authentication System",
    description="A passwordless authentication system using WebAuthn and voiceprint recognition",
    version="1.0.0",
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


@app.get("/")
def root():
    return {
        "message": "WebAuthn & Voiceprint Authentication API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
