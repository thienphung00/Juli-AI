"""#1732 AC3 — `acceptance_criteria_mapped` derives its count from the issue
body, not from the artifact under review, and fails when the two disagree,
naming both numbers.

The gate calls `load_review_artifact` first and returns early ("Review
artifact missing") if it is None — stubbing only the issue-body lookup and
leaving `load_review_artifact` unstubbed makes every exhibit fail for the
wrong reason (a missing artifact, not a count mismatch). Both must be
stubbed for the three branches below to prove anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cam():
    """Import the gate behind its path shim, without an E402 suppression.

    A module-level sys.path.insert followed by a late import is an E402;
    silencing it adds a suppression identity the ratchet then carries forever.
    Deferring the import keeps the debt set unchanged.
    """
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "validate"))
    import check_acceptance_mapping

    return check_acceptance_mapping


# A real, stable pytest node that the gate's `pytest_node_exists` /
# `criterion_matches_test` checks can resolve — this very function, in this
# very file. Not "test_"-prefixed so pytest does not also collect it as a
# test in its own right; `pytest_node_exists` only requires a FunctionDef.
def acceptance_mapping_fixture_target() -> None:
    pass


FIXTURE_NODE = "tests/unit/test_check_acceptance_mapping.py::acceptance_mapping_fixture_target"


def _review(total: int, mapped: int) -> dict:
    mappings = [
        {"criterion": "Acceptance mapping fixture target", "test": FIXTURE_NODE}
        for _ in range(mapped)
    ]
    return {
        "testCoverage": {
            "acceptance": {
                "total": total,
                "mapped": mapped,
                "mappings": mappings,
                "unmapped": [],
            }
        }
    }


def test_lookup_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The issue body is unreadable (gh unavailable/unauthenticated/no
    section) — the gate must fail closed rather than trust the artifact's
    own count."""
    monkeypatch.setattr(_cam(), "load_review_artifact", lambda issue: _review(1, 1))
    monkeypatch.setattr(_cam(), "extract_criteria_count_from_issue_body", lambda issue: None)

    passed, message, details = _cam().run_check(1732)

    assert passed is False
    assert any("cannot read the acceptance-criteria count" in p for p in details["problems"])
    assert "issue_criteria_count" not in details


def test_count_matches_issue_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The middle case: a real count from the issue body that agrees with the
    artifact. Without this branch a gate that always fails looks identical to
    one that correctly fails closed."""
    monkeypatch.setattr(_cam(), "load_review_artifact", lambda issue: _review(1, 1))
    monkeypatch.setattr(_cam(), "extract_criteria_count_from_issue_body", lambda issue: 1)

    passed, message, details = _cam().run_check(1732)

    assert passed is True, details
    assert details["problems"] == []
    assert details["issue_criteria_count"] == 1


def test_count_disagrees_fails_naming_both_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhibit from the issue: total: 1 recorded against a three-criterion
    issue must fail, and the failure must name both numbers."""
    monkeypatch.setattr(_cam(), "load_review_artifact", lambda issue: _review(1, 1))
    monkeypatch.setattr(_cam(), "extract_criteria_count_from_issue_body", lambda issue: 3)

    passed, message, details = _cam().run_check(1732)

    assert passed is False
    problem = next(p for p in details["problems"] if "criteria count from issue" in p)
    assert "1" in problem
    assert "3" in problem
    assert details["issue_criteria_count"] == 3


# ---------------------------------------------------------------------------
# #1761 — the criteria-count fact becomes injectable, without ever letting
# production pass because the fact was withheld.
# ---------------------------------------------------------------------------


def _no_gh_available(*_args: object, **_kwargs: object) -> None:
    """Stand-in for a sandbox with no `gh` binary at all."""
    raise FileNotFoundError("gh: command not found")


def test_ac2_no_provider_and_gh_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2 (critical, ADR-092): with no provider registered for this issue and
    `gh` itself unavailable, the REAL (unstubbed) `extract_criteria_count_from_issue_body`
    must return None, and `run_check` must fail closed — never PASS, never SKIP,
    because the fact was unreachable. The seam must never become a way to make
    a gate green by withholding the fact."""
    cam = _cam()
    monkeypatch.delenv(cam.CRITERIA_COUNT_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(cam.subprocess, "run", _no_gh_available)

    # The seam itself, exercised directly and unstubbed.
    assert cam.extract_criteria_count_from_issue_body(1761) is None

    # And the gate that consumes it, end to end.
    monkeypatch.setattr(cam, "load_review_artifact", lambda issue: _review(1, 1))
    passed, message, details = cam.run_check(1761)

    assert passed is False
    assert any("cannot read the acceptance-criteria count" in p for p in details["problems"])
    assert "issue_criteria_count" not in details


def test_ac3_default_provider_is_the_real_gh_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: fails if the seam is removed, or its default stops being the real
    `gh` lookup. With no override registered, the seam must actually invoke
    `gh issue view <issue> ...` — not a canned answer, not a skip."""
    cam = _cam()
    monkeypatch.delenv(cam.CRITERIA_COUNT_OVERRIDE_ENV, raising=False)

    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = "## Acceptance criteria\n1. one\n2. two\n"

    def _spy_run(cmd: list[str], **_kwargs: object) -> _Result:
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(cam.subprocess, "run", _spy_run)

    result = cam.extract_criteria_count_from_issue_body(1761)

    assert calls, "the default path must call subprocess.run at all"
    assert calls[0][:3] == ["gh", "issue", "view"]
    assert "1761" in calls[0]
    assert result == 2


def test_harness_override_bypasses_gh_for_the_matching_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation harness's provider: an env-var override scoped to one
    synthetic issue, so the offline sweep can reach the record comparison
    without a live `gh` lookup. Registered via `criteria_count_override_env`,
    the same helper `eval/gate_scoring.py` calls."""
    cam = _cam()

    def _gh_must_not_be_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("gh must not be called when a matching override is registered")

    monkeypatch.setattr(cam.subprocess, "run", _gh_must_not_be_called)
    for key, value in cam.criteria_count_override_env(9_900_123, 4).items():
        monkeypatch.setenv(key, value)

    assert cam.extract_criteria_count_from_issue_body(9_900_123) == 4


def test_harness_override_ignored_for_a_different_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale override left over for one issue must never answer for another
    — the harness always scopes its provider to the exact synthetic issue."""
    cam = _cam()

    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = "## Acceptance criteria\n1. one\n"

    def _spy_run(cmd: list[str], **_kwargs: object) -> _Result:
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(cam.subprocess, "run", _spy_run)
    for key, value in cam.criteria_count_override_env(9_900_123, 4).items():
        monkeypatch.setenv(key, value)

    result = cam.extract_criteria_count_from_issue_body(9_900_999)

    assert calls, "a mismatched override must fall through to the real gh lookup"
    assert result == 1
