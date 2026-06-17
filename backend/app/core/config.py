from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:password@localhost:5432/webauthn_voiceprint"
    secret_key: str = "your-secret-key-here"
    access_token_expire_minutes: int = 30

    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "VoiceAuth"
    webauthn_origin: str = "http://localhost:5173"

    mfcc_n_mfcc: int = 40
    voiceprint_similarity_threshold: float = 0.85

    class Config:
        env_file = ".env"


settings = Settings()
