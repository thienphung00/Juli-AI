"""#842 — the main domain serves Landing; the dashboard is retired from production.

Pins each acceptance criterion that is verifiable from the repo. The runtime half
(sign-in round trip, public serving) is verified live at rollout.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VHOST = REPO_ROOT / "infra" / "nginx" / "app-juli.com.conf"
DEPLOY = REPO_ROOT / "infra" / "scripts" / "deploy-release.sh"
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"
UPTIME = REPO_ROOT / ".github" / "workflows" / "uptime.yml"


def test_main_domain_upstream_is_landing() -> None:
    conf = VHOST.read_text(encoding="utf-8")
    assert "server 127.0.0.1:3007;" in conf, "app-juli.com must proxy to juli-landing"
    assert "127.0.0.1:3000" not in conf, "the retired dashboard must not be routed"


def test_no_new_tls_or_server_names_were_needed() -> None:
    """AC: no new DNS record or TLS certificate — the existing cert and names hold."""
    conf = VHOST.read_text(encoding="utf-8")
    assert "/etc/letsencrypt/live/app-juli.com/fullchain.pem" in conf
    assert "server_name app-juli.com www.app-juli.com;" in conf


def test_dashboard_is_never_deployed() -> None:
    source = "\n".join(
        line
        for line in DEPLOY.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "systemctl restart juli-web" not in source
    assert "build-frontend-review" not in source
    assert "apps/dashboard" not in source


def test_dashboard_keeps_ci_coverage() -> None:
    """AC: type-checking and tests still run in CI — development-only, not deleted."""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "apps/dashboard/**" in workflow


def test_uptime_monitoring_covers_landing_once_live() -> None:
    """AC: uptime covers the landing page. uptime.yml polls the main domain, so
    coverage transfers to Landing at the instant of cutover with no change."""
    workflow = UPTIME.read_text(encoding="utf-8")
    assert "https://app-juli.com/" in workflow
