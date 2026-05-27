#!/usr/bin/env python3
"""Gate: handoff registry files have required structure when present on branch."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    git_changed_files,
    handoff_files_on_branch,
    parse_architecture_map,
    parse_args,
    print_check_result,
    resolve_issue_number,
)


REQUIRED_MARKERS = ("status", "modules", "bootstrap")


def validate_handoff(path: Path, modules: dict) -> list[str]:
    text = path.read_text(encoding="utf-8").lower()
    problems: list[str] = []
    for marker in REQUIRED_MARKERS:
        if marker not in text:
            problems.append(f"missing section marker: {marker}")
    if "| modules |" not in text and "modules" not in text:
        problems.append("modules table/column not found")
    return problems


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:  # noqa: ARG001
    changed = git_changed_files()
    handoffs = handoff_files_on_branch(changed)
    if not handoffs:
        return True, "No handoff on branch (skipped)", {"required": False, "missingFields": []}

    modules = parse_architecture_map()
    all_problems: dict[str, list[str]] = {}
    for path in handoffs:
        problems = validate_handoff(path, modules)
        if problems:
            all_problems[path.name] = problems

    details = {"required": True, "missingFields": all_problems, "files": [p.name for p in handoffs]}
    if all_problems:
        return False, "Handoff structure invalid", details
    return True, "Handoff structure valid", details


def main() -> int:
    args = parse_args("Validate handoff documents")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, _, details = run_check(issue)
    detail = ""
    if details.get("missingFields"):
        detail = str(details["missingFields"])
    return print_check_result("handoff_structure", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
