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
