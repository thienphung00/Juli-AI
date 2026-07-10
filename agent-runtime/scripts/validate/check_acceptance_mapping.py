#!/usr/bin/env python3
"""Gate: acceptance criteria mapped to real pytest nodes."""

from __future__ import annotations

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

    details = {"total": total, "mapped": mapped, "unmapped": unmapped, "problems": problems}
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
