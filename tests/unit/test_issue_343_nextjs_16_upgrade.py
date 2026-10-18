"""Contract tests for issue #343 — coordinated Next.js 16 + React 19 upgrade.

The dashboard-package assertions went with apps/dashboard (deleted in fast-track
P53, C1); the CI-merge-gate and handoff records remain.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDOFF = REPO_ROOT / "docs/handoffs/nextjs-16-coordinated-upgrade.md"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/pr.yml"


def test_issue_343_pr_ci_includes_frontend_and_status_check_jobs():
    """PR CI workflow defines the live frontend jobs and status-check for merge gate."""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "demo-frontend:" in workflow
    assert "landing-frontend:" in workflow
    assert "status-check:" in workflow


def test_issue_343_handoff_documents_superseded_dependabot_prs():
    """Handoff lists Dependabot PRs superseded by the coordinated upgrade."""
    text = HANDOFF.read_text(encoding="utf-8")
    for pr in (322, 325, 327, 332, 338, 339):
        assert f"#{pr}" in text or f"PR #{pr}" in text
