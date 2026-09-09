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
        return (
            False,
            "Review artifact missing",
            {"path": f"agent-runtime/artifacts/reviews/review-issue-{issue}.json"},
        )

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

    # AC4: A review claiming PASS must have recorded a test run (#1732)
    if status in {"PASS", "PASS_WITH_WARNINGS"}:
        dynamic_tests_executed = review.get("dynamicTestsExecuted")

        # If field is absent or false, PASS is invalid
        if dynamic_tests_executed is not True:
            return (
                False,
                (
                    f"status {status} but dynamicTestsExecuted is {dynamic_tests_executed}; "
                    "a PASS claim requires evidence of test execution"
                ),
                {
                    "status": status,
                    "dynamicTestsExecuted": dynamic_tests_executed,
                },
            )

        # If tests executed, unit counts must show at least one test ran
        unit = review.get("testCoverage", {}).get("unit", {})
        passed = unit.get("passed", 0)
        failed = unit.get("failed", 0)

        if passed == 0 and failed == 0:
            return (
                False,
                (
                    f"status {status} and dynamicTestsExecuted: true, but unit tests "
                    "{passed: 0, failed: 0} — no tests actually ran"
                ),
                {
                    "status": status,
                    "dynamicTestsExecuted": dynamic_tests_executed,
                    "unitPassed": passed,
                    "unitFailed": failed,
                },
            )

    findings = normalize_review_findings(review)
    derived = derive_review_status(findings, review)
    warning_count = sum(1 for f in findings if f.get("severity") == "WARNING")
    detail = f"Review artifact present; status {status}"
    if warning_count:
        detail += f" ({warning_count} gating warning(s))"
    return (
        True,
        detail,
        {
            "status": status,
            "derivedStatus": derived,
            "warningCount": warning_count,
        },
    )


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
