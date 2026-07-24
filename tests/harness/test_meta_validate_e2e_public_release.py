"""E2E fixtures: Meta prepare → mock artifacts → validate matrix (#516 / META-4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
for path in (VALIDATE_DIR, CI_DIR, REPO_ROOT / "tests" / "harness", REPO_ROOT / "tests" / "unit"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from check_public_release_evidence_plan import run_check as run_evidence_plan  # noqa: E402
from meta_validate_e2e_fixtures import (  # noqa: E402
    META_VALIDATE_CHECKS,
    NON_PUBLIC_ISSUE,
    PHASE_RUN_ID,
    PLAN_ID,
    PUBLIC_ISSUE,
    ensure_non_public_issue_cache,
    ensure_public_issue_cache,
    evidence_plan_gate_result,
    meta_validate_check_names,
    patch_artifact_dirs,
    run_meta_prepare,
    run_meta_validate_matrix,
    valid_release_plan,
    write_matching_phase_artifacts,
)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def patched_dirs(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_artifact_dirs(monkeypatch, repo_root)


class TestPublicReleaseMetaValidateE2E:
    def test_public_missing_plan_evidence_gate_halts(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        ensure_public_issue_cache(repo_root, plan=None)

        passed, description, details = run_evidence_plan(PUBLIC_ISSUE, repo_root=repo_root)

        assert passed is False
        assert details.get("halt") is True
        assert "planId" in details["missingFields"]
        assert "resolution" in details

    def test_public_missing_plan_meta_prepare_halts(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, patched_dirs: None
    ) -> None:
        ensure_public_issue_cache(repo_root, plan=None)
        _passed, gate_results = evidence_plan_gate_result(repo_root, PUBLIC_ISSUE)

        code, payload = run_meta_prepare(
            repo_root,
            monkeypatch,
            PUBLIC_ISSUE,
            gate_results=gate_results,
        )

        assert code == 1
        assert payload["readyForExecutor"] is False
        assert payload["halt"] is True
        assert payload["failedGate"] == "public_release_evidence_plan"
        assert payload["missingFields"]
        assert "releaseEvidencePlan" not in payload.get("injectionPlan", {})

    def test_public_valid_plan_meta_prepare_ready(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, patched_dirs: None
    ) -> None:
        plan = valid_release_plan()
        ensure_public_issue_cache(repo_root, plan=plan)

        code, payload = run_meta_prepare(repo_root, monkeypatch, PUBLIC_ISSUE)

        assert code == 0
        assert payload["readyForExecutor"] is True
        assert payload["halt"] is False
        injection = payload["injectionPlan"]
        assert injection["publicRelease"] is True
        assert injection["releaseEvidencePlan"] == plan
        assert injection["releaseEvidencePlanId"] == PLAN_ID

    def test_public_full_validation_matrix_passes(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        plan = valid_release_plan()
        ensure_public_issue_cache(repo_root, plan=plan)
        write_matching_phase_artifacts(
            repo_root,
            PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id=PLAN_ID,
            public_release=True,
        )

        matrix = run_meta_validate_matrix(PUBLIC_ISSUE, repo_root=repo_root)

        assert matrix["status"] == "PASS"
        assert matrix["failedChecks"] == 0
        assert {check["name"] for check in matrix["checks"]} == {
            "release_evidence_plan_continuity",
            "phase_run_correlation",
            "implementation_tdd_evidence",
        }
        assert all(check["status"] == "PASS" for check in matrix["checks"])

    def test_public_matrix_fails_plan_id_mismatch(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        plan = valid_release_plan()
        ensure_public_issue_cache(repo_root, plan=plan)
        write_matching_phase_artifacts(
            repo_root,
            PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id="wrong-plan-id",
            public_release=True,
        )

        matrix = run_meta_validate_matrix(PUBLIC_ISSUE, repo_root=repo_root)

        assert matrix["status"] == "FAIL"
        assert matrix["failedChecks"] >= 1
        continuity = next(
            check for check in matrix["checks"] if check["name"] == "release_evidence_plan_continuity"
        )
        assert continuity["status"] == "FAIL"
        assert "mismatch" in continuity["description"]

    def test_public_matrix_fails_phase_run_mismatch(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        plan = valid_release_plan()
        ensure_public_issue_cache(repo_root, plan=plan)
        write_matching_phase_artifacts(
            repo_root,
            PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id=PLAN_ID,
            public_release=True,
        )
        review_path = (
            repo_root
            / "agent-runtime"
            / "artifacts"
            / "reviews"
            / f"review-issue-{PUBLIC_ISSUE}.json"
        )
        review = review_path.read_text(encoding="utf-8").replace(PHASE_RUN_ID, "other-phase-run")
        review_path.write_text(review, encoding="utf-8")

        matrix = run_meta_validate_matrix(PUBLIC_ISSUE, repo_root=repo_root)

        assert matrix["status"] == "FAIL"
        correlation = next(
            check for check in matrix["checks"] if check["name"] == "phase_run_correlation"
        )
        assert correlation["status"] == "FAIL"
        assert "review" in correlation["description"]

    def test_public_matrix_fails_empty_tdd_evidence(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        plan = valid_release_plan()
        ensure_public_issue_cache(repo_root, plan=plan)
        write_matching_phase_artifacts(
            repo_root,
            PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id=PLAN_ID,
            public_release=True,
            tdd_overrides={"redGreenRefactorEvidence": []},
        )

        matrix = run_meta_validate_matrix(PUBLIC_ISSUE, repo_root=repo_root)

        assert matrix["status"] == "FAIL"
        tdd = next(
            check for check in matrix["checks"] if check["name"] == "implementation_tdd_evidence"
        )
        assert tdd["status"] == "FAIL"


class TestNonPublicMetaValidateE2E:
    def test_non_public_meta_prepare_ready_without_plan(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, patched_dirs: None
    ) -> None:
        ensure_non_public_issue_cache(repo_root)

        code, payload = run_meta_prepare(repo_root, monkeypatch, NON_PUBLIC_ISSUE)

        assert code == 0
        assert payload["readyForExecutor"] is True
        injection = payload["injectionPlan"]
        assert injection["publicRelease"] is False
        assert "releaseEvidencePlan" not in injection
        assert "releaseEvidencePlanId" not in injection

    def test_non_public_evidence_plan_gate_skips(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        ensure_non_public_issue_cache(repo_root)

        passed, description, details = run_evidence_plan(NON_PUBLIC_ISSUE, repo_root=repo_root)

        assert passed is True
        assert details.get("skipped") is True
        assert "not required" in description

    def test_non_public_continuity_skipped_in_matrix(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        ensure_non_public_issue_cache(repo_root)
        write_matching_phase_artifacts(
            repo_root,
            NON_PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id=None,
            public_release=False,
        )

        matrix = run_meta_validate_matrix(NON_PUBLIC_ISSUE, repo_root=repo_root)

        continuity = next(
            check for check in matrix["checks"] if check["name"] == "release_evidence_plan_continuity"
        )
        assert continuity["status"] == "PASS"
        assert continuity["details"].get("skipped") is True

    def test_non_public_full_validation_matrix_passes(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        ensure_non_public_issue_cache(repo_root)
        write_matching_phase_artifacts(
            repo_root,
            NON_PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id=None,
            public_release=False,
        )

        matrix = run_meta_validate_matrix(NON_PUBLIC_ISSUE, repo_root=repo_root)

        assert matrix["status"] == "PASS"
        assert matrix["failedChecks"] == 0

    def test_non_public_matrix_fails_bad_tdd_evidence(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        ensure_non_public_issue_cache(repo_root)
        write_matching_phase_artifacts(
            repo_root,
            NON_PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id=None,
            public_release=False,
            tdd_overrides={"testsAdded": [], "testsUpdated": []},
        )

        matrix = run_meta_validate_matrix(NON_PUBLIC_ISSUE, repo_root=repo_root)

        assert matrix["status"] == "FAIL"
        assert matrix["failedChecks"] == 1
        tdd = next(
            check for check in matrix["checks"] if check["name"] == "implementation_tdd_evidence"
        )
        assert tdd["status"] == "FAIL"

    def test_single_check_fail_causes_overall_matrix_fail(
        self, repo_root: Path, patched_dirs: None
    ) -> None:
        ensure_non_public_issue_cache(repo_root)
        write_matching_phase_artifacts(
            repo_root,
            NON_PUBLIC_ISSUE,
            phase_run_id=PHASE_RUN_ID,
            plan_id=None,
            public_release=False,
            tdd_overrides={"redGreenRefactorEvidence": []},
        )

        matrix = run_meta_validate_matrix(NON_PUBLIC_ISSUE, repo_root=repo_root)

        assert matrix["status"] == "FAIL"
        assert matrix["failedChecks"] == 1
        assert matrix["passedChecks"] == 2
        assert "failed" in matrix["overallSummary"].lower()


def test_meta_validate_checks_wired_in_generate_validation_artifact() -> None:
    wired = meta_validate_check_names()
    expected = [name for name, _ in META_VALIDATE_CHECKS]
    assert wired == expected
