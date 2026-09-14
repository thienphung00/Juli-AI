"""Unit tests for the single owning phaseRunId helper (#1881).

`check_phase_run_correlation` requires every phase artifact to carry the same
`phaseRunId`, but nothing assigned one -- each generator invented its own
convention, so two separate agent sessions (Executor/Meta writing the
implementation artifact, Review writing intent-review/review/validation)
never agreed and the gate failed closed on every slice.

The fix: one helper, `derive_phase_run_id`, computes the id from something
both phases can independently observe -- the issue number plus the git HEAD
sha under review -- and every template takes it from there instead of
inventing a value.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"


def _ci_imports():
    """Import from `agent-runtime/scripts/ci`/`validate` lazily, inside a function.

    A module-level import after a `sys.path` insert needs `# noqa: E402`, which
    the suppression ratchet counts as new debt. #1540 solved this in
    `eval/gate_scoring.py::_bootstrap_anchor_sha` by moving the import into a
    function, and E402 does not apply inside a function body at all --
    `test_evidence_state_schema.py::_ci_imports` reuses the same fix.
    """
    for path in (CI_DIR, VALIDATE_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import common
    from check_phase_run_correlation import run_check

    return common, run_check


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo_with_commit(repo: Path, *, message: str = "initial") -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "file.txt").write_text(message, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return sha


# --- derive_phase_run_id itself ------------------------------------------


def test_derive_phase_run_id_embeds_issue_and_head_sha(tmp_path: Path) -> None:
    common, _ = _ci_imports()
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo)

    phase_run_id = common.derive_phase_run_id(1881, repo_root=repo)

    assert isinstance(phase_run_id, str)
    assert phase_run_id.startswith("1881-")
    assert phase_run_id.split("-", 1)[1] == sha[:12]


def test_derive_phase_run_id_is_stable_across_independent_calls(tmp_path: Path) -> None:
    """Two calls that never talk to each other still agree (the whole point)."""
    common, _ = _ci_imports()
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo)

    first = common.derive_phase_run_id(1881, repo_root=repo)
    second = common.derive_phase_run_id(1881, repo_root=repo)

    assert first == second


def test_derive_phase_run_id_changes_with_head_sha(tmp_path: Path) -> None:
    """A genuinely different run (different head) must not silently agree."""
    common, _ = _ci_imports()
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo, message="first")
    first_id = common.derive_phase_run_id(1881, repo_root=repo)

    (repo / "file.txt").write_text("second", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")
    second_id = common.derive_phase_run_id(1881, repo_root=repo)

    assert first_id != second_id


def test_derive_phase_run_id_records_unavailable_shape_when_sha_unresolvable(
    tmp_path: Path,
) -> None:
    """No git repo at all: the repo's unavailable shape, not an invented value."""
    common, _ = _ci_imports()
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()

    result = common.derive_phase_run_id(1881, repo_root=not_a_repo)

    assert isinstance(result, dict)
    assert result["available"] is False
    assert isinstance(result["reason"], str) and result["reason"]


# --- single owning helper: every builder takes it from there -------------


def test_every_builder_takes_phase_run_id_from_the_shared_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if any template computes its own id instead of calling the helper.

    Patches the shared helper to a sentinel and asserts every builder's
    default output carries exactly that sentinel -- a template with its own
    id-generation logic would not.
    """
    common, _ = _ci_imports()
    sentinel = "SENTINEL-PHASE-RUN-ID"
    monkeypatch.setattr(common, "derive_phase_run_id", lambda *a, **k: sentinel)

    implementation = common.build_implementation_artifact(1881, "backend")
    review = common.build_review_artifact(1881)
    intent_review = common.build_intent_review_artifact(1881)

    assert implementation["phaseRunId"] == sentinel
    assert review["phaseRunId"] == sentinel
    assert intent_review["phaseRunId"] == sentinel


def test_builders_agree_when_neither_is_given_an_explicit_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real end-to-end property: two independent builder calls for the
    same issue and repo state agree without either being told the other's id.
    """
    common, _ = _ci_imports()
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo)
    monkeypatch.setattr(common, "REPO_ROOT", repo)

    implementation = common.build_implementation_artifact(1881, "backend")
    review = common.build_review_artifact(1881)
    intent_review = common.build_intent_review_artifact(1881)

    assert implementation["phaseRunId"] == review["phaseRunId"]
    assert implementation["phaseRunId"] == intent_review["phaseRunId"]


# --- explicit override and existing-value precedence still work ----------


def test_explicit_phase_run_id_still_wins_over_derivation() -> None:
    common, _ = _ci_imports()
    implementation = common.build_implementation_artifact(
        1881, "backend", phase_run_id="explicit-id"
    )
    assert implementation["phaseRunId"] == "explicit-id"


def test_existing_phase_run_id_is_preserved_on_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common, _ = _ci_imports()
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo)
    monkeypatch.setattr(common, "REPO_ROOT", repo)
    existing: dict[str, Any] = {"issue": 1881, "phaseRunId": "already-recorded"}

    review = common.build_review_artifact(1881, existing=existing)

    assert review["phaseRunId"] == "already-recorded"


# --- the gate: genuinely different runs still fail closed, naming both ---


def test_gate_fails_when_derived_ids_genuinely_disagree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common, run_check = _ci_imports()

    repo_a = tmp_path / "repo-a"
    _init_repo_with_commit(repo_a, message="run-a")
    repo_b = tmp_path / "repo-b"
    _init_repo_with_commit(repo_b, message="run-b")

    impl_id = common.derive_phase_run_id(1881, repo_root=repo_a)
    review_id = common.derive_phase_run_id(1881, repo_root=repo_b)
    assert impl_id != review_id

    fixture_repo = tmp_path / "fixture"
    base = fixture_repo / "agent-runtime" / "artifacts"
    monkeypatch.setattr(common, "REPO_ROOT", fixture_repo)
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", base / "implementations")
    monkeypatch.setattr(common, "INTENT_REVIEWS_DIR", base / "intent-reviews")
    monkeypatch.setattr(common, "REVIEWS_DIR", base / "reviews")
    monkeypatch.setattr(common, "VALIDATION_DIR", base / "validation")

    cache_dir = fixture_repo / "agent-runtime" / "artifacts" / "workflow-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "issue-context-cache-1881.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.2.0",
                "artifactType": "issue_context_cache",
                "issueId": 1881,
                "parentIssueId": 1434,
                "issueLoadProfile": {"executorDomain": "backend"},
            }
        ),
        encoding="utf-8",
    )

    common.write_json(
        base / "implementations" / "implementation-issue-1881.json",
        common.build_implementation_artifact(1881, "backend", phase_run_id=impl_id),
    )
    common.write_json(
        base / "intent-reviews" / "intent-review-issue-1881.json",
        common.build_intent_review_artifact(1881, phase_run_id=review_id),
    )
    common.write_json(
        base / "reviews" / "review-issue-1881.json",
        common.build_review_artifact(1881, phase_run_id=review_id),
    )
    common.write_json(
        base / "validation" / "validation-issue-1881.json",
        {"issue": 1881, "phaseRunId": review_id},
    )

    passed, description, details = run_check(
        1881,
        repo_root=fixture_repo,
        tier="issue",
        branch="feature/issue-1881-shared-phase-run-id",
    )

    assert passed is False
    assert impl_id in description or impl_id in str(details)
    assert review_id in description
