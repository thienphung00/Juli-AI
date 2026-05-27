#!/usr/bin/env python3
"""Gate: review artifact exists and status is mergeable."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    load_review_artifact,
    parse_args,
    print_check_result,
    resolve_issue_number,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {"path": f"artifacts/reviews/review-issue-{issue}.json"}

    required = ("id", "issue", "status", "criticalFindings", "modulesTouched", "testCoverage")
    missing = [field for field in required if field not in review]
    if missing:
        return False, f"Missing fields: {', '.join(missing)}", {"missing": missing}

    status = review.get("status")
    if status not in {"PASS", "PASS_WITH_WARNINGS", "FAIL"}:
        return False, f"Invalid status: {status}", {}

    critical = [
        f for f in review.get("criticalFindings", []) if f.get("severity") == "CRITICAL"
    ]
    if critical and status != "FAIL":
        return (
            False,
            "CRITICAL findings present but status is not FAIL",
            {"criticalCount": len(critical)},
        )
    if status == "FAIL":
        return False, "Review status is FAIL", {"status": status}

    acceptance = review.get("testCoverage", {}).get("acceptance", {})
    for field in ("total", "mapped", "mappings"):
        if field not in acceptance:
            return False, f"testCoverage.acceptance missing {field}", {}

    return True, "Review artifact present and structurally valid", {"status": status}


def main() -> int:
    args = parse_args("Validate review artifact")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    return print_check_result("review_artifact_present", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
