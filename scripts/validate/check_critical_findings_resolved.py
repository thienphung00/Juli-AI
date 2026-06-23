#!/usr/bin/env python3
"""Gate: CRITICAL findings force FAIL; mandatory fail triggers block merge."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    derive_review_status,
    effective_mandatory_fail_reasons,
    load_review_artifact,
    mandatory_fail_reasons,
    merge_override_active,
    normalize_review_findings,
    overridden_merge_valid,
    parse_args,
    print_check_result,
    resolve_issue_number,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {}

    findings = normalize_review_findings(review)
    status = review.get("status")
    override_valid, override_issue = overridden_merge_valid(review)
    problems: list[str] = list(effective_mandatory_fail_reasons(review))

    critical = [f for f in findings if f.get("severity") == "CRITICAL"]
    if critical and status != "FAIL":
        problems.append(
            f"{len(critical)} CRITICAL finding(s) present but status is {status!r} (must be FAIL)"
        )

    action_required = [f for f in findings if f.get("actionRequired")]
    if action_required and status != "FAIL":
        problems.append(
            f"{len(action_required)} actionRequired finding(s) but status is {status!r} (must be FAIL)"
        )

    review_failures = int(review.get("reviewFailures", 0))
    if review_failures and status != "FAIL":
        problems.append(f"reviewFailures is {review_failures} but status is {status!r}")

    derived = derive_review_status(findings, review)
    if status != derived and not merge_override_active(review):
        problems.append(f"status {status!r} does not match derived {derived!r}")

    if status == "FAIL" and not merge_override_active(review):
        problems.append("review status is FAIL (blocks merge)")

    details = {
        "status": status,
        "derivedStatus": derived,
        "criticalCount": len(critical),
        "mandatoryFailReasons": mandatory_fail_reasons(review),
        "effectiveMandatoryFailReasons": effective_mandatory_fail_reasons(review),
        "overriddenMerge": review.get("overriddenMerge"),
        "mergeOverrideActive": merge_override_active(review),
        "problems": problems,
    }
    if override_valid:
        details["overrideValid"] = True
    elif override_issue:
        details["overrideValid"] = False
        details["overrideIssue"] = override_issue

    if problems:
        return False, problems[0], details
    if merge_override_active(review):
        return True, "FAIL status overridden with audited hotfix metadata", details
    return True, "No blocking CRITICAL findings or mandatory fail triggers", details


def main() -> int:
    args = parse_args("Validate critical findings resolved")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("critical_findings_resolved", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
