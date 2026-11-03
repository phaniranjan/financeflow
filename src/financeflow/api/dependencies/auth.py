"""Authentication and tenant isolation dependencies."""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from financeflow.core.config import Settings, get_settings

api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthenticatedTenant(BaseModel):
    """Authenticated tenant identity bound to the validated API credentials."""

    client_id: str
    business_id: uuid.UUID
    is_admin: bool = False


def resolve_tenant_from_api_key(
    api_key: str,
    settings: Settings,
) -> tuple[uuid.UUID | None, bool, bool]:
    """Resolve tenant business UUID and admin flag from API key.

    Returns:
        tuple of (business_id, is_admin, is_valid_key)
    """
    # 1. Configured api_keys map
    if api_key in settings.api_keys:
        target = settings.api_keys[api_key]
        if target == "admin":
            return None, True, True
        if target in ("none", "unassigned", ""):
            return None, False, True  # Valid key, but no tenant identity
        try:
            return uuid.UUID(target), False, True
        except (ValueError, TypeError):
            return None, False, True

    # 2. Dynamic test/dev keys of form 'test-key-<uuid>' or 'sk_test_<uuid>'
    if settings.environment in ("test", "testing", "development"):
        for prefix in ("test-key-", "sk_test_", "sk_test-"):
            if api_key.startswith(prefix):
                candidate = api_key[len(prefix) :]
                try:
                    return uuid.UUID(candidate), False, True
                except (ValueError, TypeError):
                    return None, False, False

    return None, False, False


def get_current_tenant(
    api_key: str | None = Security(api_key_header_scheme),
    x_business_id: Annotated[str | None, Header(alias="X-Business-Id")] = None,
    settings: Settings = Depends(get_settings),
) -> AuthenticatedTenant:
    """Authenticate incoming request and enforce strict tenant binding."""
    if not settings.api_key_required:
        # If explicitly disabled in local dev, allow request with optional tenant header
        if x_business_id:
            try:
                b_id = uuid.UUID(x_business_id)
                return AuthenticatedTenant(client_id="dev-bypass", business_id=b_id, is_admin=False)
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid X-Business-Id tenant header: must be a valid UUID",
                ) from exc
        # Default placeholder for unauthenticated dev mode
        return AuthenticatedTenant(
            client_id="dev-bypass",
            business_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            is_admin=True,
        )

    # Authentication is mandatory
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    bound_business_id, is_admin, is_valid_key = resolve_tenant_from_api_key(api_key, settings)

    if not is_valid_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if bound_business_id is None and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Valid API key is not associated with any tenant identity",
        )

    # Validate X-Business-Id header if provided
    if x_business_id is not None:
        try:
            header_business_id = uuid.UUID(x_business_id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Business-Id tenant header: must be a valid UUID",
            ) from exc

        if bound_business_id is not None and header_business_id != bound_business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: API key is not authorized for the specified business tenant",
            )

        resolved_business_id = header_business_id
    else:
        if bound_business_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Business-Id header is required for admin credentials",
            )
        resolved_business_id = bound_business_id

    return AuthenticatedTenant(
        client_id=api_key,
        business_id=resolved_business_id,
        is_admin=is_admin,
    )


def get_authenticated_business(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
) -> uuid.UUID:
    """Extract authenticated business UUID from the validated tenant."""
    return tenant.business_id
