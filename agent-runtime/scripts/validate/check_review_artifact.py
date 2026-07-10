#!/usr/bin/env python3
"""Gate: review artifact exists and is structurally valid."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    derive_review_status,
    load_review_artifact,
    normalize_review_findings,
    parse_args,
    print_check_result,
    resolve_issue_number,
    review_status_issues,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {"path": f"agent-runtime/artifacts/reviews/review-issue-{issue}.json"}

    required = ("id", "issue", "status", "criticalFindings", "modulesTouched", "testCoverage")
    missing = [field for field in required if field not in review]
    if missing:
        return False, f"Missing fields: {', '.join(missing)}", {"missing": missing}

    status = review.get("status")
    if status not in {"PASS", "PASS_WITH_WARNINGS", "FAIL"}:
        return False, f"Invalid status: {status}", {}

    issues = review_status_issues(review)
    if issues:
        return False, issues[0], {"issues": issues}

    acceptance = review.get("testCoverage", {}).get("acceptance", {})
    for field in ("total", "mapped", "mappings"):
        if field not in acceptance:
            return False, f"testCoverage.acceptance missing {field}", {}

    findings = normalize_review_findings(review)
    derived = derive_review_status(findings, review)
    warning_count = sum(1 for f in findings if f.get("severity") == "WARNING")
    detail = f"Review artifact present; status {status}"
    if warning_count:
        detail += f" ({warning_count} gating warning(s))"
    return True, detail, {
        "status": status,
        "derivedStatus": derived,
        "warningCount": warning_count,
    }


def main() -> int:
    args = parse_args("Validate review artifact")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    detail = description if not passed else ""
    return print_check_result("review_artifact_present", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
