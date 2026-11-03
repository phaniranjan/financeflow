import json
from decimal import Decimal
from functools import lru_cache
from typing import Self

from pydantic import Field, field_validator, model_validator
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

    # Authentication & Multi-Tenancy (Cycle 7 Hardening)
    api_key_required: bool = True
    api_keys: dict[str, str] = Field(default_factory=dict)
    api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, v: object) -> dict[str, str]:
        """Parse API key mappings from JSON string, comma-separated string, or dictionary."""
        if isinstance(v, str):
            v_strip = v.strip()
            if not v_strip:
                return {}
            if v_strip.startswith("{"):
                try:
                    parsed = json.loads(v_strip)
                    if isinstance(parsed, dict):
                        return {str(k): str(val) for k, val in parsed.items()}
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON string for api_keys: {exc}") from exc
            result: dict[str, str] = {}
            for pair in v_strip.split(","):
                if ":" in pair:
                    k, val = pair.split(":", 1)
                    result[k.strip()] = val.strip()
            return result
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        return {}

    @model_validator(mode="after")
    def validate_api_keys_configured(self) -> Self:
        """Fail startup if authentication is required but no API keys or secrets are configured."""
        if self.api_key and not self.api_keys:
            self.api_keys[self.api_key] = "admin"

        if (
            self.api_key_required
            and not self.api_keys
            and self.environment not in ("test", "testing")
        ):
            raise ValueError(
                "Application configuration error: api_key_required is True, but "
                "no API keys or tenant key mappings (api_keys) are configured. "
                "Configure API_KEYS in the environment or secrets manager."
            )
        return self

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
