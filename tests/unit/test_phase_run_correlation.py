"""Unit tests for phase_run_correlation (#515 / META-3, hardened by #1439).

#1439: the required-artifact set is computed in CI from tier + branch. The
release-evidence plan — which the same agent loop writes — may no longer narrow
it, and a missing artifact the computed set marks required can never resolve to
a "skipped" status.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_phase_run_correlation import run_check  # noqa: E402
from common import build_implementation_artifact, write_json  # noqa: E402
from required_artifacts import (  # noqa: E402
    ARTIFACT_KEYS,
    UnresolvableTierError,
    compute_required_artifacts,
    resolve_tier_and_branch,
)

PHASE_RUN_ID = "515-phase-test"
ISSUE_BRANCH = "feature/issue-515-phase-correlation"

ALL_RELAXED = {
    "implementation": True,
    "intentReview": False,
    "review": False,
    "validation": False,
}


def _write_child_cache(repo: Path, *, required: dict[str, bool] | None = None) -> None:
    cache_dir = repo / "agent-runtime" / "artifacts" / "workflow-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
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


@pytest.fixture
def patched_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import common

    base = tmp_path / "agent-runtime" / "artifacts"
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", base / "implementations")
    monkeypatch.setattr(common, "INTENT_REVIEWS_DIR", base / "intent-reviews")
    monkeypatch.setattr(common, "REVIEWS_DIR", base / "reviews")
    monkeypatch.setattr(common, "VALIDATION_DIR", base / "validation")
    return tmp_path


def _write_intent_review(repo: Path, phase_run_id: str = PHASE_RUN_ID) -> None:
    _write_artifact(
        repo,
        "intent-reviews",
        "intent-review-issue-515.json",
        {"issue": 515, "phaseRunId": phase_run_id},
    )


def _write_review(repo: Path, phase_run_id: str = PHASE_RUN_ID) -> None:
    _write_artifact(
        repo, "reviews", "review-issue-515.json", {"issue": 515, "phaseRunId": phase_run_id}
    )


def _write_validation(repo: Path, phase_run_id: str = PHASE_RUN_ID) -> None:
    _write_artifact(
        repo,
        "validation",
        "validation-issue-515.json",
        {"issue": 515, "phaseRunId": phase_run_id},
    )


# --- existing behaviour, now with an explicitly computed tier -----------------


def test_phase_run_correlation_passes_when_all_match(patched_dirs: Path) -> None:
    repo = patched_dirs
    _write_child_cache(repo)
    _write_impl(repo)
    _write_intent_review(repo)
    _write_review(repo)
    _write_validation(repo)

    passed, description, details = run_check(515, repo_root=repo, tier="issue", branch=ISSUE_BRANCH)

    assert passed is True
    assert details["canonicalPhaseRunId"] == PHASE_RUN_ID
    assert details["artifacts"]["review"]["status"] == "matched"
    assert "correlated" in description


def test_phase_run_correlation_fails_on_review_mismatch(patched_dirs: Path) -> None:
    repo = patched_dirs
    _write_child_cache(repo)
    _write_impl(repo)
    _write_intent_review(repo)
    _write_review(repo, phase_run_id="other-run")
    _write_validation(repo)

    passed, description, details = run_check(515, repo_root=repo, tier="issue", branch=ISSUE_BRANCH)

    assert passed is False
    assert "review" in description
    assert details["artifacts"]["review"]["status"] == "mismatch"


def test_phase_run_correlation_fails_when_required_validation_missing(
    patched_dirs: Path,
) -> None:
    repo = patched_dirs
    _write_child_cache(repo)
    _write_impl(repo)
    _write_intent_review(repo)
    _write_review(repo)

    passed, description, _details = run_check(
        515, repo_root=repo, tier="issue", branch=ISSUE_BRANCH
    )

    assert passed is False
    assert "validation" in description


# --- #1439 acceptance criteria ------------------------------------------------


def test_plan_cannot_narrow_required_set(patched_dirs: Path) -> None:
    """An issue-tier plan setting intentReview: false must not relax the gate.

    This is the load-bearing test: before #1439 the gate read ``required``
    straight out of the release-evidence plan the same loop writes, so this
    exact shape returned PASS with status "skipped".
    """
    repo = patched_dirs
    _write_child_cache(repo, required=ALL_RELAXED)
    _write_impl(repo)
    _write_review(repo)
    _write_validation(repo)
    # intent-review artifact deliberately absent

    passed, description, details = run_check(515, repo_root=repo, tier="issue", branch=ISSUE_BRANCH)

    assert passed is False, "a plan-relaxed intentReview must not make the gate pass"
    assert "intent_review" in description
    entry = details["artifacts"]["intent_review"]
    assert entry["required"] is True
    assert entry["status"] == "missing"
    # The plan is recorded as evidence, never consulted for the verdict.
    assert details["requiredArtifactSet"]["source"] == "ci-computed"
    assert details["planRequiredArtifacts"]["intentReview"] is False
    assert "intentReview" in details["planNarrowingIgnored"]


def test_missing_required_artifact_never_reports_skipped(patched_dirs: Path) -> None:
    repo = patched_dirs
    _write_child_cache(repo, required=ALL_RELAXED)
    _write_impl(repo)
    # intent-review, review and validation all absent

    passed, description, details = run_check(515, repo_root=repo, tier="issue", branch=ISSUE_BRANCH)

    assert passed is False
    for label in ("intent_review", "review", "validation"):
        entry = details["artifacts"][label]
        assert entry["status"] == "missing", f"{label} resolved to {entry['status']!r}"
        assert entry["status"] != "skipped"
        assert label in description


def test_tier_narrowing_is_explicit_and_logged(patched_dirs: Path) -> None:
    repo = patched_dirs
    _write_child_cache(repo)
    _write_impl(repo)
    # no review-phase artifacts: the docs lane never runs those phases

    passed, _description, details = run_check(
        515, repo_root=repo, tier="issue", branch="docs/harness-e-epic-handoff"
    )

    assert passed is True
    computed = details["requiredArtifactSet"]
    assert computed["source"] == "ci-computed"
    assert computed["tier"] == "issue"
    assert computed["branchClass"] == "docs"
    assert computed["narrowed"] == ["intentReview", "review", "validation"]
    assert computed["reason"], "tier narrowing must carry a stated reason"
    assert "docs" in computed["reason"]
    for label in ("intent_review", "review", "validation"):
        assert details["artifacts"][label]["status"] == "skipped_by_tier"
        assert details["artifacts"][label]["narrowingReason"] == computed["reason"]


def test_tier_narrowing_for_hotfix_keeps_review_required(patched_dirs: Path) -> None:
    repo = patched_dirs
    _write_child_cache(repo)
    _write_impl(repo)
    # review missing on a hotfix branch: still required, still a failure

    passed, description, details = run_check(
        515, repo_root=repo, tier="issue", branch="hotfix/restore-worker-queue"
    )

    assert passed is False
    assert "review" in description
    assert details["requiredArtifactSet"]["branchClass"] == "hotfix"
    assert details["requiredArtifactSet"]["narrowed"] == ["intentReview", "validation"]
    assert details["artifacts"]["review"]["required"] is True
    assert details["artifacts"]["intent_review"]["status"] == "skipped_by_tier"


def test_unresolvable_tier_fails_closed(patched_dirs: Path) -> None:
    repo = patched_dirs
    _write_child_cache(repo, required=ALL_RELAXED)
    _write_impl(repo)
    _write_intent_review(repo)
    _write_review(repo)
    _write_validation(repo)

    passed, description, details = run_check(
        515, repo_root=repo, tier="chaos-tier", branch=ISSUE_BRANCH
    )

    assert passed is False, "an unresolvable tier must fail, not fall back to permissive"
    assert "tier" in description.lower()
    assert details.get("requiredArtifactSet") is None


def test_unresolvable_tier_fails_even_with_everything_present(patched_dirs: Path) -> None:
    """Fail-closed is about the tier, not about the artifacts on disk."""
    repo = patched_dirs
    _write_child_cache(repo)
    _write_impl(repo)
    _write_intent_review(repo)
    _write_review(repo)
    _write_validation(repo)

    passed, _description, _details = run_check(
        515, repo_root=repo, tier="not-a-tier", branch=ISSUE_BRANCH
    )

    assert passed is False


# --- the CI-side helper in isolation ------------------------------------------


def test_compute_required_artifacts_issue_tier_requires_everything() -> None:
    computed = compute_required_artifacts("issue", ISSUE_BRANCH)

    assert computed.required == dict.fromkeys(ARTIFACT_KEYS, True)
    assert computed.narrowed == ()
    assert computed.reason is None
    assert computed.source == "ci-computed"


@pytest.mark.parametrize("tier", ["wave", "main"])
def test_compute_required_artifacts_aggregate_tiers_are_not_permissive(tier: str) -> None:
    computed = compute_required_artifacts(tier, "feature/w7-wave")

    assert computed.required == dict.fromkeys(ARTIFACT_KEYS, True)


@pytest.mark.parametrize("tier", [None, "", "issue-tier", "Issue", "unknown", 7])
def test_compute_required_artifacts_raises_on_unresolvable_tier(tier: Any) -> None:
    with pytest.raises(UnresolvableTierError):
        compute_required_artifacts(tier, ISSUE_BRANCH)


def test_compute_required_artifacts_narrowing_carries_a_reason() -> None:
    docs = compute_required_artifacts("issue", "docs/adr-080")
    hotfix = compute_required_artifacts("issue", "hotfix/prod-500s")

    assert docs.required["implementation"] is True
    assert docs.required["intentReview"] is False
    assert docs.reason and "docs" in docs.reason
    assert hotfix.required["review"] is True
    assert hotfix.required["validation"] is False
    assert hotfix.reason and "hotfix" in hotfix.reason


def test_resolve_tier_and_branch_mirrors_ci_classification() -> None:
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_BASE_REF": "feature/w7-wave",
        "GITHUB_HEAD_REF": "feature/issue-1439-required-artifacts-in-ci",
    }

    tier, branch = resolve_tier_and_branch(env=env)

    assert tier == "issue"
    assert branch == "feature/issue-1439-required-artifacts-in-ci"


def test_resolve_tier_and_branch_classifies_wave_push() -> None:
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": "feature/w7-wave"}

    tier, branch = resolve_tier_and_branch(env=env)

    assert tier == "wave"
    assert branch == "feature/w7-wave"


def test_resolve_tier_and_branch_classifies_push_to_main_as_main_tier() -> None:
    """`release.yml`'s flow, which was missing and took production down.

    The deploy pipeline runs on push to main and executes `pytest tests/`. With
    this flow unclassified, every merge to main raised UnresolvableTierError
    inside that run, `build` failed, `deploy` was skipped, and three merges sat
    undeployed — including a migration.

    `pr.yml` cannot catch it: its event is always `pull_request`, so the branch
    below is unreachable there. Same shape as #1447.
    """
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": "main"}

    tier, branch = resolve_tier_and_branch(env=env)

    assert tier == "main"
    assert branch == "main"


def test_resolve_tier_and_branch_classifies_push_to_staging_as_main_tier() -> None:
    """Staging is classified with main on the pull_request path; keep push in step.

    Splitting them would leave one workflow's event resolving and the other's
    raising for the same branch, which is exactly the asymmetry that produced
    the outage.
    """
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF_NAME": "staging"}

    tier, _branch = resolve_tier_and_branch(env=env)

    assert tier == "main"


def test_resolve_tier_and_branch_fails_closed_on_unsupported_ci_flow() -> None:
    env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF_NAME": "main", "CI": "true"}

    with pytest.raises(UnresolvableTierError):
        resolve_tier_and_branch(env=env)


def test_resolve_tier_and_branch_fails_closed_without_any_branch() -> None:
    with pytest.raises(UnresolvableTierError):
        resolve_tier_and_branch(env={}, branch_resolver=lambda: None)
