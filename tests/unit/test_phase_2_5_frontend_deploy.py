"""Doc and script contract tests for Phase 2.5-review-b frontend deploy (Issue #257).

Issue #257 deploys the existing ``web/`` Next.js app behind ``https://app-juli.com/``
for TikTok reviewers. Live VPS steps stay HITL; this slice ships the runbook,
provision script, and build contract that make frontend deploy repeatable and
testable in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "infra/deploy"

FRONTEND_RUNBOOK_PATH = DEPLOY_DIR / "frontend-deploy-runbook.md"
PROVISION_FRONTEND_PATH = DEPLOY_DIR / "provision-frontend.sh"
BUILD_SCRIPT_PATH = DEPLOY_DIR / "build-frontend-review.sh"
SYSTEMD_FRONTEND_PATH = DEPLOY_DIR / "systemd/juli-web.service"
ENV_FRONTEND_PATH = DEPLOY_DIR / "env/web.env.example"
SMOKE_TEST_PATH = DEPLOY_DIR / "smoke-test.sh"
ISSUES_PATH = REPO_ROOT / "docs/features/app_review_deployment/issues.md"
PHASE_25_PATH = REPO_ROOT / "docs/phases/phase-2.5-deployment.md"

FRONTEND_PORT = "3000"
API_URL = "https://api.app-juli.com"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def frontend_runbook_text() -> str:
    return _read(FRONTEND_RUNBOOK_PATH)


# AC1: npm ci && npm run build documented with NEXT_PUBLIC_API_URL.
def test_frontend_runbook_documents_build_with_api_url(frontend_runbook_text: str):
    assert FRONTEND_RUNBOOK_PATH.is_file()
    assert "npm ci" in frontend_runbook_text
    assert "npm run build" in frontend_runbook_text
    assert f"NEXT_PUBLIC_API_URL={API_URL}" in frontend_runbook_text
    assert "build-frontend-review.sh" in frontend_runbook_text


# AC2: juli-web systemd serves production build on localhost:3000.
def test_systemd_unit_binds_frontend_to_loopback_port():
    unit = _read(SYSTEMD_FRONTEND_PATH)
    assert f"--port {FRONTEND_PORT}" in unit or f":{FRONTEND_PORT}" in unit
    assert "127.0.0.1" in unit
    assert "npm run start" in unit


def test_provision_script_installs_juli_web_and_runs_build():
    assert PROVISION_FRONTEND_PATH.is_file()
    script = _read(PROVISION_FRONTEND_PATH)
    assert "juli-web.service" in script
    assert "build-frontend-review.sh" in script
    assert "systemctl" in script
    assert FRONTEND_PORT in script or "juli-web" in script


# AC3: Public / and /login load without local setup (smoke + runbook).
def test_smoke_test_covers_frontend_root_and_login():
    script = _read(SMOKE_TEST_PATH)
    assert "app-juli.com" in script
    assert "/login" in script
    assert "frontend loads" in script.lower() or "frontend" in script.lower()


def test_frontend_runbook_documents_public_urls_and_smoke(frontend_runbook_text: str):
    assert "https://app-juli.com/" in frontend_runbook_text
    assert "/login" in frontend_runbook_text
    assert "smoke-test.sh" in frontend_runbook_text


# AC4: UI-only reviewer path documented as fallback.
def test_frontend_runbook_documents_ui_only_fallback(frontend_runbook_text: str):
    assert "NEXT_PUBLIC_UI_ONLY=1" in frontend_runbook_text
    lowered = frontend_runbook_text.lower()
    assert "demo" in lowered or "ui-only" in lowered or "ui only" in lowered
    assert "build-frontend-review.sh" in frontend_runbook_text


def test_build_script_enforces_ui_only_and_validates_chunks():
    assert BUILD_SCRIPT_PATH.is_file()
    script = _read(BUILD_SCRIPT_PATH)
    assert "NEXT_PUBLIC_UI_ONLY=1" in script
    assert "npm ci" in script
    assert "npm run build" in script
    assert "login" in script.lower()
    assert "home" in script.lower() or "app/page" in script


# AC5: Landing/demo deferred to Phase 3.
def test_frontend_runbook_defers_landing_and_demo(frontend_runbook_text: str):
    assert "Phase 3" in frontend_runbook_text
    lowered = frontend_runbook_text.lower()
    assert "landing" in lowered or "demo.app-juli.com" in lowered


def test_provision_script_is_executable_and_has_shebang():
    assert PROVISION_FRONTEND_PATH.stat().st_mode & 0o111
    assert _read(PROVISION_FRONTEND_PATH).startswith("#!/")


def test_provision_script_does_not_reference_forbidden_services():
    forbidden = {
        "redis": r"\bredis\b",
        "webhook": r"\bwebhook\b",
        "celery": r"\bcelery\b",
    }
    lowered = _read(PROVISION_FRONTEND_PATH).lower()
    problems = [
        label for label, pattern in forbidden.items() if re.search(pattern, lowered)
    ]
    assert not problems, f"provision script references out-of-scope: {problems}"


def test_env_example_sets_review_api_url_and_ui_only():
    env = _read(ENV_FRONTEND_PATH)
    assert f"NEXT_PUBLIC_API_URL={API_URL}" in env
    assert "NEXT_PUBLIC_UI_ONLY=1" in env


def test_issues_index_records_p2_5_ar_2a_slice():
    assert ISSUES_PATH.is_file()
    text = _read(ISSUES_PATH)
    assert "#257" in text or "257" in text
    assert "frontend-deploy-runbook" in text


def test_phase_doc_records_2_5_review_b_frontend_deploy_slice():
    text = _read(PHASE_25_PATH)
    assert "257" in text
    assert "frontend-deploy-runbook" in text
