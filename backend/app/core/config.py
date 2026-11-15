"""Typed environment-based application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path

BACKEND_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = "NITC CCC Terminal Booking Tracker API"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = ""
    jwt_secret_key: str = Field(default="development-only-change-me", min_length=24)
    access_token_minutes: int = 30
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = ""
    bootstrap_faculty_username: str = ""
    bootstrap_faculty_display_name: str = "CCC Faculty"
    bootstrap_faculty_password: str = ""
    frontend_origin: str = "http://localhost:5173"
    campus_timezone: str = "Asia/Kolkata"
    booking_slot_minutes: int = 30

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
