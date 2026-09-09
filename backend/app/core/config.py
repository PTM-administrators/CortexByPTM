"""
Variabili d'ambiente centralizzate dell'applicazione.
Carica i valori da backend/.env tramite pydantic-settings.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database (default SQLite per sviluppo locale)
    DATABASE_URL: str = "sqlite:///./cortex_enterprise.db"

    # Security / JWT
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # CORS
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # Integrazioni esterne (default di piattaforma)
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    """Ritorna un'istanza cachata delle impostazioni dell'applicazione."""
    return Settings()


settings = get_settings()
