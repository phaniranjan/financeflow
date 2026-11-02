from decimal import Decimal

import pytest
from pydantic import ValidationError

from financeflow.core.config import Settings, get_settings


class TestSettingsConfiguration:
    """Unit tests for environment-based configuration and validation."""

    @pytest.mark.unit
    def test_default_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify default configuration values."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("APP_PORT", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        settings = Settings()
        assert settings.environment == "development"
        assert settings.log_level == "INFO"
        assert settings.app_port == 8000
        assert settings.default_currency == "USD"
        assert settings.default_advance_rate == Decimal("0.8000")
        assert settings.default_fee_percentage == Decimal("0.0300")
        assert "postgresql+psycopg://" in str(settings.database_url)

    @pytest.mark.unit
    def test_settings_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify environment variables override defaults."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("APP_PORT", "9000")
        monkeypatch.setenv("DEFAULT_CURRENCY", "EUR")
        monkeypatch.setenv("DEFAULT_ADVANCE_RATE", "0.7500")

        settings = Settings()
        assert settings.environment == "production"
        assert settings.log_level == "DEBUG"
        assert settings.app_port == 9000
        assert settings.default_currency == "EUR"
        assert settings.default_advance_rate == Decimal("0.7500")

    @pytest.mark.unit
    def test_database_url_requires_psycopg_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify non-psycopg database driver schemes are rejected."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db")
        with pytest.raises(
            ValidationError, match="database_url must use the 'postgresql\\+psycopg' driver"
        ):
            Settings()

    @pytest.mark.unit
    def test_cached_get_settings(self) -> None:
        """Verify get_settings returns a cached instance."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
