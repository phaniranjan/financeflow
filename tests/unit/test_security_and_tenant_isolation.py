"""Unit tests for security, API key authentication, and tenant isolation (Cycle 7 Hardening)."""

import uuid

import pytest
from fastapi import HTTPException, status
from pydantic import ValidationError

from financeflow.api.dependencies.auth import (
    AuthenticatedTenant,
    get_authenticated_business,
    get_current_tenant,
)
from financeflow.core.config import Settings


class TestSecurityUnit:
    """Unit tests for tenant-bound API key verification and isolation rules."""

    @pytest.mark.unit
    def test_settings_startup_fails_if_no_api_keys_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify application fails startup if authentication is required but no keys configured."""
        monkeypatch.delenv("API_KEYS", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        with pytest.raises(ValidationError, match="no API keys or tenant key mappings"):
            Settings(
                api_key_required=True,
                api_keys={},
                environment="production",
            )

    @pytest.mark.unit
    def test_settings_startup_succeeds_with_configured_api_keys(self) -> None:
        """Verify settings initialize successfully when api_keys mapping is provided."""
        tenant_id = uuid.uuid4()
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_alpha_key": str(tenant_id)},
            environment="production",
        )
        assert settings.api_key_required is True
        assert "sk_live_alpha_key" in settings.api_keys

    @pytest.mark.unit
    def test_get_current_tenant_no_api_key_raises_401(self) -> None:
        """Verify missing API key raises 401 Unauthorized."""
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_valid": str(uuid.uuid4())},
            environment="production",
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(api_key=None, x_business_id=None, settings=settings)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid or missing API Key" in exc_info.value.detail

    @pytest.mark.unit
    def test_get_current_tenant_invalid_api_key_raises_401(self) -> None:
        """Verify unconfigured or invalid API key raises 401 Unauthorized."""
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_valid": str(uuid.uuid4())},
            environment="production",
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(
                api_key="sk_live_unknown_bad_key",
                x_business_id=None,
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.unit
    def test_get_current_tenant_valid_key_unassigned_tenant_raises_403(self) -> None:
        """Verify valid key with unassigned/empty tenant identity raises 403 Forbidden."""
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_unassigned": "unassigned"},
            environment="production",
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(
                api_key="sk_live_unassigned",
                x_business_id=None,
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "not associated with any tenant" in exc_info.value.detail

    @pytest.mark.unit
    def test_get_current_tenant_valid_key_no_header_derives_tenant(self) -> None:
        """Verify tenant is automatically derived from the API key when header is omitted."""
        tenant_a = uuid.uuid4()
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_tenant_a": str(tenant_a)},
            environment="production",
        )
        tenant = get_current_tenant(
            api_key="sk_live_tenant_a",
            x_business_id=None,
            settings=settings,
        )
        assert isinstance(tenant, AuthenticatedTenant)
        assert tenant.business_id == tenant_a
        assert tenant.client_id == "sk_live_tenant_a"

    @pytest.mark.unit
    def test_get_current_tenant_valid_key_matching_header_allowed(self) -> None:
        """Verify matching API key and X-Business-Id header is allowed."""
        tenant_a = uuid.uuid4()
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_tenant_a": str(tenant_a)},
            environment="production",
        )
        tenant = get_current_tenant(
            api_key="sk_live_tenant_a",
            x_business_id=str(tenant_a),
            settings=settings,
        )
        assert tenant.business_id == tenant_a

    @pytest.mark.unit
    def test_get_current_tenant_key_a_with_header_b_raises_403(self) -> None:
        """Verify Business A key cannot spoof Business B via X-Business-Id header."""
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_tenant_a": str(tenant_a)},
            environment="production",
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(
                api_key="sk_live_tenant_a",
                x_business_id=str(tenant_b),
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "not authorized for the specified business tenant" in exc_info.value.detail

    @pytest.mark.unit
    def test_get_current_tenant_malformed_header_raises_400(self) -> None:
        """Verify malformed non-UUID X-Business-Id header raises 400 Bad Request."""
        tenant_a = uuid.uuid4()
        settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_tenant_a": str(tenant_a)},
            environment="production",
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(
                api_key="sk_live_tenant_a",
                x_business_id="not-a-valid-uuid",
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.unit
    def test_get_authenticated_business_helper(self) -> None:
        """Verify get_authenticated_business extracts UUID from AuthenticatedTenant."""
        b_id = uuid.uuid4()
        tenant = AuthenticatedTenant(client_id="test", business_id=b_id, is_admin=False)
        assert get_authenticated_business(tenant) == b_id

    @pytest.mark.unit
    def test_admin_api_key_with_target_header(self) -> None:
        """Verify admin key requires and binds to X-Business-Id target."""
        target_b = uuid.uuid4()
        settings = Settings(
            api_key_required=True,
            api_keys={"admin_secret": "admin"},
            environment="production",
        )
        tenant = get_current_tenant(
            api_key="admin_secret",
            x_business_id=str(target_b),
            settings=settings,
        )
        assert tenant.is_admin is True
        assert tenant.business_id == target_b

    @pytest.mark.unit
    def test_admin_api_key_without_header_raises_400(self) -> None:
        """Verify admin key without X-Business-Id target is rejected with 400."""
        settings = Settings(
            api_key_required=True,
            api_keys={"admin_secret": "admin"},
            environment="production",
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(
                api_key="admin_secret",
                x_business_id=None,
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "X-Business-Id header is required for admin credentials" in exc_info.value.detail

    @pytest.mark.unit
    def test_unauthenticated_dev_bypass_mode(self) -> None:
        """Verify behavior when api_key_required is False in local dev."""
        settings = Settings(
            api_key_required=False,
            api_keys={},
            environment="development",
        )
        # Default placeholder when no header
        tenant_default = get_current_tenant(api_key=None, x_business_id=None, settings=settings)
        assert tenant_default.is_admin is True

        # Header specified
        target = uuid.uuid4()
        tenant_header = get_current_tenant(
            api_key=None, x_business_id=str(target), settings=settings
        )
        assert tenant_header.business_id == target
        assert tenant_header.is_admin is False

        # Malformed header raises 400
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(api_key=None, x_business_id="invalid-uuid", settings=settings)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.unit
    def test_config_parsing_string_and_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify Settings parses JSON string and comma-separated string formats."""
        monkeypatch.delenv("API_KEYS", raising=False)
        t1 = str(uuid.uuid4())
        t2 = str(uuid.uuid4())
        # JSON format
        s1 = Settings(api_keys=f'{{"k1": "{t1}", "k2": "{t2}"}}', environment="test")
        assert s1.api_keys == {"k1": t1, "k2": t2}

        # Comma-separated format
        s2 = Settings(api_keys=f"k1:{t1}, k2:{t2}", environment="test")
        assert s2.api_keys == {"k1": t1, "k2": t2}

        # Non-string, non-dict fallback
        s_other = Settings(api_keys=123, environment="test")
        assert s_other.api_keys == {}

        # Empty string
        s3 = Settings(api_keys="", environment="test")
        assert s3.api_keys == {}

        # Invalid JSON
        with pytest.raises(ValidationError):
            Settings(api_keys="{invalid_json", environment="test")

        # Legacy api_key fallback
        s4 = Settings(api_key="legacy_secret", api_keys={}, environment="test")
        assert s4.api_keys.get("legacy_secret") == "admin"

    @pytest.mark.unit
    def test_dynamic_test_key_malformed_uuid_returns_401(self) -> None:
        """Verify test-key- with non-UUID suffix returns 401."""
        settings = Settings(api_key_required=True, api_keys={}, environment="test")
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(api_key="test-key-not-a-uuid", settings=settings)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.unit
    def test_configured_key_non_uuid_target_returns_403(self) -> None:
        """Verify key mapped to invalid non-UUID string returns 403."""
        settings = Settings(
            api_key_required=True,
            api_keys={"some_key": "not_admin_and_not_uuid"},
            environment="production",
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_tenant(api_key="some_key", settings=settings)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.unit
    def test_invoices_endpoint_rejects_mismatched_payload_business(self) -> None:
        """Verify create_invoice endpoint rejects business_id differing from tenant."""
        from datetime import date
        from decimal import Decimal
        from unittest.mock import MagicMock

        from financeflow.api.v1.endpoints.invoices import create_invoice
        from financeflow.schemas.invoice import InvoiceCreate

        tenant_b = uuid.uuid4()
        tenant = AuthenticatedTenant(client_id="key", business_id=tenant_b, is_admin=False)
        payload = InvoiceCreate(
            business_id=uuid.uuid4(),
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("1000.00"),
            currency="USD",
            issue_date=date(2026, 1, 1),
            due_date=date(2026, 2, 1),
        )
        with pytest.raises(HTTPException) as exc_info:
            create_invoice(payload=payload, service=MagicMock(), tenant=tenant)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.unit
    def test_financing_endpoint_rejects_cross_tenant_approve_and_reject(self) -> None:
        """Verify approve and reject endpoints reject cross-tenant operations."""
        from unittest.mock import MagicMock

        from financeflow.api.v1.endpoints.financing import (
            approve_financing_application,
            reject_financing_application,
        )

        owner_id = uuid.uuid4()
        other_tenant = AuthenticatedTenant(
            client_id="key", business_id=uuid.uuid4(), is_admin=False
        )
        mock_service = MagicMock()
        mock_app = MagicMock()
        mock_app.business_id = owner_id
        mock_service.get_application.return_value = mock_app

        app_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc1:
            approve_financing_application(
                application_id=app_id, service=mock_service, tenant=other_tenant
            )
        assert exc1.value.status_code == status.HTTP_403_FORBIDDEN

        with pytest.raises(HTTPException) as exc2:
            reject_financing_application(
                application_id=app_id, service=mock_service, tenant=other_tenant
            )
        assert exc2.value.status_code == status.HTTP_403_FORBIDDEN
