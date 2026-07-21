"""Doc and script contract tests for Phase 2.6 Demo deploy runbook (Issue #406).

Issue #406 deploys ``apps/demo`` behind ``https://demo.app-juli.com/`` as an
independent systemd/Nginx surface. Live VPS steps stay HITL (decision 4A); this
slice ships the runbook, provision/build/deploy/rollback scripts, and contract tests
that make Demo deploy repeatable and verifiable in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
NGINX_DIR = REPO_ROOT / "infra/nginx"
SYSTEMD_DIR = REPO_ROOT / "infra/systemd"

DEMO_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/demo-deploy-runbook.md"
PROVISION_DEMO_PATH = SCRIPTS_DIR / "provision-demo.sh"
PROVISION_NGINX_PATH = SCRIPTS_DIR / "provision-nginx.sh"
BUILD_DEMO_PATH = SCRIPTS_DIR / "build-demo.sh"
DEPLOY_DEMO_PATH = SCRIPTS_DIR / "deploy-demo-release.sh"
ROLLBACK_DEMO_PATH = SCRIPTS_DIR / "rollback-demo-release.sh"
SYSTEMD_DEMO_PATH = SYSTEMD_DIR / "juli-demo.service"
ENV_DEMO_PATH = SCRIPTS_DIR / "env/demo.env.example"
SMOKE_DEMO_PATH = SCRIPTS_DIR / "smoke-test-demo.sh"
PHASE_26_PRD_PATH = REPO_ROOT / "docs/product/phases/phase-2.6/PRD.md"
DEPLOY_README_PATH = REPO_ROOT / "infra/deploy/README.md"

DEMO_DOMAIN = "demo.app-juli.com"
DEMO_PORT = "3001"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def demo_runbook_text() -> str:
    return _read(DEMO_RUNBOOK_PATH)


# AC1: pnpm build documented for apps/demo with mock-only runtime.
def test_demo_runbook_documents_build_without_api_credentials(demo_runbook_text: str):
    assert DEMO_RUNBOOK_PATH.is_file()
    assert "pnpm" in demo_runbook_text
    assert "apps/demo" in demo_runbook_text
    assert "build-demo.sh" in demo_runbook_text
    lowered = demo_runbook_text.lower()
    assert "mock" in lowered


def test_build_script_validates_decisions_route():
    assert BUILD_DEMO_PATH.is_file()
    script = _read(BUILD_DEMO_PATH)
    assert "pnpm" in script
    assert "apps/demo" in script
    assert "decisions" in script.lower()


# AC2: juli-demo systemd serves production build on localhost:3001.
def test_systemd_unit_binds_demo_to_loopback_port():
    unit = _read(SYSTEMD_DEMO_PATH)
    assert f"--port {DEMO_PORT}" in unit or f":{DEMO_PORT}" in unit
    assert "127.0.0.1" in unit
    assert "apps/demo" in unit or "@juli/demo" in unit


def test_provision_script_installs_juli_demo_and_runs_build():
    assert PROVISION_DEMO_PATH.is_file()
    script = _read(PROVISION_DEMO_PATH)
    assert "juli-demo.service" in script
    assert "build-demo.sh" in script
    assert "systemctl" in script
    assert DEMO_PORT in script or "juli-demo" in script


# AC3: Public HTTPS and /decisions documented with smoke verification.
def test_smoke_demo_covers_public_domain_and_decisions_route():
    script = _read(SMOKE_DEMO_PATH)
    assert DEMO_DOMAIN in script
    assert "/decisions" in script


def test_demo_runbook_documents_public_urls_and_smoke(demo_runbook_text: str):
    assert f"https://{DEMO_DOMAIN}/" in demo_runbook_text
    assert "/decisions" in demo_runbook_text
    assert "smoke-test-demo.sh" in demo_runbook_text


# AC4: Nginx provision script installs demo vhost alongside review vhosts.
def test_provision_nginx_installs_demo_vhost():
    script = _read(PROVISION_NGINX_PATH)
    assert "demo.app-juli.com.conf" in script
    assert "app-juli.com.conf" in script
    assert "api.app-juli.com.conf" in script


def test_demo_runbook_documents_nginx_vhost_path(demo_runbook_text: str):
    assert "demo.app-juli.com.conf" in demo_runbook_text


# AC5: Independent deploy/rollback scripts are executable with shebangs.
@pytest.mark.parametrize(
    "path",
    [
        PROVISION_DEMO_PATH,
        BUILD_DEMO_PATH,
        DEPLOY_DEMO_PATH,
        ROLLBACK_DEMO_PATH,
        SMOKE_DEMO_PATH,
    ],
)
def test_demo_scripts_are_executable_and_have_shebang(path: Path):
    assert path.is_file(), f"missing script: {path}"
    assert path.stat().st_mode & 0o111, f"{path.name} must be executable"
    assert _read(path).startswith("#!/")


def test_provision_demo_does_not_reference_forbidden_services():
    forbidden = {
        "redis": r"\bredis\b",
        "webhook": r"\bwebhook\b",
        "celery": r"\bcelery\b",
    }
    lowered = _read(PROVISION_DEMO_PATH).lower()
    problems = [
        label for label, pattern in forbidden.items() if re.search(pattern, lowered)
    ]
    assert not problems, f"provision script references out-of-scope: {problems}"


def test_env_demo_example_documents_mock_only_runtime():
    env = _read(ENV_DEMO_PATH)
    assert "apps/demo" in env
    assert "mock" in env.lower() or "Mock" in env


def test_prd_records_demo_public_deployment_target():
    text = _read(PHASE_26_PRD_PATH)
    assert DEMO_DOMAIN in text
    assert "apps/demo" in text


def test_deploy_readme_records_phase_2_6_demo_deploy_slice():
    text = _read(DEPLOY_README_PATH)
    assert "#406" in text or "406" in text
    assert "demo-deploy-runbook" in text
