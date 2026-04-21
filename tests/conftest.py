"""Shared pytest fixtures for samanage-mcp tests."""

from __future__ import annotations

import pytest

from samanage_mcp.client import reset_client
from samanage_mcp.config import settings


@pytest.fixture(autouse=True)
def _isolated_client() -> None:
    """Reset the shared module-level client + dry-run flag before each test."""
    settings.samanage_dry_run = False
    settings.samanage_default_requester = None
    reset_client(base_url="https://api.samanage.com", api_token="test-token")
    yield
