#!/usr/bin/env python3
"""Gate: acceptance criteria mapped to real pytest nodes."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    criterion_matches_test,
    load_review_artifact,
    parse_args,
    print_check_result,
    pytest_node_exists,
    resolve_issue_number,
)


def extract_criteria_count_from_issue_body(issue: int) -> int | None:
    """Extract acceptance criteria count from GitHub issue body.

    Parses the "Acceptance criteria" section looking for numbered list items.
    Returns count of criteria, or None if unable to fetch/parse.
    """
    try:
        # Fetch issue body using gh
        result = subprocess.run(
            ["gh", "issue", "view", str(issue), "--json", "body", "-q", ".body"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        body = result.stdout
        if not body:
            return None

        # Find "Acceptance criteria" section and count numbered items
        # Pattern: lines starting with "1. ", "2. ", etc.
        lines = body.split("\n")
        in_acceptance = False
        criteria_count = 0

        for line in lines:
            # Check for "Acceptance criteria" header
            if "acceptance criteria" in line.lower():
                in_acceptance = True
                continue

            # If we hit another section header, stop
            if in_acceptance and line.strip() and line.startswith("#"):
                break

            # Count numbered list items (1., 2., etc.)
            if in_acceptance and re.match(r"^\d+\.\s", line):
                criteria_count += 1

        return criteria_count if criteria_count > 0 else None
    except Exception:
        return None


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {}

    acceptance = review.get("testCoverage", {}).get("acceptance", {})
    total = acceptance.get("total", 0)
    mapped = acceptance.get("mapped", 0)
    mappings = acceptance.get("mappings", [])
    unmapped = acceptance.get("unmapped", [])

    problems: list[str] = []

    # AC3: Compare artifact total against issue body criteria count (#1732)
    issue_criteria_count = extract_criteria_count_from_issue_body(issue)
    if issue_criteria_count is not None and total != issue_criteria_count:
        problems.append(
            f"acceptance total ({total}) != criteria count from issue ({issue_criteria_count})"
        )

    if total != mapped:
        problems.append(f"total ({total}) != mapped ({mapped})")
    if unmapped:
        problems.append(f"unmapped: {unmapped}")
    if len(mappings) != total:
        problems.append(f"mappings length ({len(mappings)}) != total ({total})")

    for entry in mappings:
        node = entry.get("test", "")
        criterion = entry.get("criterion", "")
        if not pytest_node_exists(node):
            problems.append(f"test not found: {node}")
            continue
        test_name = node.rsplit("::", 1)[-1]
        if not criterion_matches_test(criterion, test_name):
            problems.append(f"criterion/test name mismatch: {criterion!r} -> {test_name}")

    details: dict[str, Any] = {
        "total": total,
        "mapped": mapped,
        "unmapped": unmapped,
        "problems": problems,
    }
    if issue_criteria_count is not None:
        details["issue_criteria_count"] = issue_criteria_count

    if problems:
        return False, "Acceptance criteria mapping invalid", details
    return True, "All acceptance criteria mapped to tests", details


def main() -> int:
    args = parse_args("Validate acceptance criteria mapping")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    detail = ""
    if not passed and details.get("problems"):
        detail = "; ".join(details["problems"][:3])
    return print_check_result("acceptance_criteria_mapped", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
