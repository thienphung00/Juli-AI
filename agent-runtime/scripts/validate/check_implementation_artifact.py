#!/usr/bin/env python3
"""Gate: implementation artifact exists and has required runtime fields."""

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

REQUIRED_FIELDS = (
    "issueId",
    "executorDomain",
    "phaseRunId",
    "executionDurationMs",
    "toolInvocationCount",
    "tokenUsage",
    "contextFilesLoaded",
    "skillsLoaded",
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    path = implementation_artifact_path(issue)
    if not path.exists():
        return False, "Implementation artifact missing", {
            "path": f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json"
        }

    artifact = load_json(path)
    missing = [field for field in REQUIRED_FIELDS if field not in artifact]
    if missing:
        return False, f"Missing fields: {', '.join(missing)}", {"missing": missing}

    if artifact.get("issueId") != issue:
        return False, f"issueId mismatch: expected {issue}", {"issueId": artifact.get("issueId")}

    domain = artifact.get("executorDomain")
    if domain not in {"ui-ux", "backend", "data-platform", "machine-learning"}:
        return False, f"Invalid executorDomain: {domain}", {}

    return True, f"Implementation artifact present; domain {domain}", {
        "executorDomain": domain,
        "phaseRunId": artifact.get("phaseRunId"),
        "executionDurationMs": artifact.get("executionDurationMs"),
    }


def main() -> int:
    args = parse_args("Validate implementation artifact")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    detail = description if not passed else ""
    return print_check_result("implementation_artifact_present", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
