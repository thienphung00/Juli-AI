"""Shared pytest fixtures for the KiotViet test suite."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from src.integrations.kiotviet.auth import TokenManager
from src.integrations.kiotviet.client import KiotVietClient


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject dummy credentials so TokenManager / KiotVietClient never touch real env."""
    monkeypatch.setenv("KIOTVIET_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("KIOTVIET_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("KIOTVIET_RETAILER", "test-store")


@pytest.fixture()
def token_manager() -> TokenManager:
    return TokenManager(
        client_id="test-client-id",
        client_secret="test-client-secret",
        token_url="https://id.kiotviet.vn/connect/token",
    )


@pytest.fixture()
def mock_token_manager() -> TokenManager:
    """TokenManager whose access_token is pre-set (no HTTP needed)."""
    tm = MagicMock(spec=TokenManager)
    tm.access_token = "mock-token"
    return tm


@pytest.fixture()
def client(mock_token_manager: TokenManager) -> KiotVietClient:
    return KiotVietClient(
        token_manager=mock_token_manager,
        retailer="test-store",
        base_url="https://public.kiotapi.com",
    )
