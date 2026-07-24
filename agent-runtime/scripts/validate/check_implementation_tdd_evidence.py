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
    files_trigger_tdd_evidence,
    has_passing_command_evidence,
    tests_added_or_updated,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    path = implementation_artifact_path(issue)
    if not path.exists():
        return False, "Implementation artifact missing", {
            "path": f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json",
            "issueId": issue,
        }

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

    duration = artifact.get("executionDurationMs")
    token_usage = artifact.get("tokenUsage") or {}
    total_tokens = token_usage.get("total") if isinstance(token_usage, dict) else None
    if isinstance(duration, int) and duration > 60000 and total_tokens == 0:
        return False, "tokenUsage.total is 0 for executionDurationMs > 60000", details

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
