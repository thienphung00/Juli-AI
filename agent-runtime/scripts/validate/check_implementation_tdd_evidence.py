#!/usr/bin/env python3
"""Gate: TDD evidence on implementation artifact for in-scope code changes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    implementation_artifact_path,
    load_json,
    parse_args,
    print_check_result,
    resolve_issue_number,
)
from implementation_tdd import (  # noqa: E402
    EVIDENCE_STATE_RECONSTRUCTED,
    EVIDENCE_STATE_WITNESSED,
    evidence_state_counts,
    every_cycle_explicitly_unavailable,
    files_trigger_tdd_evidence,
    has_passing_command_evidence,
    has_witnessed_or_reconstructed_evidence,
    tests_added_or_updated,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    path = implementation_artifact_path(issue)
    if not path.exists():
        return (
            False,
            "Implementation artifact missing",
            {
                "path": f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json",
                "issueId": issue,
            },
        )

    artifact = load_json(path)
    requires_tdd, matched_paths = files_trigger_tdd_evidence(artifact.get("filesModified"))
    details: dict[str, Any] = {
        "issueId": issue,
        "requiresTddEvidence": requires_tdd,
        "matchedPaths": matched_paths,
    }

    if not requires_tdd:
        details["skipped"] = True
        return True, "No in-scope code changes — TDD evidence not required", details

    cycles = artifact.get("redGreenRefactorEvidence") or []
    details["cycleCount"] = len(cycles) if isinstance(cycles, list) else 0

    if not isinstance(cycles, list) or len(cycles) < 1:
        return False, "redGreenRefactorEvidence must contain at least one cycle", details

    if not has_passing_command_evidence(cycles):
        return False, "No redGreenRefactorEvidence cycle with passing command (exitCode 0)", details

    if not tests_added_or_updated(artifact):
        return False, "testsAdded and testsUpdated are both empty", details

    # #1603: witnessed / reconstructed / unavailable must not collapse into one
    # verdict — and "omitted" (a cycle written before evidenceState existed)
    # must not collapse into "unavailable" either. Omission is not a
    # declaration: an artifact that predates this field has asserted nothing,
    # whereas one that explicitly writes evidenceState: "unavailable" has
    # asserted it has no evidence. Reading the first as the second is the
    # ADR-093 error class ("could not determine" counted as an answer) and is
    # what made this gate fail every pre-#1603 artifact outright — the mutants
    # clean-record fixture and the public-release e2e matrices among them —
    # the moment it shipped. So: all-omitted (legacy) passes; all-explicitly-
    # unavailable still fails, exactly as before.
    state_counts = evidence_state_counts(cycles)
    details["evidenceStateCounts"] = state_counts

    witnessed = state_counts[EVIDENCE_STATE_WITNESSED]
    reconstructed = state_counts[EVIDENCE_STATE_RECONSTRUCTED]

    if not has_witnessed_or_reconstructed_evidence(cycles):
        if every_cycle_explicitly_unavailable(cycles):
            return (
                False,
                "redGreenRefactorEvidence has no witnessed or reconstructed cycle — "
                "every cycle explicitly declares evidenceState: unavailable, so there "
                "is no evidence of a real red state, only a claim",
                details,
            )
        # Every cycle omits evidenceState (a legacy shape predating this field,
        # possibly mixed with explicit `unavailable` cycles) — pass, but never
        # let it read as witnessed.
        details["evidenceQuality"] = "legacy"
        return (
            True,
            "TDD evidence present but predates evidenceState — this artifact was "
            "written before witnessed/reconstructed/unavailable existed and cannot "
            "be scored on it",
            details,
        )

    if reconstructed and not witnessed:
        details["evidenceQuality"] = "reconstructed"
        plural = "s" if reconstructed != 1 else ""
        return (
            True,
            f"TDD evidence present but reconstructed, not witnessed — "
            f"{reconstructed} cycle{plural} inferred from commit history/diff "
            "rather than observed this session",
            details,
        )

    if reconstructed and witnessed:
        details["evidenceQuality"] = "mixed"
        return (
            True,
            f"TDD evidence present: {witnessed} witnessed, {reconstructed} reconstructed cycle(s)",
            details,
        )

    details["evidenceQuality"] = "witnessed"
    # tokenUsage is optional telemetry for harness optimization — not a ship gate.
    return True, "TDD evidence present for in-scope code changes", details


def main() -> int:
    args = parse_args("Validate implementation TDD evidence")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result(
        "implementation_tdd_evidence", passed, description if not passed else ""
    )


if __name__ == "__main__":
    raise SystemExit(main())
