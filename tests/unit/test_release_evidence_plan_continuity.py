"""Unit tests for release_evidence_plan_continuity (#515 / META-3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_release_evidence_plan_continuity import run_check  # noqa: E402
from common import build_implementation_artifact, write_json  # noqa: E402

PLAN_ID = "rep-515-meta3-ci-validators"


def _write_child_cache(repo: Path, *, public_release: bool, plan_id: str | None = PLAN_ID) -> None:
    cache_dir = repo / "agent-runtime" / "artifacts" / "workflow-cache"
    cache_dir.mkdir(parents=True)
    profile: dict = {"executorDomain": "backend"}
    if plan_id is not None:
        profile["releaseEvidencePlan"] = {"planId": plan_id}
    child = {
        "schemaVersion": "1.2.0",
        "artifactType": "issue_context_cache",
        "issueId": 515,
        "parentIssueId": 500,
        "publicRelease": public_release,
        "issueLoadProfile": profile,
    }
    (cache_dir / "issue-context-cache-515.json").write_text(json.dumps(child), encoding="utf-8")


def _write_impl(repo: Path, *, plan_id: str | None = PLAN_ID) -> None:
    impl_dir = repo / "agent-runtime" / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True, exist_ok=True)
    artifact = build_implementation_artifact(515, "backend")
    if plan_id is not None:
        artifact["releaseEvidencePlanId"] = plan_id
    write_json(impl_dir / "implementation-issue-515.json", artifact)


def test_release_plan_continuity_skips_non_public(tmp_path: Path) -> None:
    _write_child_cache(tmp_path, public_release=False)
    _write_impl(tmp_path, plan_id=None)

    passed, description, details = run_check(515, repo_root=tmp_path)

    assert passed is True
    assert details.get("skipped") is True
    assert "not required" in description


def test_release_plan_continuity_passes_on_match(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write_child_cache(tmp_path, public_release=True)
    _write_impl(tmp_path, plan_id=PLAN_ID)

    passed, description, details = run_check(515, repo_root=tmp_path)

    assert passed is True
    assert details["implementationPlanId"] == PLAN_ID
    assert PLAN_ID in description


def test_release_plan_continuity_fails_on_implementation_mismatch(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write_child_cache(tmp_path, public_release=True)
    _write_impl(tmp_path, plan_id="wrong-plan")

    passed, description, _details = run_check(515, repo_root=tmp_path)

    assert passed is False
    assert "mismatch" in description


def test_release_plan_continuity_fails_on_validation_mismatch(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    monkeypatch.setattr(common, "VALIDATION_DIR", tmp_path / "agent-runtime" / "artifacts" / "validation")
    _write_child_cache(tmp_path, public_release=True)
    _write_impl(tmp_path, plan_id=PLAN_ID)
    validation_dir = tmp_path / "agent-runtime" / "artifacts" / "validation"
    validation_dir.mkdir(parents=True)
    write_json(
        validation_dir / "validation-issue-515.json",
        {"issue": 515, "releaseEvidencePlanId": "other-plan"},
    )

    passed, description, _details = run_check(515, repo_root=tmp_path)

    assert passed is False
    assert "validation" in description
