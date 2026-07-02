"""Doc and config contract tests for Phase 2.5-d deploy configuration (Issue #253).

Issue #253 splits frontend and backend deploy configuration under ``infra/deploy/``
for the TikTok App Review deployment. This slice ships documentation and config
samples only — live VPS/DNS/TLS wiring stays HITL (Issue #256). These tests assert
the deliverables exist, keep frontend/backend independently restartable, avoid
committing secrets, and cover the required smoke-test surface.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "infra/deploy"

RUNBOOK_PATH = DEPLOY_DIR / "app-review-runbook.md"
NGINX_APP_PATH = DEPLOY_DIR / "nginx/app-juli.com.conf"
NGINX_API_PATH = DEPLOY_DIR / "nginx/api.app-juli.com.conf"
SYSTEMD_FRONTEND_PATH = DEPLOY_DIR / "systemd/juli-web.service"
SYSTEMD_BACKEND_PATH = DEPLOY_DIR / "systemd/juli-api.service"
ENV_FRONTEND_PATH = DEPLOY_DIR / "env/web.env.example"
ENV_BACKEND_PATH = DEPLOY_DIR / "env/api.env.example"
SMOKE_TEST_PATH = DEPLOY_DIR / "smoke-test.sh"
PHASE_25_PATH = REPO_ROOT / "docs/phases/phase-2.5-deployment.md"

# App Review upstream ports (frontend Next.js / backend FastAPI on the single VPS).
FRONTEND_PORT = "3000"
BACKEND_PORT = "8000"

# Secret-like tokens that must never appear as real values in committed config.
SECRET_ENV_KEYS = (
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWT_SECRET",
    "TIKTOK_APP_SECRET",
    "DATABASE_URL",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def runbook_text() -> str:
    return _read(RUNBOOK_PATH)


# AC1: Deploy topology documented under infra/deploy/ (VPS, Nginx, HTTPS, ports).
def test_runbook_documents_review_topology(runbook_text: str):
    assert RUNBOOK_PATH.is_file(), "infra/deploy/app-review-runbook.md is required"
    lowered = runbook_text.lower()
    for term in ("vps", "nginx", "https", "app-juli.com", "api.app-juli.com"):
        assert term in lowered, f"runbook must document: {term}"


def test_runbook_documents_single_monorepo_vps_layout(runbook_text: str):
    assert "Juli-AI-v2" in runbook_text
    assert "web/.env.production" in runbook_text
    assert FRONTEND_PORT in runbook_text, "frontend upstream port must be documented"
    assert BACKEND_PORT in runbook_text, "backend upstream port must be documented"


def test_nginx_configs_route_frontend_and_api_separately():
    for path in (NGINX_APP_PATH, NGINX_API_PATH):
        assert path.is_file(), f"missing nginx config: {path}"
    app_conf = _read(NGINX_APP_PATH)
    api_conf = _read(NGINX_API_PATH)
    assert "app-juli.com" in app_conf
    assert f"127.0.0.1:{FRONTEND_PORT}" in app_conf
    assert "api.app-juli.com" in api_conf
    assert f"127.0.0.1:{BACKEND_PORT}" in api_conf


def test_nginx_api_config_exposes_health_and_oauth_callback():
    api_conf = _read(NGINX_API_PATH)
    assert "/health" in api_conf, "API nginx config must reference /health"
    assert "/v1/auth/tiktok/callback" in api_conf, (
        "API nginx config must reference the TikTok OAuth callback path"
    )


def test_systemd_units_use_single_monorepo_checkout():
    """Backend and frontend systemd units share one Juli-AI-v2 repo on the VPS."""
    api_unit = _read(SYSTEMD_BACKEND_PATH)
    web_unit = _read(SYSTEMD_FRONTEND_PATH)
    assert "Juli-AI-v2" in api_unit
    assert "Juli-AI-v2/web" in web_unit
    assert "/root/Juli-AI-v2/.env" in api_unit
    assert "/root/Juli-AI-v2/web/.env.production" in web_unit


# AC2: Frontend and backend deploy steps separated and independently restartable.
def test_systemd_units_are_separate_and_restartable():
    for path in (SYSTEMD_FRONTEND_PATH, SYSTEMD_BACKEND_PATH):
        assert path.is_file(), f"missing systemd unit: {path}"
    frontend = _read(SYSTEMD_FRONTEND_PATH)
    backend = _read(SYSTEMD_BACKEND_PATH)
    # Independent restart: each unit defines its own Restart policy.
    assert "Restart=" in frontend
    assert "Restart=" in backend
    # Backend runs the FastAPI ASGI app; frontend runs the Next.js server.
    assert "api_gateway.api.main:app" in backend
    assert "next" in frontend.lower() or "npm" in frontend.lower()


def test_frontend_backend_deploy_steps_separated_and_independently_restartable(runbook_text: str):
    assert "juli-web" in runbook_text
    assert "juli-api" in runbook_text
    assert "systemctl restart juli-web" in runbook_text
    assert "systemctl restart juli-api" in runbook_text


# AC3: Env vars documented without committing secrets.
def test_env_examples_exist_and_are_placeholders_only():
    for path in (ENV_FRONTEND_PATH, ENV_BACKEND_PATH):
        assert path.is_file(), f"missing env example: {path}"

    api_env = _read(ENV_BACKEND_PATH)
    # Backend startup requires DATABASE_URL and CORS; document them.
    assert "DATABASE_URL=" in api_env
    assert "CORS_ALLOW_ORIGINS=" in api_env
    assert "PHONE_OTP_ENABLED=false" in api_env

    web_env = _read(ENV_FRONTEND_PATH)
    assert "NEXT_PUBLIC_API_URL=" in web_env
    assert "NEXT_PUBLIC_UI_ONLY=1" in web_env
    assert "Juli-AI-v2" in api_env
    assert "Juli-AI-v2/web" in web_env


def test_env_examples_do_not_contain_real_secrets():
    """Committed env templates must use placeholders, never real credential values."""
    problems: list[str] = []
    # A long hex/base64 token after a secret key indicates a committed secret.
    secret_value = re.compile(r"=([A-Za-z0-9+/]{20,}|[0-9a-f]{20,})\s*$")
    for path in (ENV_FRONTEND_PATH, ENV_BACKEND_PATH):
        for line in _read(path).splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].replace("export ", "").strip()
            if key not in SECRET_ENV_KEYS:
                continue
            if secret_value.search(stripped):
                problems.append(f"{path.name}: {key} looks like a committed secret")
    assert not problems, "; ".join(problems)


def test_runbook_directs_secrets_outside_source_control(runbook_text: str):
    lowered = runbook_text.lower()
    assert "secret" in lowered
    # Runbook must state secrets live outside git (env file on the VPS / secret manager).
    assert "outside" in lowered or "not commit" in lowered or "do not commit" in lowered


# AC4: Smoke test covers DNS, TLS, frontend, /health, OAuth callback.
def test_smoke_test_script_exists_and_is_executable():
    assert SMOKE_TEST_PATH.is_file(), "infra/deploy/smoke-test.sh is required"
    mode = SMOKE_TEST_PATH.stat().st_mode
    assert mode & 0o111, "smoke-test.sh must be executable"


def test_smoke_test_covers_required_surface():
    script = _read(SMOKE_TEST_PATH)
    assert script.startswith("#!/"), "smoke-test.sh must have a shebang"
    assert "dig" in script, "smoke test must check DNS"
    assert "curl" in script, "smoke test must probe HTTPS endpoints"
    assert "app-juli.com" in script, "smoke test must load the frontend"
    assert "/health" in script, "smoke test must probe backend health"
    assert "/v1/auth/tiktok/callback" in script, (
        "smoke test must probe the OAuth callback route"
    )
    assert "/login" in script, "smoke test must probe reviewer login"
    assert "UI-only" in script or "UI_ONLY" in script, (
        "smoke test must assert UI-only reviewer login"
    )


def test_smoke_test_confirms_no_production_data_required():
    script = _read(SMOKE_TEST_PATH).lower()
    assert "no production" in script or "review" in script


# AC5: CI documents validation commands; live domain wiring stays HITL.
def test_runbook_documents_ci_validation_and_hitl_boundary(runbook_text: str):
    lowered = runbook_text.lower()
    assert "smoke-test.sh" in runbook_text, "runbook must reference the smoke-test script"
    assert "hitl" in lowered or "manual" in lowered, (
        "runbook must mark live domain wiring as HITL/manual"
    )


def test_phase_doc_records_2_5_d_deploy_slice():
    text = _read(PHASE_25_PATH)
    assert "2.5-d" in text, "phase doc must name the 2.5-d deploy config slice"
    assert "infra/deploy" in text


# Scope guard: review deploy must not require deferred production services.
def test_deploy_config_excludes_out_of_scope_services():
    """App Review config must not wire deferred background services.

    Guards against Redis, Celery/queue workers, cron units, and webhook services
    being enabled in the review deploy. Uses word-boundary patterns so legitimate
    tokens (e.g. uvicorn ``--workers 1``) are not flagged.
    """
    # Match service references, not incidental flags like `--workers 1`.
    forbidden = {
        "redis": r"\bredis\b",
        "celery": r"\bcelery\b",
        "worker service": r"\bworker(s)?\.(service|target)\b|\bworker_service\b",
        "cron": r"\bcron(tab|\.service|\.timer)?\b",
        "webhook": r"\bwebhook\b",
    }
    problems: list[str] = []
    for path in (
        SYSTEMD_FRONTEND_PATH,
        SYSTEMD_BACKEND_PATH,
        NGINX_APP_PATH,
        NGINX_API_PATH,
    ):
        lowered = _read(path).lower()
        for label, pattern in forbidden.items():
            if re.search(pattern, lowered):
                problems.append(f"{path.name} references out-of-scope service: {label}")
    assert not problems, "; ".join(problems)
