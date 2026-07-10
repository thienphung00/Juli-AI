"""Doc contract tests for Phase 2.5 deployment scaffold (Issue #250)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE_25_PATH = REPO_ROOT / "docs/phases/phase-2.5-deployment.md"
MIGRATION_PLAN_PATH = REPO_ROOT / "docs/architecture/migration-plan.md"
EXECUTION_PATH = REPO_ROOT / "EXECUTION.md"
MAP_PATH = REPO_ROOT / "docs/architecture/map.md"

SCAFFOLD_READMES = (
    "apps/README.md",
    "apps/landing/README.md",
    "apps/demo/README.md",
    "apps/dashboard/README.md",
    "apps/mobile/README.md",
    "packages/README.md",
    "packages/ui/README.md",
    "packages/theme/README.md",
    "packages/icons/README.md",
    "packages/illustrations/README.md",
    "packages/api-client/README.md",
    "packages/types/README.md",
    "packages/utils/README.md",
    "backend/README.md",
    "backend/src/juli_backend/api/README.md",
    "backend/src/juli_backend/workers/README.md",
    "backend/src/juli_backend/ai/README.md",
    "backend/src/juli_backend/integrations/README.md",
    "backend/src/juli_backend/database/README.md",
    "infra/README.md",
    "infra/ci/README.md",
    "infra/deploy/README.md",
)


@pytest.fixture
def phase_25_text() -> str:
    return PHASE_25_PATH.read_text(encoding="utf-8")


@pytest.fixture
def migration_plan_text() -> str:
    return MIGRATION_PLAN_PATH.read_text(encoding="utf-8")


@pytest.fixture
def execution_text() -> str:
    return EXECUTION_PATH.read_text(encoding="utf-8")


@pytest.fixture
def map_text() -> str:
    return MAP_PATH.read_text(encoding="utf-8")


def test_phase_2_5_deployment_doc_exists_with_scaffold_gate(phase_25_text: str):
    """Phase 2.5 doc declares scaffold + backend migration scope and marks 2.5-a exit items."""
    assert "Phase 2.5" in phase_25_text
    assert "backend runtime boundary moved to `backend/`" in phase_25_text
    assert "Target folders scaffolded with ownership READMEs" in phase_25_text
    assert "[x]" in phase_25_text


def test_scaffold_ownership_readmes_exist():
    """All planned product, package, backend, and infra subfolders have READMEs."""
    missing = [rel for rel in SCAFFOLD_READMES if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"missing scaffold READMEs: {missing}"


def test_naming_collision_documented(
    migration_plan_text: str, map_text: str, execution_text: str
):
    """backend/api vs top-level apps collision is explicit in canonical docs."""
    for doc_text in (migration_plan_text, map_text, execution_text):
        assert "apps/" in doc_text or "backend/api" in doc_text
    assert "Naming collision" in migration_plan_text
    apps_readme = (REPO_ROOT / "apps/README.md").read_text(encoding="utf-8")
    assert "Not to be confused with `backend/api/`" in apps_readme


def test_canonical_docs_agree_on_migration_sequence(
    execution_text: str, migration_plan_text: str, map_text: str, phase_25_text: str
):
    """EXECUTION, map, phase-2.5, and migration-plan cross-link and name 2.5-a."""
    for doc_text in (execution_text, map_text, phase_25_text):
        assert "migration-plan.md" in doc_text or "architecture/migration-plan.md" in doc_text
    assert "2.5-a" in migration_plan_text
    assert "Phase 2.5" in execution_text
    assert "Deployment Architecture" in execution_text


def test_no_runtime_code_moved_in_2_5_a_slice(migration_plan_text: str):
    """PR 2.5-a gate documents no runtime code movement."""
    assert "2.5-a" in migration_plan_text
    assert "No runtime changes" in migration_plan_text
