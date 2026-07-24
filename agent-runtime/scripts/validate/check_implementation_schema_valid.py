#!/usr/bin/env python3
"""Gate: implementation artifact validates against implementation-artifact JSON Schema."""

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
from implementation_schema import validate_implementation_artifact  # noqa: E402


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    path = implementation_artifact_path(issue)

    if not path.exists():
        return False, "Implementation artifact missing", {
            "path": f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json",
            "issueId": issue,
        }

    artifact = load_json(path)
    if artifact.get("issueId") != issue:
        return False, f"issueId mismatch: expected {issue}", {
            "issueId": artifact.get("issueId"),
        }

    result = validate_implementation_artifact(artifact)
    details: dict[str, Any] = {
        "issueId": issue,
        "path": f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json",
        "valid": result["valid"],
        "errors": result["errors"],
    }

    if not result["valid"]:
        return False, "Implementation artifact fails JSON Schema validation", details

    return True, "Implementation artifact schema-valid", details


def main() -> int:
    args = parse_args("Validate implementation artifact JSON Schema")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result(
        "implementation_schema_valid", passed, description if not passed else ""
    )


if __name__ == "__main__":
    raise SystemExit(main())
