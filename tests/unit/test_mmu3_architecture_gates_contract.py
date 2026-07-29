"""MMU-3 (#556): PR-blocking architecture gates wired into pr.yml."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"
IMPORT_BOUNDARIES_DOC = REPO_ROOT / "docs" / "architecture" / "import-boundaries.md"


def test_pr_workflow_defines_architecture_gates_job() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "architecture-gates:" in text


def test_architecture_gates_runs_on_backend_path_filter() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "architecture-gates:" in text
    assert "needs.changes.outputs.backend == 'true'" in text


def test_architecture_gates_runs_import_boundaries_strict() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "check_import_boundaries.py" in text
    assert "--strict" in text


def test_architecture_gates_runs_cycle_and_ownership_checks() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "audit_cycles.py" in text
    assert "check_ownership_registry.py" in text


def test_architecture_gates_merge_group_requires_success() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert 'require "architecture-gates"' in text
    assert "merge_group requires success" in text


def test_backend_path_filter_includes_architecture_contract_paths() -> None:
    text = PR_WORKFLOW.read_text(encoding="utf-8")
    assert ".importlinter.toml" in text
    assert "docs/architecture/ownership-registry.yml" in text


def test_import_boundaries_doc_documents_merge_queue_status_checks() -> None:
    text = IMPORT_BOUNDARIES_DOC.read_text(encoding="utf-8")
    assert "PR Validation / architecture-gates" in text
    assert "PR Validation / status-check" in text
