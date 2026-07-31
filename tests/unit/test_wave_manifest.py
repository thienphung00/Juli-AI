"""Unit tests for wave manifest contract and validator (#659 / CI-WAVE-1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from wave_manifest import (  # noqa: E402
    check_issue_membership,
    validate_wave_artifacts,
    validate_wave_manifest,
    validate_wave_manifest_identity,
)

WAVES_DIR = REPO_ROOT / "agent-runtime" / "artifacts" / "waves"
REVIEWS_DIR = REPO_ROOT / "agent-runtime" / "artifacts" / "reviews"
VALIDATION_DIR = REPO_ROOT / "agent-runtime" / "artifacts" / "validation"


def _valid_manifest(**overrides: Any) -> dict[str, Any]:
    manifest = {
        "schemaVersion": "1.0.0",
        "artifactType": "wave_manifest",
        "waveId": "wave-658",
        "branch": "feature/658-wave",
        "issues": [659, 660],
    }
    manifest.update(overrides)
    return manifest


def _write_review(
    repo: Path, issue: int, *, status: str = "PASS", wrong_issue: int | None = None
) -> None:
    reviews = repo / "agent-runtime" / "artifacts" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": f"review-issue-{issue}",
        "issue": wrong_issue if wrong_issue is not None else issue,
        "status": status,
        "criticalFindings": [],
        "modulesTouched": [],
        "testCoverage": {"acceptance": {"total": 0, "mapped": 0, "mappings": []}},
    }
    (reviews / f"review-issue-{issue}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_validation(
    repo: Path,
    issue: int,
    *,
    status: str = "PASS",
    ready_for_merge: bool = True,
    wrong_issue: int | None = None,
) -> None:
    validation = repo / "agent-runtime" / "artifacts" / "validation"
    validation.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": f"validation-issue-{issue}",
        "issue": wrong_issue if wrong_issue is not None else issue,
        "status": status,
        "readyForMerge": ready_for_merge,
        "checks": [{"name": "smoke", "status": "PASS"}],
    }
    (validation / f"validation-issue-{issue}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_valid_manifest_passes() -> None:
    result = validate_wave_manifest(_valid_manifest())
    assert result["valid"] is True
    assert result["errors"] == []


@pytest.mark.parametrize(
    "issues",
    [
        [],
        [0],
        [-1],
        [659, 659],
        [659, "660"],
    ],
)
def test_invalid_issues_list_fails(issues: list[Any]) -> None:
    result = validate_wave_manifest(_valid_manifest(issues=issues))
    assert result["valid"] is False
    assert result["errors"]


def test_missing_required_fields_fails() -> None:
    manifest = _valid_manifest()
    del manifest["branch"]
    result = validate_wave_manifest(manifest)
    assert result["valid"] is False
    assert any("branch" in error for error in result["errors"])


def test_identity_rejects_wrong_wave_id() -> None:
    errors = validate_wave_manifest_identity(
        _valid_manifest(),
        expected_wave_id="wave-999",
        expected_branch="feature/658-wave",
    )
    assert errors
    assert any("waveId" in error for error in errors)


def test_identity_rejects_wrong_branch() -> None:
    errors = validate_wave_manifest_identity(
        _valid_manifest(),
        expected_wave_id="wave-658",
        expected_branch="feature/999-wave",
    )
    assert errors
    assert any("branch" in error for error in errors)


def test_issue_membership_passes_when_present() -> None:
    result = check_issue_membership(_valid_manifest(), 659)
    assert result["valid"] is True


def test_issue_membership_fails_when_missing() -> None:
    result = check_issue_membership(_valid_manifest(), 661)
    assert result["valid"] is False
    assert any("661" in error for error in result["errors"])


def test_wave_artifacts_pass_for_valid_manifest(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)

    _write_review(tmp_path, 659)
    _write_review(tmp_path, 660)
    _write_validation(tmp_path, 659)
    _write_validation(tmp_path, 660)

    result = validate_wave_artifacts(_valid_manifest(issues=[659, 660]))
    assert result["valid"] is True
    assert result["errors"] == []


def test_wave_artifacts_fail_when_review_missing(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)

    _write_validation(tmp_path, 659)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("review" in error.lower() for error in result["errors"])


def test_wave_artifacts_fail_when_validation_missing(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)

    _write_review(tmp_path, 659)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("validation" in error.lower() for error in result["errors"])


def test_wave_artifacts_fail_when_review_not_pass(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)

    _write_review(tmp_path, 659, status="FAIL")
    _write_validation(tmp_path, 659)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("status" in error for error in result["errors"])


def test_wave_artifacts_fail_when_validation_not_pass(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)

    _write_review(tmp_path, 659)
    _write_validation(tmp_path, 659, status="FAIL")

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("status" in error for error in result["errors"])


def test_wave_artifacts_fail_when_ready_for_merge_false(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)

    _write_review(tmp_path, 659)
    _write_validation(tmp_path, 659, ready_for_merge=False)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("readyForMerge" in error for error in result["errors"])


def test_wave_artifacts_fail_when_review_issue_mismatch(tmp_path: Path, monkeypatch) -> None:
    import wave_manifest

    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)

    _write_review(tmp_path, 659, wrong_issue=999)
    _write_validation(tmp_path, 659)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("issue" in error.lower() for error in result["errors"])
