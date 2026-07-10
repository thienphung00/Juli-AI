"""Doc contract tests for Phase 2.5-review-f smoke checklist (Issue #261).

Issue #261 finalizes a repeatable smoke-test checklist proving App Review readiness.
Live VPS sign-off stays HITL; this slice ships the runbook, PRD/summary commands, and
CI contracts that keep CORS and the smoke surface documented and testable.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "infra/deploy"
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
FEATURE_DIR = REPO_ROOT / "docs/product/features/app_review_deployment"

SMOKE_CHECKLIST_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/smoke-checklist-runbook.md"
SMOKE_TEST_PATH = SCRIPTS_DIR / "smoke-test.sh"
ENV_BACKEND_PATH = SCRIPTS_DIR / "env/api.env.example"
PRD_PATH = FEATURE_DIR / "PRD.md"
SUMMARY_PATH = FEATURE_DIR / "summary.md"
ISSUES_PATH = FEATURE_DIR / "issues.md"
PHASE_25_PATH = REPO_ROOT / "docs/product/phases/phase-2.5-deployment.md"

CORS_ORIGIN = "https://app-juli.com"
APP_DOMAIN = "app-juli.com"
API_DOMAIN = "api.app-juli.com"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def smoke_checklist_text() -> str:
    return _read(SMOKE_CHECKLIST_RUNBOOK_PATH)


@pytest.fixture
def prd_text() -> str:
    return _read(PRD_PATH)


@pytest.fixture
def summary_text() -> str:
    return _read(SUMMARY_PATH)


# AC1: CORS_ALLOW_ORIGINS includes https://app-juli.com.
def test_cors_allow_origins_includes_review_frontend(smoke_checklist_text: str):
    env = _read(ENV_BACKEND_PATH)
    assert f"CORS_ALLOW_ORIGINS={CORS_ORIGIN}" in env
    assert CORS_ORIGIN in smoke_checklist_text
    assert "CORS_ALLOW_ORIGINS" in smoke_checklist_text


def test_smoke_test_probes_cors_preflight():
    script = _read(SMOKE_TEST_PATH)
    assert "access-control-allow-origin" in script.lower()
    assert APP_DOMAIN in script
    assert "CORS" in script or "cors" in script


# AC2: Checklist covers DNS, TLS, frontend load, /health, OAuth callback, reviewer login.
def test_smoke_checklist_runbook_exists(smoke_checklist_text: str):
    assert SMOKE_CHECKLIST_RUNBOOK_PATH.is_file()


def test_smoke_checklist_covers_required_surface(smoke_checklist_text: str):
    lowered = smoke_checklist_text.lower()
    for term in ("dns", "tls", "frontend", "/health", "oauth", "reviewer login", "cors"):
        assert term in lowered, f"checklist must cover: {term}"


def test_smoke_test_script_covers_required_surface():
    script = _read(SMOKE_TEST_PATH)
    assert "dig" in script
    assert "/health" in script
    assert "/v1/auth/tiktok/callback" in script
    assert "/login" in script
    assert APP_DOMAIN in script


def test_smoke_checklist_documents_smoke_test_command(smoke_checklist_text: str):
    assert "smoke-test.sh" in smoke_checklist_text
    assert APP_DOMAIN in smoke_checklist_text
    assert API_DOMAIN in smoke_checklist_text


# AC3: Checklist explicitly confirms no production users/traffic/persistent business data.
def test_smoke_checklist_confirms_review_only_scope(smoke_checklist_text: str):
    lowered = smoke_checklist_text.lower()
    assert "no production user" in lowered
    assert "no production traffic" in lowered
    assert "no persistent business data" in lowered or "persistent business data" in lowered


def test_smoke_test_script_confirms_review_only_scope():
    script = _read(SMOKE_TEST_PATH).lower()
    assert "no production" in script or "review-only" in script


# AC4: Commands documented in PRD.md and summary.md.
def test_prd_documents_smoke_commands(prd_text: str):
    assert PRD_PATH.is_file()
    assert "smoke-test.sh" in prd_text
    assert "test_phase_2_5_smoke_checklist" in prd_text
    assert CORS_ORIGIN in prd_text


def test_summary_documents_smoke_commands(summary_text: str):
    assert SUMMARY_PATH.is_file()
    assert "smoke-test.sh" in summary_text
    assert "test_phase_2_5_smoke_checklist" in summary_text
    assert CORS_ORIGIN in summary_text
    assert f"grep CORS_ALLOW_ORIGINS={CORS_ORIGIN}" in summary_text or CORS_ORIGIN in summary_text


def test_prd_and_summary_link_smoke_checklist_runbook(prd_text: str, summary_text: str):
    assert "smoke-checklist-runbook" in prd_text
    assert "smoke-checklist-runbook" in summary_text


def test_issues_index_records_p2_5_ar_5_smoke_checklist_slice():
    text = _read(ISSUES_PATH)
    assert "#261" in text or "261" in text
    assert "smoke-checklist-runbook" in text


def test_phase_doc_records_2_5_review_f_smoke_checklist_slice():
    text = _read(PHASE_25_PATH)
    assert "261" in text
    assert "smoke-checklist-runbook" in text


def test_smoke_checklist_runbook_does_not_embed_functional_secrets(smoke_checklist_text: str):
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
        if re.search(pattern, smoke_checklist_text)
    ]
    assert not problems, f"runbook may contain secrets: {problems}"
