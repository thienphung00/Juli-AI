#!/usr/bin/env python3
"""Gate: timestamped reviewer signoff when review has gating warnings."""

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
    reviewer_signoff_valid,
    warnings_require_signoff,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {}

    if not warnings_require_signoff(review):
        return True, "Reviewer signoff not required (no gating warnings)", {"required": False}

    valid, problem = reviewer_signoff_valid(review)
    signoff = review.get("reviewerSignoff") or {}
    details = {
        "required": True,
        "hasStatement": bool(signoff.get("statement")),
        "hasTimestamp": bool(signoff.get("timestamp")),
        "acceptedRisks": signoff.get("acceptedRisks"),
    }
    if not valid:
        return False, problem, details
    return True, "Reviewer signoff present", details


def main() -> int:
    args = parse_args("Validate reviewer signoff")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("reviewer_signoff_present", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
