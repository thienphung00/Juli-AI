"""Unit tests for reproducibility_audit — #1603 acceptance criterion 3.

"GIVEN the historical implementation artifacts WHEN they are re-examined THEN
the number whose red→green evidence cannot be reproduced is measured and
stated." The counting/tabulation logic is what's under test here; the actual
git-backed re-execution is already exercised end-to-end by
``tests/unit/test_differential_tdd.py`` (real pytest subprocesses against a
real base tree). Re-running that machinery per historical artifact here would
pay the same 11-19s subprocess cost dozens of times over for no new coverage,
so ``run_probe`` is injected and these tests supply a synthetic one — the
seam this module needs anyway so it can run against many artifacts quickly.

``differential_tdd`` and ``reproducibility_audit`` are imported lazily, inside
the two helpers below, rather than at module level after the ``sys.path``
setup. A module-level ``from reproducibility_audit import ...`` there would
need its own ``# noqa: E402`` — which the suppression ratchet
(``eval/ratchets.py``) counts as new debt for no functional reason (#1603
review). Same shape as ``eval/gate_scoring.py``'s ``_bootstrap_anchor_sha``
(#1540): importing inside a function sidesteps E402 entirely rather than
suppressing it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))


def _differential_tdd():
    import differential_tdd

    return differential_tdd


def _reproducibility_audit():
    import reproducibility_audit

    return reproducibility_audit


def _artifact(issue: int) -> dict[str, Any]:
    return {"issueId": issue, "redGreenRefactorEvidence": [{"cycle": 1}]}


def test_audit_tabulates_verdicts_and_counts_non_reproducible() -> None:
    dt = _differential_tdd()
    audit_artifacts = _reproducibility_audit().audit_artifacts
    verdicts = {
        1: dt.VERDICT_RED_GREEN,
        2: dt.VERDICT_RED_GREEN,
        3: dt.VERDICT_NO_DISCRIMINATION,
        4: dt.VERDICT_STILL_FAILING,
        5: dt.VERDICT_INCONCLUSIVE,
        6: dt.VERDICT_NOTHING_TO_PROBE,
    }
    artifacts = [(issue, _artifact(issue)) for issue in verdicts]

    result = audit_artifacts(artifacts, run_probe=lambda issue, _artifact: verdicts[issue])

    assert result["total"] == 6
    assert result["reproducible"] == 2
    assert result["notReproducible"] == 4
    assert result["counts"] == {
        dt.VERDICT_RED_GREEN: 2,
        dt.VERDICT_NO_DISCRIMINATION: 1,
        dt.VERDICT_STILL_FAILING: 1,
        dt.VERDICT_INCONCLUSIVE: 1,
        dt.VERDICT_NOTHING_TO_PROBE: 1,
    }
    assert result["perIssue"] == verdicts


def test_audit_of_nothing_reports_zero_not_a_crash() -> None:
    dt = _differential_tdd()
    audit_artifacts = _reproducibility_audit().audit_artifacts
    result = audit_artifacts([], run_probe=lambda issue, artifact: dt.VERDICT_RED_GREEN)
    assert result == {
        "total": 0,
        "reproducible": 0,
        "notReproducible": 0,
        "counts": {},
        "perIssue": {},
    }


def test_all_reproducible_reports_zero_not_reproducible() -> None:
    dt = _differential_tdd()
    audit_artifacts = _reproducibility_audit().audit_artifacts
    artifacts = [(i, _artifact(i)) for i in range(1, 4)]
    result = audit_artifacts(artifacts, run_probe=lambda issue, artifact: dt.VERDICT_RED_GREEN)
    assert result["notReproducible"] == 0
    assert result["reproducible"] == 3


def test_audit_directory_scans_implementation_artifact_files(tmp_path: Path) -> None:
    """The count must come from real files on disk, not a hand-built list."""
    dt = _differential_tdd()
    audit_directory = _reproducibility_audit().audit_directory
    (tmp_path / "implementation-issue-101.json").write_text(json.dumps(_artifact(101)))
    (tmp_path / "implementation-issue-202.json").write_text(json.dumps(_artifact(202)))
    (tmp_path / "not-an-artifact.json").write_text("{}")

    seen: list[int] = []

    def _probe(issue: int, _artifact: dict[str, Any]) -> str:
        seen.append(issue)
        return dt.VERDICT_RED_GREEN if issue == 101 else dt.VERDICT_STILL_FAILING

    result = audit_directory(tmp_path, run_probe=_probe)

    assert sorted(seen) == [101, 202]
    assert result["total"] == 2
    assert result["reproducible"] == 1
    assert result["notReproducible"] == 1
    assert result["perIssue"] == {101: dt.VERDICT_RED_GREEN, 202: dt.VERDICT_STILL_FAILING}


def test_audit_directory_that_does_not_exist_reports_zero() -> None:
    """No historical artifacts on this machine is a real, honest zero — not an error."""
    dt = _differential_tdd()
    audit_directory = _reproducibility_audit().audit_directory
    result = audit_directory(
        Path("/no/such/directory-for-1603"), run_probe=lambda i, a: dt.VERDICT_RED_GREEN
    )
    assert result["total"] == 0
