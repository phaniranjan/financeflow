"""Authentication and tenant isolation dependencies."""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from financeflow.core.config import Settings, get_settings

api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    api_key: str | None = Security(api_key_header_scheme),
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Verify incoming X-API-Key header against application configuration."""
    if settings.api_key_required:
        if not api_key or api_key != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API Key",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        return api_key

    # When not strictly required globally, validate key if caller provided one
    if api_key is not None and api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


def get_authenticated_business(
    x_business_id: Annotated[str | None, Header(alias="X-Business-Id")] = None,
) -> uuid.UUID | None:
    """Extract and validate the active tenant business ID from X-Business-Id header."""
    if not x_business_id:
        return None

    try:
        return uuid.UUID(x_business_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Business-Id tenant header: must be a valid UUID",
        ) from exc
