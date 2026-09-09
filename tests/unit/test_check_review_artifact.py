"""#1761 — `check_review_artifact` needs no external fact-provider seam.

Unlike `check_acceptance_mapping`, every fact this gate's AC4 branch
(#1732 — "a PASS claim requires evidence of test execution") reads —
`dynamicTestsExecuted`, `testCoverage.unit.{passed,failed}` — lives inside the
review artifact body itself. The mutation harness's fixture writes that body
directly, so it can supply the fact with no injection mechanism at all: the
fix for the mutation harness losing `self_reported_pass` sensitivity is in the
fixture's clean baseline (`eval/artifact_mutants.py::_clean_review`), not in
this gate. These tests pin that: the gate is exercised end to end with a
fully-formed, in-process artifact, and never touches `gh` or any other
external resource.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cra():
    """Import the gate behind its path shim, without an E402 suppression."""
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "validate"))
    import check_review_artifact

    return check_review_artifact


def _base_review(**overrides: object) -> dict:
    review = {
        "id": "review-issue-1761",
        "issue": 1761,
        "status": "PASS",
        "criticalFindings": [],
        "modulesTouched": [],
        "testCoverage": {
            "acceptance": {"total": 0, "mapped": 0, "mappings": [], "unmapped": []},
            "unit": {"passed": 6, "failed": 0},
        },
        "dynamicTestsExecuted": True,
    }
    review.update(overrides)
    return review


def test_pass_with_no_dynamic_tests_executed_fails_closed(monkeypatch) -> None:
    """AC4 of #1732, still enforced: a PASS with no recorded test run fails,
    with no external lookup involved at all."""
    cra = _cra()
    monkeypatch.setattr(
        cra, "load_review_artifact", lambda issue: _base_review(dynamicTestsExecuted=None)
    )

    passed, message, details = cra.run_check(1761)

    assert passed is False
    assert "dynamicTestsExecuted" in message


def test_pass_with_dynamic_tests_executed_and_real_counts_passes(monkeypatch) -> None:
    """The fixture-suppliable fact, present: the gate reaches PASS with no
    provider seam of any kind."""
    cra = _cra()
    monkeypatch.setattr(cra, "load_review_artifact", lambda issue: _base_review())

    passed, message, details = cra.run_check(1761)

    assert passed is True, details


def test_self_reported_pass_is_caught_once_dynamic_tests_executed_is_present(monkeypatch) -> None:
    """The exact shape of the `self_reported_pass` mutant (#1457): status PASS
    asserted over the record's own unresolved CRITICAL finding. Reachable
    only once `dynamicTestsExecuted` stops being the reason for an early,
    uninformative fail — proving the fixture fix (not a gate change) is what
    restores this gate's `self_reported_pass` sensitivity."""
    cra = _cra()
    review = _base_review(
        criticalFindings=[
            {
                "id": "F-1",
                "type": "test_gap",
                "module": "eval",
                "description": "unresolved",
                "severity": "CRITICAL",
                "actionRequired": True,
            }
        ]
    )
    monkeypatch.setattr(cra, "load_review_artifact", lambda issue: review)

    passed, message, details = cra.run_check(1761)

    assert passed is False
    assert "derived" in message
