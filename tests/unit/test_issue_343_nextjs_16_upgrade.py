"""Contract tests for issue #343 — coordinated Next.js 16 + React 19 upgrade."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PKG = REPO_ROOT / "apps/dashboard/package.json"
DASHBOARD_MODULE = REPO_ROOT / "apps/dashboard/MODULE.md"
ESLINT_CONFIG = REPO_ROOT / "apps/dashboard/eslint.config.mjs"
LEGACY_ESLINTRC = REPO_ROOT / "apps/dashboard/.eslintrc.json"
HANDOFF = REPO_ROOT / "docs/handoffs/nextjs-16-coordinated-upgrade.md"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/pr.yml"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_issue_343_coupled_packages_bumped_atomically():
    """Single PR bumps next, react, eslint-config-next, and jest together."""
    pkg = _read_json(DASHBOARD_PKG)
    deps = pkg.get("dependencies") or {}
    dev = pkg.get("devDependencies") or {}

    assert deps["next"].startswith("^16")
    assert deps["react"].startswith("^19")
    assert deps["react-dom"].startswith("^19")
    assert dev["eslint-config-next"].startswith("^16")
    assert dev["jest"].startswith("^30")
    assert dev["jest-environment-jsdom"].startswith("^30")


def test_issue_343_dashboard_npm_ci_script_chain_for_lint_type_check_test_build():
    """npm run lint, type-check, test, and build scripts exist for dashboard CI."""
    scripts = _read_json(DASHBOARD_PKG).get("scripts") or {}
    for task in ("lint", "type-check", "test", "build"):
        assert task in scripts, f"missing npm script: {task}"
    assert scripts["lint"] == "eslint ."


def test_issue_343_pr_ci_includes_frontend_and_status_check_jobs():
    """PR CI workflow defines frontend and status-check jobs for merge gate."""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "frontend:" in workflow
    assert "status-check:" in workflow


def test_issue_343_handoff_documents_superseded_dependabot_prs():
    """Handoff lists Dependabot PRs superseded by the coordinated upgrade."""
    text = HANDOFF.read_text(encoding="utf-8")
    for pr in (322, 325, 327, 332, 338, 339):
        assert f"#{pr}" in text or f"PR #{pr}" in text


def test_issue_343_module_md_documents_next_16_react_19_stack():
    """apps/dashboard/MODULE.md stack section documents Next.js 16 and React 19."""
    text = DASHBOARD_MODULE.read_text(encoding="utf-8")
    assert "Next.js 16" in text
    assert "React 19" in text
    assert ESLINT_CONFIG.is_file()
    assert not LEGACY_ESLINTRC.is_file()
