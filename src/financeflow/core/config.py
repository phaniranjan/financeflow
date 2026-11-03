from decimal import Decimal
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    environment: str = "development"
    log_level: str = "INFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str = (
        "postgresql+psycopg://financeflow_user:financeflow_secret@localhost:5432/financeflow_db"
    )

    disbursement_service_base_url: str = "http://localhost:8080"
    disbursement_service_api_key: str = "local_mock_disbursement_key"
    disbursement_timeout_seconds: float = 10.0

    default_advance_rate: Decimal = Decimal("0.8000")
    default_fee_percentage: Decimal = Decimal("0.0300")
    default_currency: str = "USD"

    api_key: str = "financeflow_secret_key"
    api_key_required: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url_driver(cls, v: str) -> str:
        """Enforce strict usage of the synchronous psycopg 3 driver."""
        if not v.startswith("postgresql+psycopg://"):
            raise ValueError(
                "database_url must use the 'postgresql+psycopg' driver for synchronous SQLAlchemy."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
