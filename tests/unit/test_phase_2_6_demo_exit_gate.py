"""Doc and config contract tests for Phase 2.6 Demo exit gate (Issue #407).

Issue #407 adds Playwright E2E/responsive/a11y coverage plus CI wiring for the
Phase 2.6 Demo mock journey. These tests assert deliverables exist and stay wired
without requiring a live demo.app-juli.com deployment in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = REPO_ROOT / "apps" / "demo"
E2E_DIR = DEMO_ROOT / "e2e" / "exit-gate"
PLAYWRIGHT_CONFIG = DEMO_ROOT / "playwright.config.ts"
DEMO_PACKAGE = DEMO_ROOT / "package.json"
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"
SMOKE_DEMO_PATH = REPO_ROOT / "infra" / "scripts" / "smoke-test-demo.sh"

REQUIRED_SPECS = (
    "decisions-journey.spec.ts",
    "manual-refresh.spec.ts",
    "responsive-parity.spec.ts",
    "accessibility.spec.ts",
    "locale-and-assistance.spec.ts",
)


@pytest.mark.parametrize("spec_name", REQUIRED_SPECS)
def test_exit_gate_playwright_specs_exist(spec_name: str) -> None:
    path = E2E_DIR / spec_name
    assert path.is_file(), f"Missing Playwright spec: {path.relative_to(REPO_ROOT)}"


def test_playwright_config_exists() -> None:
    assert PLAYWRIGHT_CONFIG.is_file()


def test_demo_package_exposes_e2e_script() -> None:
    text = DEMO_PACKAGE.read_text(encoding="utf-8")
    assert '"test:e2e"' in text
    assert "playwright test" in text
    assert "@playwright/test" in text
    assert "@axe-core/playwright" in text


def test_pr_workflow_runs_demo_e2e_job() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "demo-e2e:" in text
    assert "pnpm --filter @juli/demo test:e2e" in text
    assert "demo_e2e" in text


def test_public_smoke_script_covers_decisions_route() -> None:
    text = SMOKE_DEMO_PATH.read_text(encoding="utf-8")
    assert "/decisions" in text
    assert "demo.app-juli.com" in text


def test_deploy_contract_tests_remain_in_pr_workflow() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "demo-deploy-contracts:" in text
    assert "test_phase_2_6_demo_deploy_config.py" in text
