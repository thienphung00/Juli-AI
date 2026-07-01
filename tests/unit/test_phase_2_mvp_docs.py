"""Doc contract tests for phase-2-mvp.md — migrated from target-v2 stub (Issue #143)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE_2_MVP_PATH = REPO_ROOT / "docs/phases/phase-2-mvp.md"
EXECUTION_PATH = REPO_ROOT / "EXECUTION.md"
SYSTEM_DESIGN_PATH = REPO_ROOT / "docs/system-design.md"
MAP_PATH = REPO_ROOT / "docs/architecture/map.md"


@pytest.fixture
def phase_2_mvp_text() -> str:
    return PHASE_2_MVP_PATH.read_text(encoding="utf-8")


@pytest.fixture
def execution_text() -> str:
    return EXECUTION_PATH.read_text(encoding="utf-8")


@pytest.fixture
def system_design_text() -> str:
    return SYSTEM_DESIGN_PATH.read_text(encoding="utf-8")


@pytest.fixture
def map_text() -> str:
    return MAP_PATH.read_text(encoding="utf-8")


def test_phase_2_mvp_exists_with_pipeline(phase_2_mvp_text: str):
    """End-to-end Phase 2 pipeline documented with schedule or flow."""
    assert "Phase 2" in phase_2_mvp_text
    for stage in ("poll", "rules-based", "copy"):
        assert stage.lower() in phase_2_mvp_text.lower(), f"missing pipeline stage: {stage}"


def test_phase_2_mvp_references_schedule_and_models(phase_2_mvp_text: str):
    """References batch schedule; trained ML deferred to Phase 4."""
    assert "08:00" in phase_2_mvp_text
    assert "no trained ml" in phase_2_mvp_text.lower()
    assert "phase 4" in phase_2_mvp_text.lower()


def test_phase_2_mvp_docs_not_weakened(phase_2_mvp_text: str):
    """Phase 2 MVP doc contract remains intact after Phase 2.5 doc alignment."""
    assert "rules-based" in phase_2_mvp_text.lower()
    assert "phase-2.5-deployment.md" in phase_2_mvp_text


def test_cross_links_point_to_phase_2_mvp(
    execution_text: str, system_design_text: str, map_text: str
):
    """EXECUTION.md, system-design.md, and map.md link to phase-2-mvp.md."""
    for doc_text in (execution_text, system_design_text, map_text):
        assert "phase-2-mvp.md" in doc_text


def test_target_v2_stub_removed():
    """Redirect stub retired — authority is phase-2-mvp.md."""
    assert not (REPO_ROOT / "docs/architecture/target-v2.md").exists()
