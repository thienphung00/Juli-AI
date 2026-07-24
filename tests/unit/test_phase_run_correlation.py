"""Unit tests for phase_run_correlation (#515 / META-3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_phase_run_correlation import run_check  # noqa: E402
from common import build_implementation_artifact, write_json  # noqa: E402

PHASE_RUN_ID = "515-phase-test"


def _write_child_cache(repo: Path, *, required: dict[str, bool] | None = None) -> None:
    cache_dir = repo / "agent-runtime" / "artifacts" / "workflow-cache"
    cache_dir.mkdir(parents=True)
    required_artifacts = required or {
        "implementation": True,
        "intentReview": True,
        "review": True,
        "validation": True,
    }
    child = {
        "schemaVersion": "1.2.0",
        "artifactType": "issue_context_cache",
        "issueId": 515,
        "parentIssueId": 500,
        "issueLoadProfile": {
            "executorDomain": "backend",
            "releaseEvidencePlan": {"requiredArtifacts": required_artifacts},
        },
    }
    (cache_dir / "issue-context-cache-515.json").write_text(json.dumps(child), encoding="utf-8")


def _write_impl(repo: Path, phase_run_id: str = PHASE_RUN_ID) -> None:
    impl_dir = repo / "agent-runtime" / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        impl_dir / "implementation-issue-515.json",
        build_implementation_artifact(515, "backend", phase_run_id=phase_run_id),
    )


def _write_artifact(repo: Path, subdir: str, filename: str, payload: dict[str, Any]) -> None:
    directory = repo / "agent-runtime" / "artifacts" / subdir
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / filename, payload)


def test_phase_run_correlation_passes_when_all_match(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    monkeypatch.setattr(common, "INTENT_REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "intent-reviews")
    monkeypatch.setattr(common, "REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "reviews")
    monkeypatch.setattr(common, "VALIDATION_DIR", tmp_path / "agent-runtime" / "artifacts" / "validation")

    _write_child_cache(tmp_path)
    _write_impl(tmp_path)
    _write_artifact(
        tmp_path,
        "intent-reviews",
        "intent-review-issue-515.json",
        {"issue": 515, "phaseRunId": PHASE_RUN_ID},
    )
    _write_artifact(
        tmp_path,
        "reviews",
        "review-issue-515.json",
        {"issue": 515, "phaseRunId": PHASE_RUN_ID},
    )
    _write_artifact(
        tmp_path,
        "validation",
        "validation-issue-515.json",
        {"issue": 515, "phaseRunId": PHASE_RUN_ID},
    )

    passed, description, details = run_check(515, repo_root=tmp_path)

    assert passed is True
    assert details["canonicalPhaseRunId"] == PHASE_RUN_ID
    assert details["artifacts"]["review"]["status"] == "matched"
    assert "correlated" in description


def test_phase_run_correlation_fails_on_review_mismatch(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    monkeypatch.setattr(common, "INTENT_REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "intent-reviews")
    monkeypatch.setattr(common, "REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "reviews")
    monkeypatch.setattr(common, "VALIDATION_DIR", tmp_path / "agent-runtime" / "artifacts" / "validation")

    _write_child_cache(tmp_path, required={"implementation": True, "intentReview": False, "review": True, "validation": False})
    _write_impl(tmp_path)
    _write_artifact(
        tmp_path,
        "reviews",
        "review-issue-515.json",
        {"issue": 515, "phaseRunId": "other-run"},
    )

    passed, description, details = run_check(515, repo_root=tmp_path)

    assert passed is False
    assert "review" in description
    assert details["artifacts"]["review"]["status"] == "mismatch"


def test_phase_run_correlation_skips_optional_missing_artifacts(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    monkeypatch.setattr(common, "INTENT_REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "intent-reviews")
    monkeypatch.setattr(common, "REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "reviews")
    monkeypatch.setattr(common, "VALIDATION_DIR", tmp_path / "agent-runtime" / "artifacts" / "validation")

    _write_child_cache(
        tmp_path,
        required={
            "implementation": True,
            "intentReview": False,
            "review": False,
            "validation": False,
        },
    )
    _write_impl(tmp_path)

    passed, _description, details = run_check(515, repo_root=tmp_path)

    assert passed is True
    assert details["artifacts"]["intent_review"]["status"] == "skipped"


def test_phase_run_correlation_fails_when_required_validation_missing(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    monkeypatch.setattr(common, "INTENT_REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "intent-reviews")
    monkeypatch.setattr(common, "REVIEWS_DIR", tmp_path / "agent-runtime" / "artifacts" / "reviews")
    monkeypatch.setattr(common, "VALIDATION_DIR", tmp_path / "agent-runtime" / "artifacts" / "validation")

    _write_child_cache(tmp_path)
    _write_impl(tmp_path)

    passed, description, _details = run_check(515, repo_root=tmp_path)

    assert passed is False
    assert "validation" in description
