from pydantic_settings import BaseSettings
from typing import Dict


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:password@localhost:5432/webauthn_voiceprint"
    secret_key: str = "your-secret-key-here"
    access_token_expire_minutes: int = 30

    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "VoiceAuth"
    webauthn_origin: str = "http://localhost:5173"

    mfcc_n_mfcc: int = 40
    voiceprint_similarity_threshold: float = 0.70

    use_dtw_alignment: bool = True
    dtw_window_size: int = 50

    use_siamese_model: bool = True
    siamese_embedding_dim: int = 128
    model_dir: str = "models"

    similarity_weights: Dict[str, float] = {
        "model": 0.5,
        "dtw": 0.3,
        "cosine": 0.2
    }

    feature_normalization: str = "cmvn_histogram"

    class Config:
        env_file = ".env"


settings = Settings()
