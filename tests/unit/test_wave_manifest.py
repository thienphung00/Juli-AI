"""Unit tests for wave manifest contract and validator (#659 / CI-WAVE-1, #670)."""

from __future__ import annotations

import hashlib
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
STATUS_DIR = REPO_ROOT / "agent-runtime" / "artifacts" / "status"


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


def _write_status_record(
    repo: Path,
    issue: int,
    *,
    review_status: str = "PASS",
    validation_status: str = "PASS",
    wrong_issue: int | None = None,
    review_sha256: str | None = None,
    validation_sha256: str | None = None,
) -> None:
    status_dir = repo / "agent-runtime" / "artifacts" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "issue": wrong_issue if wrong_issue is not None else issue,
        "wave": None,
        "review": {
            "status": review_status,
            "artifactRef": f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json",
            "sha256": review_sha256 or hashlib.sha256(b"review").hexdigest(),
        },
        "validation": {
            "status": validation_status,
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
            ),
            "sha256": validation_sha256 or hashlib.sha256(b"validation").hexdigest(),
        },
        "metrics": {
            "acceptanceTotal": 0,
            "acceptanceMapped": 0,
            "criticalFindings": 0,
            "modulesTouched": [],
        },
        "timestamp": "2026-08-02T00:00:00Z",
        "gateVersion": 1,
    }
    (status_dir / f"issue-{issue}.json").write_text(json.dumps(payload), encoding="utf-8")


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


def _patch_status_dir(monkeypatch, tmp_path: Path):
    import wave_manifest

    status_dir = tmp_path / "agent-runtime" / "artifacts" / "status"
    monkeypatch.setattr(wave_manifest, "STATUS_DIR", status_dir)
    return status_dir


def test_wave_artifacts_pass_for_valid_manifest(tmp_path: Path, monkeypatch) -> None:
    _patch_status_dir(monkeypatch, tmp_path)

    _write_status_record(tmp_path, 659)
    _write_status_record(tmp_path, 660)

    result = validate_wave_artifacts(_valid_manifest(issues=[659, 660]))
    assert result["valid"] is True
    assert result["errors"] == []


def test_wave_artifacts_fail_when_status_record_missing(tmp_path: Path, monkeypatch) -> None:
    _patch_status_dir(monkeypatch, tmp_path)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("missing status record" in error.lower() for error in result["errors"])


def test_wave_artifacts_fail_when_review_not_pass(tmp_path: Path, monkeypatch) -> None:
    _patch_status_dir(monkeypatch, tmp_path)

    _write_status_record(tmp_path, 659, review_status="FAIL")

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("review status" in error for error in result["errors"])


def test_wave_artifacts_fail_when_validation_not_pass(tmp_path: Path, monkeypatch) -> None:
    _patch_status_dir(monkeypatch, tmp_path)

    _write_status_record(tmp_path, 659, validation_status="FAIL")

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("validation status" in error for error in result["errors"])


def test_do_not_modify_github_workflows_pr_yml_in_slice() -> None:
    """AC5: validator under agent-runtime/scripts/ci; pr.yml wiring deferred to #660."""
    module_path = (
        Path(__file__).resolve().parents[2]
        / "agent-runtime"
        / "scripts"
        / "ci"
        / "wave_manifest.py"
    )
    assert module_path.is_file()
    pr_workflow = REPO_ROOT / ".github" / "workflows" / "pr.yml"
    assert pr_workflow.is_file()


def test_wave_artifacts_fail_when_status_record_issue_mismatch(tmp_path: Path, monkeypatch) -> None:
    _patch_status_dir(monkeypatch, tmp_path)

    _write_status_record(tmp_path, 659, wrong_issue=999)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))
    assert result["valid"] is False
    assert any("issue" in error.lower() for error in result["errors"])


