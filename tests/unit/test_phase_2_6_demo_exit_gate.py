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


def test_e2e_covers_home_decisions_priority_workflow_cards_approval_in_progress() -> None:
    text = (E2E_DIR / "decisions-journey.spec.ts").read_text(encoding="utf-8")
    assert "Home → Decisions" in text or "Home exposes exactly two destination launchers" in text
    assert "Priority Workflow 1" in text
    assert "every executable workflow reaches In Progress" in text


def test_manual_refresh_returns_default_decisions_recommendations_state() -> None:
    text = (E2E_DIR / "manual-refresh.spec.ts").read_text(encoding="utf-8")
    assert "resetDemo" in text or "Manual Refresh" in text
    assert "Recommendations" in text


def test_playwright_desktop_and_mobile_web_viewport_suites_preserve_ia() -> None:
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    assert '"desktop"' in config
    assert '"mobile-web"' in config
    text = (E2E_DIR / "responsive-parity.spec.ts").read_text(encoding="utf-8")
    assert "card order" in text.lower()


def test_automated_accessibility_keyboard_focus_touch_targets_chart_equivalents() -> None:
    text = (E2E_DIR / "accessibility.spec.ts").read_text(encoding="utf-8")
    assert "AxeBuilder" in text
    assert "44" in text
    assert "focus-visible" in text
    assert "prefers-reduced-motion" in text
    assert "sr-only" in text or "chart equivalent" in text.lower()


def test_vietnamese_copy_diacritics_and_truthful_empty_loading_error_states() -> None:
    text = (E2E_DIR / "locale-and-assistance.spec.ts").read_text(encoding="utf-8")
    assert "Vietnamese diacritics" in text
    assert "load=error" in text
    assert "Mock mode notice" in text


def test_production_build_and_deploy_contract_tests_run_in_ci() -> None:
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "demo-e2e:" in workflow
    assert "pnpm --filter @juli/demo test:e2e" in workflow
    assert "demo-deploy-contracts:" in workflow
    assert "build:demo" in workflow or "check:demo" in workflow


def test_exit_gate_does_not_depend_on_optional_settings_issue_405() -> None:
    text = (E2E_DIR / "locale-and-assistance.spec.ts").read_text(encoding="utf-8")
    assert "Settings" not in text or "Cài đặt provides grounded assistance" in text
    assert "settings/workflows" not in text.lower()


def test_exit_gate_does_not_depend_on_optional_analytics_issue_404() -> None:
    text = (E2E_DIR / "accessibility.spec.ts").read_text(encoding="utf-8")
    assert "analytics-unavailable-chart" in text or "Chưa khả dụng" in text
    assert "six-KPI" not in text
