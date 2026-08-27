"""Blocking vs advisory gate split in generate_validation_artifact.py (issue #1076).

`unpushed_issue_work` is a repo-wide gate: it reports on stale branches and
worktrees that belong to no slice in flight, and a slice author cannot fix it
from inside a single worktree. Before this split, one repo-wide FAIL made
every issue's validation artifact FAIL and `readyForMerge: false` for reasons
no author could act on. These tests pin the fix so it cannot quietly widen
into a way to hide a real failure:

- the advisory set is a single named constant with exactly one member
- `status`/`readyForMerge` are computed from blocking gates only
- a blocking FAIL still fails the artifact (the split must not weaken real
  gates)
- an advisory-only FAIL still shows up, in full, in `checks` and in the new
  `advisoryFailures` record
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))

from generate_validation_artifact import (  # noqa: E402
    ADVISORY_CHECKS,
    CHECKS,
    build_artifact,
)


def _result(name: str, status: str, description: str = "") -> dict:
    return {
        "name": name,
        "status": status,
        "description": description or f"{name} {status.lower()}",
        "details": {},
    }


def _all_passing_results() -> list[dict]:
    return [_result(name, "PASS") for name, _ in CHECKS]


def test_advisory_checks_set_is_pinned_to_exactly_unpushed_issue_work() -> None:
    """The advisory set is a named, explicit constant — not a predicate.

    Any addition (or removal) must fail this test, so widening the set into a
    way to hide a real failure requires a human to touch this line.
    """
    assert ADVISORY_CHECKS == frozenset({"unpushed_issue_work", "differential_tdd"})


def test_advisory_check_name_is_a_real_registered_gate() -> None:
    check_names = {name for name, _ in CHECKS}
    assert ADVISORY_CHECKS <= check_names


def test_blocking_fail_still_fails_status_and_blocks_merge() -> None:
    results = _all_passing_results()
    for entry in results:
        if entry["name"] == "module_boundaries":
            entry["status"] = "FAIL"
            entry["description"] = "boundary violation"

    artifact = build_artifact(1076, results, review=None)

    assert artifact["status"] == "FAIL"
    assert artifact["readyForMerge"] is False
    # The failing blocking check is still fully visible.
    failing = [c for c in artifact["checks"] if c["name"] == "module_boundaries"]
    assert failing[0]["status"] == "FAIL"


def test_advisory_only_fail_still_passes_status_and_allows_merge() -> None:
    results = _all_passing_results()
    for entry in results:
        if entry["name"] == "unpushed_issue_work":
            entry["status"] = "FAIL"
            entry["description"] = "3 stale unpushed branch(es)"

    artifact = build_artifact(1076, results, review=None)

    assert artifact["status"] == "PASS"
    assert artifact["readyForMerge"] is True
    # Advisory record is non-empty and carries the real failure.
    assert artifact["advisoryFailures"], "advisory failure must be recorded, not dropped"
    assert artifact["advisoryFailures"][0]["name"] == "unpushed_issue_work"
    # And the check is still visible in full within `checks`, not hidden.
    reported = [c for c in artifact["checks"] if c["name"] == "unpushed_issue_work"]
    assert len(reported) == 1
    assert reported[0]["status"] == "FAIL"
    assert reported[0]["description"] == "3 stale unpushed branch(es)"
    # A reader must be able to tell the repo is untidy from the summary alone.
    assert "unpushed_issue_work" in artifact["overallSummary"]


def test_advisory_pass_yields_empty_advisory_failures() -> None:
    artifact = build_artifact(1076, _all_passing_results(), review=None)

    assert artifact["status"] == "PASS"
    assert artifact["readyForMerge"] is True
    assert artifact["advisoryFailures"] == []


def test_advisory_and_blocking_both_fail_status_is_fail() -> None:
    results = _all_passing_results()
    for entry in results:
        if entry["name"] in ("unpushed_issue_work", "module_boundaries"):
            entry["status"] = "FAIL"

    artifact = build_artifact(1076, results, review=None)

    assert artifact["status"] == "FAIL"
    assert artifact["readyForMerge"] is False
    assert len(artifact["advisoryFailures"]) == 1
    assert artifact["advisoryFailures"][0]["name"] == "unpushed_issue_work"


# --- #1143: phase_run_correlation must see THIS generation's file ------------


def test_phase_run_correlation_runs_against_the_artifact_this_run_writes(
    tmp_path, monkeypatch
) -> None:
    """The read-before-write off-by-one (#1143).

    `check_phase_run_correlation` loads `validation-issue-<N>.json` off disk,
    but the generator used to run every gate BEFORE writing that file — so the
    gate always judged the PREVIOUS generation's artifact (or its absence, on
    a first-ever run, failing with `phaseRunId None != canonical` even when
    every artifact already agreed). This test simulates exactly that
    first-ever run: no validation file exists, every other gate passes, and a
    recording stand-in for phase_run_correlation asserts the on-disk file
    already exists AND carries this run's phaseRunId at the moment the gate
    executes. Pre-fix this fails: the gate ran first and found nothing.
    """
    import generate_validation_artifact as gva

    canonical = "9999-20260817T000000"
    review = {"phaseRunId": canonical, "status": "PASS", "testCoverage": {}}
    seen: dict = {}

    def fake_load_checker(script_name: str):
        def _passing(issue: int):
            return True, "stub pass", {}

        def _recording(issue: int):
            out = tmp_path / f"validation-issue-{issue}.json"
            seen["existed"] = out.exists()
            if out.exists():
                import json

                seen["phaseRunId"] = json.loads(out.read_text()).get("phaseRunId")
            return True, "recorded", {}

        if script_name == "check_phase_run_correlation.py":
            return _recording
        return _passing

    monkeypatch.setattr(gva, "load_checker", fake_load_checker)
    monkeypatch.setattr(gva, "VALIDATION_DIR", tmp_path)
    monkeypatch.setattr(gva, "load_review_artifact", lambda issue: review)
    monkeypatch.setattr(gva, "resolve_issue_number", lambda raw: 9999)
    monkeypatch.setattr(sys, "argv", ["generate_validation_artifact.py", "--issue", "9999"])

    assert gva.main() == 0

    assert seen.get("existed") is True, (
        "phase_run_correlation ran before the validation artifact was written "
        "— it judged the previous generation's file (#1143)"
    )
    assert seen.get("phaseRunId") == canonical, (
        f"gate saw phaseRunId {seen.get('phaseRunId')!r}, not this run's {canonical!r}"
    )

    # And the final artifact still contains the gate's own result, in the
    # registry position, with counters that include it.
    import json

    final = json.loads((tmp_path / "validation-issue-9999.json").read_text())
    names = [c["name"] for c in final["checks"]]
    assert names == [name for name, _ in gva.CHECKS], (
        "two-pass generation must not reorder or drop gate results"
    )
    assert final["passedChecks"] == len(gva.CHECKS)
