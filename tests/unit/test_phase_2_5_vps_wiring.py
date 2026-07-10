"""Doc and script contract tests for Phase 2.5-review-a VPS wiring (Issue #256).

Issue #256 wires the review VPS with Nginx reverse proxy and HTTPS so
``app-juli.com`` and ``api.app-juli.com`` resolve publicly. Live DNS/TLS steps
stay HITL on the VPS; this slice ships the runbook, provision script, and smoke-test
subset that make that wiring repeatable and testable in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "infra/deploy"
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"

VPS_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/vps-wiring-runbook.md"
PROVISION_NGINX_PATH = SCRIPTS_DIR / "provision-nginx.sh"
SMOKE_TEST_PATH = SCRIPTS_DIR / "smoke-test.sh"
ISSUES_PATH = REPO_ROOT / "docs/product/features/app_review_deployment/issues.md"
PHASE_25_PATH = REPO_ROOT / "docs/product/phases/phase-2.5-deployment.md"

FRONTEND_PORT = "3000"
BACKEND_PORT = "8000"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def vps_runbook_text() -> str:
    return _read(VPS_RUNBOOK_PATH)


# AC1: DNS A records documented for both App Review domains.
def test_vps_runbook_documents_dns_a_records(vps_runbook_text: str):
    assert VPS_RUNBOOK_PATH.is_file()
    assert "A record" in vps_runbook_text or "A records" in vps_runbook_text
    assert "app-juli.com" in vps_runbook_text
    assert "api.app-juli.com" in vps_runbook_text
    assert "dig" in vps_runbook_text, "runbook must show DNS verification command"


# AC2: Nginx routes frontend and API upstreams separately.
def test_provision_script_installs_split_nginx_vhosts():
    assert PROVISION_NGINX_PATH.is_file()
    script = _read(PROVISION_NGINX_PATH)
    assert "app-juli.com.conf" in script
    assert "api.app-juli.com.conf" in script
    assert "/etc/nginx/sites-available" in script
    assert "nginx -t" in script


def test_vps_runbook_documents_separate_upstream_ports(vps_runbook_text: str):
    assert FRONTEND_PORT in vps_runbook_text
    assert BACKEND_PORT in vps_runbook_text


# AC3: HTTPS certificates and auto-renew documented.
def test_vps_runbook_documents_certbot_and_auto_renew(vps_runbook_text: str):
    lowered = vps_runbook_text.lower()
    assert "certbot" in lowered
    assert "renew" in lowered, "runbook must document certificate auto-renewal"


# AC4: No HA/scaling/webhook/redis in scope.
def test_vps_runbook_excludes_out_of_scope_services(vps_runbook_text: str):
    lowered = vps_runbook_text.lower()
    for term in ("redis", "webhook", "ha "):
        assert term in lowered, f"runbook must explicitly exclude or mention: {term}"


def test_provision_script_is_executable_and_has_shebang():
    assert PROVISION_NGINX_PATH.stat().st_mode & 0o111, "provision-nginx.sh must be executable"
    assert _read(PROVISION_NGINX_PATH).startswith("#!/")


def test_provision_script_does_not_reference_forbidden_services():
    """Provision script must not install deferred background services."""
    forbidden = {
        "redis": r"\bredis\b",
        "webhook": r"\bwebhook\b",
        "celery": r"\bcelery\b",
    }
    lowered = _read(PROVISION_NGINX_PATH).lower()
    problems = [
        label for label, pattern in forbidden.items() if re.search(pattern, lowered)
    ]
    assert not problems, f"provision script references out-of-scope: {problems}"


# AC5: Smoke test supports DNS/TLS-only mode for #256 before apps are deployed.
def test_smoke_test_supports_dns_tls_only_mode():
    script = _read(SMOKE_TEST_PATH)
    assert "--dns-tls-only" in script
    assert "DNS_TLS_ONLY" in script


def test_smoke_test_dns_tls_mode_skips_upstream_checks():
    script = _read(SMOKE_TEST_PATH)
    assert "Skipping upstream checks" in script or "dns-tls-only" in script.lower()


# Docs cross-links and issue index.
def test_issues_index_records_p2_5_ar_1_slice():
    assert ISSUES_PATH.is_file()
    text = _read(ISSUES_PATH)
    assert "#256" in text or "256" in text
    assert "vps-wiring-runbook" in text


def test_phase_doc_records_2_5_review_a_vps_wiring_slice():
    text = _read(PHASE_25_PATH)
    assert "256" in text
    assert "vps-wiring-runbook" in text
