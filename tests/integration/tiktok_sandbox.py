"""Shared helpers for TikTok sandbox integration tests (issue #366)."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Local dev: load repo-root .env (same pattern as juli_backend.core.config.runtime).
# Does not override vars already exported in the shell or CI.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

WEBHOOK_PATH = "/webhooks/tiktok"


def sandbox_app_key() -> str:
    return os.environ.get("TIKTOK_APP_KEY", "").strip()


def sandbox_app_secret() -> str:
    return os.environ.get("TIKTOK_APP_SECRET", "").strip()


def sandbox_auth_code() -> str:
    return os.environ.get("TIKTOK_SANDBOX_AUTH_CODE", "").strip()


def sandbox_refresh_token() -> str:
    return os.environ.get("TIKTOK_SANDBOX_REFRESH_TOKEN", "").strip()


def sandbox_credentials_configured() -> bool:
    return bool(sandbox_app_key() and sandbox_app_secret())


requires_sandbox_credentials = pytest.mark.skipif(
    not sandbox_credentials_configured(),
    reason="TikTok sandbox tests require TIKTOK_APP_KEY and TIKTOK_APP_SECRET",
)


requires_sandbox_auth_code = pytest.mark.skipif(
    not (sandbox_credentials_configured() and sandbox_auth_code()),
    reason="Requires TIKTOK_SANDBOX_AUTH_CODE (single-use; refresh in CI secrets)",
)


requires_sandbox_refresh_token = pytest.mark.skipif(
    not (sandbox_credentials_configured() and sandbox_refresh_token()),
    reason="Requires TIKTOK_SANDBOX_REFRESH_TOKEN",
)


def sign_webhook_body(app_key: str, app_secret: str, body: bytes) -> str:
    sign_string = f"{app_key}{WEBHOOK_PATH}{body.decode()}"
    return hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256,
    ).hexdigest()
