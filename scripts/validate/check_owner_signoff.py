#!/usr/bin/env python3
"""Gate: timestamped owner signoff when review has gating warnings."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    load_review_artifact,
    owner_signoff_valid,
    parse_args,
    print_check_result,
    resolve_issue_number,
    warnings_require_signoff,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {}

    if not warnings_require_signoff(review):
        return True, "Owner signoff not required (no gating warnings)", {"required": False}

    valid, problem = owner_signoff_valid(review)
    signoff = review.get("ownerSignoff") or {}
    details = {
        "required": True,
        "hasStatement": bool(signoff.get("statement")),
        "hasTimestamp": bool(signoff.get("timestamp")),
        "acknowledged": signoff.get("acknowledged"),
    }
    if not valid:
        return False, problem, details
    return True, "Owner signoff present", details


def main() -> int:
    args = parse_args("Validate owner signoff")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("owner_signoff_present", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
