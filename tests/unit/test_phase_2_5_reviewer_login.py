"""Doc contract tests for Phase 2.5-review-d reviewer login (Issue #260).

Issue #260 enables TikTok reviewers to log in without becoming production users.
Live Supabase/VPS steps stay HITL; this slice ships the runbook and CI contracts
that make the reviewer login path repeatable and testable without a live domain.

The dashboard-side assertions (LoginForm, build-frontend-review.sh) went with
apps/dashboard in fast-track P53 (C1); today's reviewer access lives in apps/demo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.phase_scaffold

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "infra/deploy"
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"

REVIEWER_LOGIN_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/reviewer-login-runbook.md"
FRONTEND_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/frontend-deploy-runbook.md"
SMOKE_TEST_PATH = SCRIPTS_DIR / "smoke-test.sh"
ISSUES_PATH = REPO_ROOT / "docs/product/features/app_review_deployment/issues.md"
PHASE_25_PATH = REPO_ROOT / "docs/product/phases/phase-2.5-deployment.md"

APP_URL = "https://app-juli.com"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def reviewer_runbook_text() -> str:
    return _read(REVIEWER_LOGIN_RUNBOOK_PATH)


# AC1: Supabase free-tier project documented when API OTP auth is used.
def test_reviewer_runbook_documents_supabase_free_tier_for_otp(reviewer_runbook_text: str):
    assert REVIEWER_LOGIN_RUNBOOK_PATH.is_file()
    lowered = reviewer_runbook_text.lower()
    assert "supabase" in lowered
    assert "free tier" in lowered or "free-tier" in lowered
    assert "otp" in lowered or "phone" in lowered
    assert "optional" in lowered or "only if" in lowered


# AC2: Site URL and redirect URLs for Supabase when OTP is used.
def test_reviewer_runbook_documents_supabase_site_and_redirect_urls(reviewer_runbook_text: str):
    assert "Site URL" in reviewer_runbook_text or "site url" in reviewer_runbook_text.lower()
    assert APP_URL in reviewer_runbook_text
    assert f"{APP_URL}/**" in reviewer_runbook_text or "redirect" in reviewer_runbook_text.lower()


# AC3: Reviewer credentials/instructions stored outside source control.
def test_reviewer_runbook_directs_credentials_outside_source_control(reviewer_runbook_text: str):
    lowered = reviewer_runbook_text.lower()
    assert "never commit" in lowered or "not in git" in lowered or "outside" in lowered
    assert "ops notes" in lowered or "secret manager" in lowered or "password manager" in lowered
    assert "handoff" in lowered or "template" in lowered


# AC4: UI-only path (NEXT_PUBLIC_UI_ONLY=1) is the default reviewer login.
def test_reviewer_runbook_documents_ui_only_as_default(reviewer_runbook_text: str):
    assert "NEXT_PUBLIC_UI_ONLY=1" in reviewer_runbook_text
    assert "build-frontend-review.sh" in reviewer_runbook_text
    assert "/login" in reviewer_runbook_text
    lowered = reviewer_runbook_text.lower()
    assert "demo" in lowered or "ui-only" in lowered or "ui only" in lowered


def test_smoke_test_probes_demo_login_markers():
    script = _read(SMOKE_TEST_PATH)
    assert "/login" in script
    assert "loginAsReviewer" in script or "Tiếp tục" in script or "Đăng nhập demo" in script


# AC5: No real seller business data required.
def test_reviewer_runbook_documents_no_real_seller_data(reviewer_runbook_text: str):
    lowered = reviewer_runbook_text.lower()
    assert "no real" in lowered or "mock" in lowered
    assert "production user" in lowered or "production users" in lowered


def test_reviewer_runbook_links_prerequisite_deploy_slices(reviewer_runbook_text: str):
    assert "257" in reviewer_runbook_text or "frontend-deploy-runbook" in reviewer_runbook_text
    assert "258" in reviewer_runbook_text or "backend-deploy-runbook" in reviewer_runbook_text


def test_reviewer_runbook_documents_smoke_verification(reviewer_runbook_text: str):
    assert "smoke-test.sh" in reviewer_runbook_text


def test_issues_index_records_p2_5_ar_4_reviewer_login_slice():
    text = _read(ISSUES_PATH)
    assert "#260" in text or "260" in text
    assert "reviewer-login-runbook" in text


def test_phase_doc_records_2_5_review_d_reviewer_login_slice():
    text = _read(PHASE_25_PATH)
    assert "260" in text
    assert "reviewer-login-runbook" in text


def test_reviewer_runbook_does_not_embed_functional_secrets(reviewer_runbook_text: str):
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
        if re.search(pattern, reviewer_runbook_text)
    ]
    assert not problems, f"runbook may contain secrets: {problems}"
