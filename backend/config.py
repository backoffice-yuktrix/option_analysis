"""Standalone config — reads from .env, no DB required."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Options Movement Analysis"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS origin for the Vite dev server
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # Where to persist credentials and result JSONs
    CONFIG_FILE: str = "upstox_config.txt"
    RESULTS_DIR: str = "results"


settings = Settings()
