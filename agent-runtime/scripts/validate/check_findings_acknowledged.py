#!/usr/bin/env python3
"""Gate: every gating WARNING finding has reviewer acceptance and owner ack."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    load_review_artifact,
    normalize_review_findings,
    parse_args,
    print_check_result,
    resolve_issue_number,
    unacknowledged_findings,
    warning_findings,
    warnings_require_signoff,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {}

    findings = normalize_review_findings(review)
    warnings = warning_findings(findings)
    if not warnings_require_signoff(review):
        return True, "No gating warnings (signoff not required)", {
            "warningCount": len(warnings),
            "required": False,
        }

    pending = unacknowledged_findings(findings)
    details = {
        "warningCount": len(warnings),
        "unacknowledgedCount": len(pending),
        "unacknowledged": [
            {
                "description": f.get("description", "")[:120],
                "acceptanceByReviewer": f.get("acceptanceByReviewer"),
                "ownerAck": f.get("ownerAck"),
                "fixedInCommit": f.get("fixedInCommit"),
                "shipAsIsReason": bool(f.get("shipAsIsReason")),
            }
            for f in pending
        ],
    }
    if pending:
        return (
            False,
            f"{len(pending)} WARNING finding(s) missing acceptanceByReviewer, ownerAck, "
            "and fixedInCommit or shipAsIsReason",
            details,
        )
    return True, f"All {len(warnings)} WARNING finding(s) acknowledged", details


def main() -> int:
    args = parse_args("Validate findings acknowledged")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("findings_acknowledged", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
