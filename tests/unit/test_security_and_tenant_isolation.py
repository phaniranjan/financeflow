"""Unit tests for security, API key authentication, and tenant isolation (Cycle 7.3)."""

import uuid

import pytest
from fastapi import HTTPException, status

from financeflow.api.dependencies.auth import (
    get_authenticated_business,
    verify_api_key,
)
from financeflow.core.config import Settings


class TestSecurityUnit:
    """Unit tests for API key verification and tenant isolation rules."""

    @pytest.mark.unit
    def test_verify_api_key_valid(self) -> None:
        """Verify valid API key passes authentication."""
        settings = Settings(api_key="valid-secret-key", api_key_required=True)
        # Should not raise exception
        result = verify_api_key(api_key="valid-secret-key", settings=settings)
        assert result == "valid-secret-key"

    @pytest.mark.unit
    def test_verify_api_key_invalid_raises_401(self) -> None:
        """Verify invalid API key raises 401 Unauthorized."""
        settings = Settings(api_key="valid-secret-key", api_key_required=True)
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(api_key="wrong-key", settings=settings)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid or missing API Key" in exc_info.value.detail

    @pytest.mark.unit
    def test_verify_api_key_missing_when_required_raises_401(self) -> None:
        """Verify missing API key raises 401 Unauthorized when required."""
        settings = Settings(api_key="valid-secret-key", api_key_required=True)
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(api_key=None, settings=settings)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.unit
    def test_verify_api_key_allowed_when_not_required(self) -> None:
        """Verify missing API key is allowed when api_key_required=False."""
        settings = Settings(api_key="valid-secret-key", api_key_required=False)
        result = verify_api_key(api_key=None, settings=settings)
        assert result is None

    @pytest.mark.unit
    def test_verify_api_key_invalid_when_not_required_raises_401(self) -> None:
        """Verify bad API key raises 401 even when api_key_required=False."""
        settings = Settings(api_key="valid-secret-key", api_key_required=False)
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(api_key="wrong-key", settings=settings)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.unit
    def test_get_authenticated_business_tenant_isolation(self) -> None:
        """Verify tenant header parsing and isolation validation."""
        tenant_id = uuid.uuid4()

        # Valid business UUID header
        resolved = get_authenticated_business(x_business_id=str(tenant_id))
        assert resolved == tenant_id

        # Missing header returns None (unscoped / internal service mode)
        assert get_authenticated_business(x_business_id=None) is None

        # Malformed UUID header raises 400 Bad Request
        with pytest.raises(HTTPException) as exc_info:
            get_authenticated_business(x_business_id="not-a-uuid")
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid X-Business-Id tenant header" in exc_info.value.detail
