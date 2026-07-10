"""Doc and script contract tests for Phase 2.5-review-c backend deploy (Issue #258).

Issue #258 deploys the existing FastAPI app behind ``https://api.app-juli.com/``
for TikTok App Review. Live VPS steps stay HITL; this slice ships the runbook,
provision script, and env contract that make backend deploy repeatable and testable
in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "infra/deploy"
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
SYSTEMD_DIR = REPO_ROOT / "infra/systemd"

BACKEND_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/backend-deploy-runbook.md"
PROVISION_BACKEND_PATH = SCRIPTS_DIR / "provision-backend.sh"
SYSTEMD_BACKEND_PATH = SYSTEMD_DIR / "juli-api.service"
ENV_BACKEND_PATH = SCRIPTS_DIR / "env/api.env.example"
SMOKE_TEST_PATH = SCRIPTS_DIR / "smoke-test.sh"
ISSUES_PATH = REPO_ROOT / "docs/product/features/app_review_deployment/issues.md"
PHASE_25_PATH = REPO_ROOT / "docs/product/phases/phase-2.5-deployment.md"

BACKEND_PORT = "8000"
API_DOMAIN = "api.app-juli.com"
CORS_ORIGIN = "https://app-juli.com"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def backend_runbook_text() -> str:
    return _read(BACKEND_RUNBOOK_PATH)


# AC1: https://api.app-juli.com/health returns 2xx JSON (runbook + smoke).
def test_backend_runbook_documents_health_returns_2xx_json(backend_runbook_text: str):
    assert BACKEND_RUNBOOK_PATH.is_file()
    assert f"https://{API_DOMAIN}/health" in backend_runbook_text
    assert "/health" in backend_runbook_text
    assert "2xx" in backend_runbook_text.lower() or "json" in backend_runbook_text.lower()


def test_smoke_test_covers_backend_health():
    script = _read(SMOKE_TEST_PATH)
    assert "/health" in script
    assert API_DOMAIN in script


# AC2: API starts with required env vars only (api.env.example + runbook).
def test_backend_runbook_documents_required_env_vars(backend_runbook_text: str):
    assert "DATABASE_URL" in backend_runbook_text
    assert "CORS_ALLOW_ORIGINS" in backend_runbook_text
    assert f"CORS_ALLOW_ORIGINS={CORS_ORIGIN}" in backend_runbook_text
    assert "api.env.example" in backend_runbook_text


def test_env_example_sets_review_cors_and_database():
    env = _read(ENV_BACKEND_PATH)
    assert "DATABASE_URL=" in env
    assert f"CORS_ALLOW_ORIGINS={CORS_ORIGIN}" in env


# AC3: juli-api systemd uses single uvicorn worker on localhost:8000.
def test_systemd_unit_binds_backend_to_loopback_single_worker():
    unit = _read(SYSTEMD_BACKEND_PATH)
    assert f"--port {BACKEND_PORT}" in unit or f":{BACKEND_PORT}" in unit
    assert "127.0.0.1" in unit
    assert "--workers 1" in unit
    assert "uvicorn" in unit


def test_provision_script_installs_juli_api_and_pip_deps():
    assert PROVISION_BACKEND_PATH.is_file()
    script = _read(PROVISION_BACKEND_PATH)
    assert "juli-api.service" in script
    assert "requirements.txt" in script
    assert "pip" in script and "install" in script
    assert "systemctl" in script
    assert BACKEND_PORT in script or "juli-api" in script


# AC4: Redis, cron, workers, ML, polling, webhooks not required.
def test_backend_runbook_excludes_redis_cron_workers_webhooks_not_required(backend_runbook_text: str):
    lowered = backend_runbook_text.lower()
    for term in ("redis", "cron", "worker", "ml", "polling", "webhook"):
        assert term in lowered, f"runbook must document {term} as out of scope"


def test_provision_script_does_not_reference_forbidden_services():
    forbidden = {
        "redis": r"\bredis\b",
        "webhook": r"\bwebhook\b",
        "celery": r"\bcelery\b",
    }
    lowered = _read(PROVISION_BACKEND_PATH).lower()
    problems = [
        label for label, pattern in forbidden.items() if re.search(pattern, lowered)
    ]
    assert not problems, f"provision script references out-of-scope: {problems}"


# AC5: Alembic migrations skipped unless OAuth/login persistence requires schema.
def test_backend_runbook_documents_alembic_migrations_skipped_unless_oauth(backend_runbook_text: str):
    assert "Alembic" in backend_runbook_text or "alembic" in backend_runbook_text
    lowered = backend_runbook_text.lower()
    assert "skip" in lowered
    assert "oauth" in lowered or "login" in lowered


def test_provision_script_is_executable_and_has_shebang():
    assert PROVISION_BACKEND_PATH.stat().st_mode & 0o111
    assert _read(PROVISION_BACKEND_PATH).startswith("#!/")


def test_backend_runbook_documents_provision_and_smoke(backend_runbook_text: str):
    assert "provision-backend.sh" in backend_runbook_text
    assert "smoke-test.sh" in backend_runbook_text


def test_issues_index_records_p2_5_ar_2b_slice():
    assert ISSUES_PATH.is_file()
    text = _read(ISSUES_PATH)
    assert "#258" in text or "258" in text
    assert "backend-deploy-runbook" in text


def test_phase_doc_records_2_5_review_c_backend_deploy_slice():
    text = _read(PHASE_25_PATH)
    assert "258" in text
    assert "backend-deploy-runbook" in text
