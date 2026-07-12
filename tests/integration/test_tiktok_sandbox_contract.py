"""Contract checks for TikTok sandbox integration test wiring — Issue #366."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_DIR = REPO_ROOT / "tests" / "integration"
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"


def test_sandbox_oauth_and_webhook_modules_live_under_tests_integration():
    """New sandbox integration tests live under tests/integration/."""
    oauth = INTEGRATION_DIR / "test_tiktok_sandbox_oauth.py"
    webhook = INTEGRATION_DIR / "test_tiktok_sandbox_webhook.py"
    assert oauth.is_file(), f"missing {oauth}"
    assert webhook.is_file(), f"missing {webhook}"


def test_pr_workflow_configures_tiktok_ci_secrets_for_sandbox_tests():
    """CI secrets configured in GitHub Actions so sandbox tests run on PRs."""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    for secret in (
        "TIKTOK_APP_KEY",
        "TIKTOK_APP_SECRET",
        "TIKTOK_SANDBOX_AUTH_CODE",
        "TIKTOK_SANDBOX_REFRESH_TOKEN",
    ):
        assert secret in workflow, f"{secret} missing from pr.yml test job env"


def test_sandbox_helpers_skip_when_tiktok_app_key_and_app_secret_unset(monkeypatch):
    """Tests skip when TIKTOK_APP_KEY / TIKTOK_APP_SECRET are unset."""
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)

    from tests.integration import tiktok_sandbox

    assert tiktok_sandbox.sandbox_credentials_configured() is False


def test_no_secrets_committed_to_source_control_in_sandbox_files():
    """No secrets committed to source control in sandbox integration tests."""
    secret_literal = re.compile(
        r'(app_key|app_secret)\s*=\s*["\'][a-zA-Z0-9_\-]{8,}["\']',
        re.IGNORECASE,
    )
    for name in (
        "test_tiktok_sandbox_oauth.py",
        "test_tiktok_sandbox_webhook.py",
        "tiktok_sandbox.py",
    ):
        path = INTEGRATION_DIR / name
        text = path.read_text(encoding="utf-8")
        match = secret_literal.search(text)
        assert match is None, f"hardcoded credential literal in {path.name}: {match.group(0)!r}"