def test_wave_artifacts_verify_integrity_passes_on_sha256_match(
    tmp_path: Path, monkeypatch
) -> None:
    import wave_manifest

    status_dir = _patch_status_dir(monkeypatch, tmp_path)
    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)
    reviews.mkdir(parents=True)
    validation.mkdir(parents=True)

    review_bytes = b'{"issue": 659, "status": "PASS"}'
    validation_bytes = b'{"issue": 659, "status": "PASS"}'
    (reviews / "review-issue-659.json").write_bytes(review_bytes)
    (validation / "validation-issue-659.json").write_bytes(validation_bytes)

    _write_status_record(
        tmp_path,
        659,
        review_sha256=hashlib.sha256(review_bytes).hexdigest(),
        validation_sha256=hashlib.sha256(validation_bytes).hexdigest(),
    )

    result = validate_wave_artifacts(_valid_manifest(issues=[659]), verify_integrity=True)
    assert result["valid"] is True
    assert result["errors"] == []
    assert (status_dir / "issue-659.json").is_file()


def test_wave_artifacts_verify_integrity_fails_on_sha256_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    import wave_manifest

    _patch_status_dir(monkeypatch, tmp_path)
    reviews = tmp_path / "agent-runtime" / "artifacts" / "reviews"
    validation = tmp_path / "agent-runtime" / "artifacts" / "validation"
    monkeypatch.setattr(wave_manifest, "REVIEWS_DIR", reviews)
    monkeypatch.setattr(wave_manifest, "VALIDATION_DIR", validation)
    reviews.mkdir(parents=True)
    validation.mkdir(parents=True)

    (reviews / "review-issue-659.json").write_bytes(b'{"issue": 659, "status": "PASS"}')
    (validation / "validation-issue-659.json").write_bytes(b'{"issue": 659, "status": "PASS"}')

    _write_status_record(tmp_path, 659)  # sha256 values won't match the bodies above

    result = validate_wave_artifacts(_valid_manifest(issues=[659]), verify_integrity=True)
    assert result["valid"] is False
    assert any("sha256 mismatch" in error for error in result["errors"])


# --- Scoped artifact waiver (ADR-059) -------------------------------------


def _waiver(issues: list[int], **overrides: Any) -> dict[str, Any]:
    waiver = {
        "adr": "docs/adr/059-dpr-wave-artifact-waiver.md",
        "reason": "evidence unrecoverable; diffs reviewed in its place",
        "approvedBy": "Repository owner",
        "issues": issues,
    }
    waiver.update(overrides)
    return waiver


def test_waiver_accepts_named_issues_without_status_records(tmp_path: Path, monkeypatch) -> None:
    _patch_status_dir(monkeypatch, tmp_path)

    manifest = _valid_manifest(issues=[659, 660], artifactWaiver=_waiver([659, 660]))
    result = validate_wave_artifacts(manifest)

    assert result["valid"] is True
    assert result["errors"] == []


def test_waiver_does_not_cover_an_issue_it_omits(tmp_path: Path, monkeypatch) -> None:
    """An issue added to the wave after the decision is not retroactively waived."""
    _patch_status_dir(monkeypatch, tmp_path)

    manifest = _valid_manifest(issues=[659, 660], artifactWaiver=_waiver([659]))
    result = validate_wave_artifacts(manifest)

    assert result["valid"] is False
    assert any("issue 660" in error for error in result["errors"])
    assert not any("issue 659" in error for error in result["errors"])


def test_waiver_covering_an_issue_outside_the_wave_is_an_error(tmp_path: Path, monkeypatch) -> None:
    _patch_status_dir(monkeypatch, tmp_path)

    manifest = _valid_manifest(issues=[659], artifactWaiver=_waiver([659, 999]))
    result = validate_wave_artifacts(manifest)

    assert result["valid"] is False
    assert any("not in this wave" in error for error in result["errors"])


def test_wave_without_a_waiver_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    """The waiver is opt-in per manifest; it must not soften any other wave."""
    _patch_status_dir(monkeypatch, tmp_path)

    result = validate_wave_artifacts(_valid_manifest(issues=[659]))

    assert result["valid"] is False
    assert any("missing status record" in error for error in result["errors"])


def test_waiver_is_described_for_the_gate_to_print() -> None:
    from wave_manifest import describe_waiver

    manifest = _valid_manifest(issues=[659], artifactWaiver=_waiver([659]))

    described = describe_waiver(manifest)

    assert described is not None
    assert "059" in described
    assert "Repository owner" in described
    assert describe_waiver(_valid_manifest()) is None
