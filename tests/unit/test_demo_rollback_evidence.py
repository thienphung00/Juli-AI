"""ADR-035 rollback evidence and static-asset release gate contracts (#499).

Proves the Demo VPS bridge documents and wires rollback plus static-asset checks
without requiring a live deployment in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra" / "scripts"
RUNBOOK_PATH = REPO_ROOT / "docs" / "runbooks" / "demo-deploy-runbook.md"
ROLLBACK_DEMO_PATH = SCRIPTS_DIR / "rollback-demo-release.sh"
SMOKE_DEMO_PATH = SCRIPTS_DIR / "smoke-test-demo.sh"
VERIFY_STATIC_PATH = SCRIPTS_DIR / "verify-demo-static-assets.sh"
BUILD_DEMO_PATH = SCRIPTS_DIR / "build-demo.sh"

pytestmark = pytest.mark.demo_contract

STATIC_ASSET_SPEC = (
    REPO_ROOT / "apps" / "demo" / "e2e" / "exit-gate" / "static-asset-render.spec.ts"
)
RELEASE_EVIDENCE_PLAN = (
    REPO_ROOT / "agent-runtime" / "artifacts" / "release-evidence-plan-issue-499.json"
)

ROLLBACK_COMMAND = "./infra/scripts/rollback-demo-release.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def runbook_text() -> str:
    return _read(RUNBOOK_PATH)


def test_rollback_script_exists_and_is_executable() -> None:
    assert ROLLBACK_DEMO_PATH.is_file(), f"missing rollback script: {ROLLBACK_DEMO_PATH}"
    assert ROLLBACK_DEMO_PATH.stat().st_mode & 0o111, "rollback-demo-release.sh must be executable"


def test_rollback_script_affects_the_demo_lane_only() -> None:
    script = _read(ROLLBACK_DEMO_PATH)
    directives = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    # This used to require `systemctl restart juli-demo`. #839 removed it: the live port
    # is now decided by the upstream definition, so restarting the durable unit would
    # collide with whatever is serving. Rollback starts the target on the free port and
    # goes through the same graceful switch a deploy uses. What must still hold — that
    # rollback touches nothing outside the Demo lane — is unchanged.
    assert "systemctl restart juli-demo" not in directives
    assert "switch_demo_upstream" in directives
    assert "systemctl restart juli-api" not in script
    assert "systemctl restart juli-web" not in script
    assert "demo-current" in script
    assert "demo-deploy-history.log" in script


def test_runbook_documents_rollback_command(runbook_text: str) -> None:
    assert "rollback-demo-release.sh" in runbook_text
    assert ROLLBACK_COMMAND in runbook_text
    assert "without affecting app-juli.com" in runbook_text.replace("`", "")


def test_runbook_documents_static_asset_release_gates(runbook_text: str) -> None:
    lowered = runbook_text.lower()
    assert "adr-035" in lowered or "release evidence" in lowered
    assert "verify-demo-static-assets.sh" in runbook_text
    assert "smoke-test-demo.sh" in runbook_text
    assert "static-asset-render.spec.ts" in runbook_text
    assert "build-demo.sh" in runbook_text


def test_static_asset_render_playwright_spec_exists() -> None:
    assert STATIC_ASSET_SPEC.is_file(), f"missing Playwright spec: {STATIC_ASSET_SPEC}"
    text = _read(STATIC_ASSET_SPEC)
    assert "expectBrandedComputedStyles" in text
    assert "Home → Decisions" in text or 'navigatePrimaryDestination(page, "Quyết định")' in text


def test_release_evidence_plan_documents_rollback_and_static_checks() -> None:
    assert RELEASE_EVIDENCE_PLAN.is_file()
    text = _read(RELEASE_EVIDENCE_PLAN)
    assert ROLLBACK_COMMAND in text
    assert "computed_styles_non_browser_default" in text
    assert "primary_nav_to_decisions_works" in text
    assert "static-asset-render.spec.ts" in text


def test_smoke_and_verify_scripts_exist_for_asset_integrity() -> None:
    assert SMOKE_DEMO_PATH.is_file()
    assert VERIFY_STATIC_PATH.is_file(), (
        "verify-demo-static-assets.sh is required by ADR-035 bridge"
    )
    assert BUILD_DEMO_PATH.is_file()
