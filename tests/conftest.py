"""Global pytest configuration and environment setup."""

import os
from collections.abc import Generator

import pytest

# Ensure test environment is active before application modules are imported
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("API_KEY_REQUIRED", "true")
os.environ.setdefault(
    "API_KEYS",
    '{"test_default_key": "00000000-0000-0000-0000-000000000000"}',
)

from financeflow.core.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Generator[None, None, None]:
    """Clear LRU cache of get_settings between test runs to prevent test pollution."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
