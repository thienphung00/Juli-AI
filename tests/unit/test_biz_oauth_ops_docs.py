"""Doc + smoke contract tests for Business OAuth ops wiring (Issue #492, BIZ-OAUTH-3).

Live portal registration and VPS secret values stay HITL; this slice keeps both
ADR-034 production redirect URLs, env/secret keys, and non-5xx smoke GETs
documented and regression-tested.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

APP_REVIEW_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/app-review-runbook.md"
SMOKE_CHECKLIST_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/smoke-checklist-runbook.md"
VPS_WIRING_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/vps-wiring-runbook.md"
API_ENV_EXAMPLE_PATH = REPO_ROOT / "infra/scripts/env/api.env.example"
SMOKE_TEST_SCRIPT_PATH = REPO_ROOT / "infra/scripts/smoke-test.sh"

ADVERTISER_URL = "https://api.app-juli.com/v1/auth/tiktok/business/callback"
ACCOUNT_HOLDER_URL = (
    "https://api.app-juli.com/v1/auth/tiktok/business/account-holder/callback"
)
ADVERTISER_PATH = "/v1/auth/tiktok/business/callback"
ACCOUNT_HOLDER_PATH = "/v1/auth/tiktok/business/account-holder/callback"

REQUIRED_ENV_KEYS = (
    "TIKTOK_BUSINESS_APP_ID",
    "TIKTOK_BUSINESS_APP_SECRET",
    "TIKTOK_BUSINESS_REDIRECT_URI",
    "TIKTOK_BUSINESS_ACCOUNT_HOLDER_REDIRECT_URI",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def app_review_text() -> str:
    return _read(APP_REVIEW_RUNBOOK_PATH)


@pytest.fixture
def smoke_checklist_text() -> str:
    return _read(SMOKE_CHECKLIST_RUNBOOK_PATH)


@pytest.fixture
def vps_wiring_text() -> str:
    return _read(VPS_WIRING_RUNBOOK_PATH)


@pytest.fixture
def api_env_example_text() -> str:
    return _read(API_ENV_EXAMPLE_PATH)


@pytest.fixture
def smoke_script_text() -> str:
    return _read(SMOKE_TEST_SCRIPT_PATH)


# AC1: Runbooks list both ADR-034 production URLs exactly.
def test_app_review_runbook_lists_both_business_redirect_urls(app_review_text: str):
    assert ADVERTISER_URL in app_review_text
    assert ACCOUNT_HOLDER_URL in app_review_text


def test_smoke_checklist_lists_both_business_redirect_urls(smoke_checklist_text: str):
    assert ADVERTISER_URL in smoke_checklist_text
    assert ACCOUNT_HOLDER_URL in smoke_checklist_text


def test_vps_wiring_runbook_lists_both_business_redirect_urls(vps_wiring_text: str):
    assert ADVERTISER_URL in vps_wiring_text
    assert ACCOUNT_HOLDER_URL in vps_wiring_text
    lowered = vps_wiring_text.lower()
    assert "5xx" in lowered


# AC2: Env var names and required VPS / Secrets Manager keys are documented.
def test_env_var_names_and_required_vps_secrets_manager_keys_are_documented(
    app_review_text: str,
):
    for key in REQUIRED_ENV_KEYS:
        assert key in app_review_text, f"app-review runbook must document {key}"
    assert "juli/api/production" in app_review_text
    assert "/etc/juli/api.env" in app_review_text


def test_api_env_example_documents_business_oauth_keys(api_env_example_text: str):
    for key in REQUIRED_ENV_KEYS:
        assert key in api_env_example_text, f"api.env.example must include {key}"
    assert ADVERTISER_URL in api_env_example_text
    assert ACCOUNT_HOLDER_URL in api_env_example_text


# AC3: Smoke checklist + script include GETs that must not 5xx for both paths.
def test_smoke_checklist_documents_non_5xx_gets_for_business_callbacks(
    smoke_checklist_text: str,
):
    lowered = smoke_checklist_text.lower()
    assert ADVERTISER_PATH in smoke_checklist_text
    assert ACCOUNT_HOLDER_PATH in smoke_checklist_text
    assert "5xx" in lowered
    assert "business" in lowered


def test_smoke_test_script_probes_both_business_callbacks(smoke_script_text: str):
    assert ADVERTISER_PATH in smoke_script_text
    assert ACCOUNT_HOLDER_PATH in smoke_script_text
    # Same non-5xx gate pattern as Shop OAuth.
    assert "-lt 500" in smoke_script_text


# AC4: Explicit note that renaming registered portal URIs is high-risk.
def test_app_review_warns_that_renaming_portal_uris_is_high_risk(app_review_text: str):
    lowered = app_review_text.lower()
    assert "renam" in lowered or "chang" in lowered
    assert "high-risk" in lowered or "high risk" in lowered or "break" in lowered
    assert "portal" in lowered or "registered" in lowered


def test_smoke_checklist_warns_that_renaming_portal_uris_is_high_risk(
    smoke_checklist_text: str,
):
    lowered = smoke_checklist_text.lower()
    assert "high-risk" in lowered or "high risk" in lowered
    assert "renam" in lowered or "portal" in lowered


def test_ops_runbooks_do_not_embed_functional_secrets(
    app_review_text: str,
    smoke_checklist_text: str,
    vps_wiring_text: str,
):
    # api.env.example is a placeholder template (REPLACE_* URIs) — scan runbooks only.
    combined = f"{app_review_text}\n{smoke_checklist_text}\n{vps_wiring_text}"
    secret_patterns = [
        r"postgresql://[^:]+:[^@\s]+@",
        r"eyJ[A-Za-z0-9_-]{20,}\.",
        r"sk_live_[A-Za-z0-9]+",
    ]
    problems = [
        label
        for label, pattern in zip(
            ("database_url", "jwt", "api_key"),
            secret_patterns,
            strict=True,
        )
        if re.search(pattern, combined)
    ]
    assert not problems, f"ops docs may contain secrets: {problems}"
