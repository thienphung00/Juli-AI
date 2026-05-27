#!/usr/bin/env python3
"""Gate: architectural changes include a new ADR."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    ADR_FILE_RE,
    REPO_ROOT,
    architectural_change_detected,
    git_changed_files,
    load_review_artifact,
    new_adr_files,
    parse_args,
    print_check_result,
    resolve_issue_number,
)


def validate_adr_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    if "**Status:**" not in text and "## Status" not in text:
        problems.append("missing Status")
    for section in ("## Context", "## Decision", "## Rationale", "## Consequences"):
        if section not in text:
            problems.append(f"missing {section}")
    return problems


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue) or {}
    changed = git_changed_files()
    arch_change = architectural_change_detected(review, changed)
    adrs = new_adr_files(changed)

    adr_problems: dict[str, list[str]] = {}
    for rel in adrs:
        path = REPO_ROOT / rel
        name = path.name
        if not ADR_FILE_RE.match(name):
            adr_problems[name] = ["filename must match NNN-slug.md"]
            continue
        problems = validate_adr_file(path)
        if problems:
            adr_problems[name] = problems

    details = {
        "architecturalChange": arch_change,
        "adrPresent": bool(adrs),
        "adrs": adrs,
        "adrProblems": adr_problems,
    }

    if not arch_change:
        return True, "No architectural change detected", details
    if not adrs:
        return False, "Architectural change requires new ADR in docs/decisions/", details
    if adr_problems:
        return False, "ADR file structure invalid", details
    return True, "ADR present for architectural change", details


def main() -> int:
    args = parse_args("Validate ADR requirement")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("adr_requirement", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
