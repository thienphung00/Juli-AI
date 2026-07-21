"""Doc and config contract tests for Phase 2.6 Demo deploy configuration (Issue #406).

Issue #406 adds an independent Demo deployment for ``apps/demo`` at
``demo.app-juli.com``. This slice ships documentation, config samples, deploy/rollback
automation, and contract tests only — live VPS/DNS/TLS wiring stays HITL (decision 4A).
These tests assert the deliverables exist, keep Demo independently restartable from
``app-juli.com`` / ``api.app-juli.com``, avoid committing secrets, and cover mock-mode
runtime (no backend credentials).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
NGINX_DIR = REPO_ROOT / "infra/nginx"
SYSTEMD_DIR = REPO_ROOT / "infra/systemd"

RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/demo-deploy-runbook.md"
NGINX_DEMO_PATH = NGINX_DIR / "demo.app-juli.com.conf"
NGINX_APP_PATH = NGINX_DIR / "app-juli.com.conf"
NGINX_API_PATH = NGINX_DIR / "api.app-juli.com.conf"
SYSTEMD_DEMO_PATH = SYSTEMD_DIR / "juli-demo.service"
SYSTEMD_FRONTEND_PATH = SYSTEMD_DIR / "juli-web.service"
SYSTEMD_BACKEND_PATH = SYSTEMD_DIR / "juli-api.service"
ENV_DEMO_PATH = SCRIPTS_DIR / "env/demo.env.example"
BUILD_DEMO_PATH = SCRIPTS_DIR / "build-demo.sh"
DEPLOY_DEMO_PATH = SCRIPTS_DIR / "deploy-demo-release.sh"
ROLLBACK_DEMO_PATH = SCRIPTS_DIR / "rollback-demo-release.sh"
SMOKE_DEMO_PATH = SCRIPTS_DIR / "smoke-test-demo.sh"
DEPLOY_README_PATH = REPO_ROOT / "infra/deploy/README.md"

DEMO_DOMAIN = "demo.app-juli.com"
DEMO_PORT = "3001"
FRONTEND_PORT = "3000"
BACKEND_PORT = "8000"

SECRET_ENV_KEYS = (
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWT_SECRET",
    "TIKTOK_APP_SECRET",
    "TIKTOK_TOKEN_ENCRYPTION_KEY",
    "DATABASE_URL",
    "NEXT_PUBLIC_API_URL",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def runbook_text() -> str:
    return _read(RUNBOOK_PATH)


# AC1: Demo has its own systemd service/upstream and Nginx vhost.
def test_runbook_documents_demo_topology(runbook_text: str):
    assert RUNBOOK_PATH.is_file(), "docs/runbooks/demo-deploy-runbook.md is required"
    lowered = runbook_text.lower()
    for term in ("vps", "nginx", "https", DEMO_DOMAIN, "juli-demo"):
        assert term in lowered, f"runbook must document: {term}"


def test_nginx_demo_vhost_routes_to_independent_upstream():
    assert NGINX_DEMO_PATH.is_file(), f"missing nginx config: {NGINX_DEMO_PATH}"
    conf = _read(NGINX_DEMO_PATH)
    assert DEMO_DOMAIN in conf
    assert f"127.0.0.1:{DEMO_PORT}" in conf
    assert f"127.0.0.1:{FRONTEND_PORT}" not in conf, "demo vhost must not proxy to the App Review port"
    assert f"127.0.0.1:{BACKEND_PORT}" not in conf, "demo vhost must not proxy to the API port"


def test_app_and_api_nginx_configs_unchanged_for_demo_independence():
    """Demo slice must not alter app-juli.com or api.app-juli.com upstream ownership."""
    app_conf = _read(NGINX_APP_PATH)
    api_conf = _read(NGINX_API_PATH)
    assert "app-juli.com" in app_conf
    assert f"127.0.0.1:{FRONTEND_PORT}" in app_conf
    assert "api.app-juli.com" in api_conf
    assert f"127.0.0.1:{BACKEND_PORT}" in api_conf
    assert DEMO_DOMAIN not in app_conf
    assert DEMO_DOMAIN not in api_conf


def test_systemd_demo_unit_is_independent_service():
    assert SYSTEMD_DEMO_PATH.is_file(), f"missing systemd unit: {SYSTEMD_DEMO_PATH}"
    unit = _read(SYSTEMD_DEMO_PATH)
    assert "juli-demo" in unit or "Demo" in unit
    assert f"--port {DEMO_PORT}" in unit or f":{DEMO_PORT}" in unit
    assert "127.0.0.1" in unit
    assert "apps/demo" in unit
    assert "juli-api.service" not in unit
    assert "juli-web.service" not in unit


def test_systemd_demo_uses_demo_release_symlink():
    unit = _read(SYSTEMD_DEMO_PATH)
    assert "releases/demo-current" in unit


# AC2: Release automation builds apps/demo and restarts only Demo with local health check.
def test_deploy_demo_script_builds_and_restarts_demo_only():
    assert DEPLOY_DEMO_PATH.is_file()
    script = _read(DEPLOY_DEMO_PATH)
    assert "build-demo.sh" in script
    assert "apps/demo" in script
    assert "juli-demo" in script
    assert "systemctl restart juli-demo" in script
    assert "systemctl restart juli-api" not in script
    assert "systemctl restart juli-web" not in script
    assert f"127.0.0.1:{DEMO_PORT}" in script
    assert "demo-deploy-history.log" in script


def test_build_demo_script_targets_monorepo_demo_app():
    assert BUILD_DEMO_PATH.is_file()
    script = _read(BUILD_DEMO_PATH)
    assert "apps/demo" in script
    assert "pnpm" in script
    assert "decisions" in script.lower() or "/decisions" in script


def test_runbook_documents_independent_demo_restart(runbook_text: str):
    assert "systemctl restart juli-demo" in runbook_text
    assert "deploy-demo-release.sh" in runbook_text
    assert "systemctl restart juli-web" not in runbook_text
    assert "systemctl restart juli-api" not in runbook_text


# AC3: Rollback restores previous healthy Demo release independently.
def test_rollback_demo_script_restarts_demo_only():
    assert ROLLBACK_DEMO_PATH.is_file()
    script = _read(ROLLBACK_DEMO_PATH)
    assert "demo-deploy-history.log" in script
    assert "demo-current" in script
    assert "systemctl restart juli-demo" in script
    assert "systemctl restart juli-api" not in script
    assert "systemctl restart juli-web" not in script
    assert f"127.0.0.1:{DEMO_PORT}" in script


def test_runbook_documents_demo_rollback(runbook_text: str):
    assert "rollback-demo-release.sh" in runbook_text
    lowered = runbook_text.lower()
    assert "rollback" in lowered
    assert "without affecting app-juli.com" in lowered.replace("`", "")


# AC4: Nginx/DNS/TLS/provisioning documented without secrets.
def test_runbook_documents_dns_tls_and_provisioning_without_secrets(runbook_text: str):
    assert "A record" in runbook_text or "DNS" in runbook_text
    assert "certbot" in runbook_text.lower()
    assert "provision-demo.sh" in runbook_text
    lowered = runbook_text.lower()
    assert "secret" in lowered
    assert "do not commit" in lowered or "not commit" in lowered or "outside" in lowered


def test_env_demo_example_has_no_backend_credentials():
    assert ENV_DEMO_PATH.is_file()
    env = _read(ENV_DEMO_PATH)
    for key in SECRET_ENV_KEYS:
        assert f"{key}=" not in env, f"demo env must not require {key}"


def test_env_demo_example_do_not_contain_real_secrets():
    secret_value = re.compile(r"=([A-Za-z0-9+/]{20,}|[0-9a-f]{20,})\s*$")
    problems: list[str] = []
    for line in _read(ENV_DEMO_PATH).splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].replace("export ", "").strip()
        if key not in SECRET_ENV_KEYS:
            continue
        if secret_value.search(stripped):
            problems.append(f"{key} looks like a committed secret")
    assert not problems, "; ".join(problems)


# AC5: Smoke test covers Demo DNS/TLS/route surface.
def test_smoke_demo_script_exists_and_is_executable():
    assert SMOKE_DEMO_PATH.is_file()
    mode = SMOKE_DEMO_PATH.stat().st_mode
    assert mode & 0o111, "smoke-test-demo.sh must be executable"


def test_smoke_demo_covers_dns_tls_and_decisions_route():
    script = _read(SMOKE_DEMO_PATH)
    assert script.startswith("#!/")
    assert "dig" in script
    assert "curl" in script
    assert DEMO_DOMAIN in script
    assert "/decisions" in script


# AC6: CI validates production Demo build and deployment contracts.
def test_deploy_readme_documents_demo_ci_validation():
    text = _read(DEPLOY_README_PATH)
    assert DEMO_DOMAIN in text
    assert "test_phase_2_6_demo_deploy" in text


def test_runbook_documents_ci_validation_command(runbook_text: str):
    assert "test_phase_2_6_demo_deploy" in runbook_text


# AC7: Mock mode needs no backend credentials or API availability.
def test_build_demo_script_does_not_require_api_env():
    script = _read(BUILD_DEMO_PATH)
    assert "source " not in script and "EnvironmentFile" not in script
    assert "fetch-secrets.sh" not in script


def test_systemd_demo_does_not_fetch_backend_secrets():
    unit = _read(SYSTEMD_DEMO_PATH)
    assert "ExecStartPre=" not in unit
    assert "EnvironmentFile=/etc/juli/api.env" not in unit
    assert "EnvironmentFile=/etc/juli/web.env" not in unit


def test_runbook_documents_mock_mode_without_backend(runbook_text: str):
    lowered = runbook_text.lower()
    assert "mock" in lowered
    assert "backend" in lowered or "api" in lowered


# Scope guard: demo deploy must not wire deferred background services.
def test_demo_deploy_excludes_out_of_scope_services():
    forbidden = {
        "redis": r"\bredis\b",
        "celery": r"\bcelery\b",
        "webhook": r"\bwebhook\b",
    }
    problems: list[str] = []
    for path in (SYSTEMD_DEMO_PATH, NGINX_DEMO_PATH, DEPLOY_DEMO_PATH):
        lowered = _read(path).lower()
        for label, pattern in forbidden.items():
            if re.search(pattern, lowered):
                problems.append(f"{path.name} references out-of-scope service: {label}")
    assert not problems, "; ".join(problems)
