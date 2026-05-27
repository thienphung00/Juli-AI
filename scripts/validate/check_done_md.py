#!/usr/bin/env python3
"""Gate: root done.md required checklist is complete."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    DONE_MD,
    parse_args,
    print_check_result,
    resolve_issue_number,
)

REQUIRED_SECTION_RE = re.compile(r"^##\s+Required\b", re.MULTILINE | re.IGNORECASE)
UNCHECKED_RE = re.compile(r"^\s*-\s+\[\s\]\s+", re.MULTILINE)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:  # noqa: ARG001
    if not DONE_MD.exists():
        return False, "done.md missing at repository root", {"unchecked": ["done.md missing"]}

    text = DONE_MD.read_text(encoding="utf-8")
    section_match = REQUIRED_SECTION_RE.search(text)
    if not section_match:
        return False, "done.md missing ## Required section", {"unchecked": ["## Required section"]}

    required_body = text[section_match.end() :]
    next_section = re.search(r"\n##\s+", required_body)
    if next_section:
        required_body = required_body[: next_section.start()]

    unchecked = UNCHECKED_RE.findall(required_body)
    unchecked_items = [
        line.strip()
        for line in required_body.splitlines()
        if line.strip().startswith("- [ ]")
    ]

    details = {"unchecked": unchecked_items}
    if unchecked_items:
        return False, f"{len(unchecked_items)} required item(s) unchecked", details
    return True, "done.md required checklist complete", details


def main() -> int:
    args = parse_args("Validate done.md")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    detail = ""
    if details.get("unchecked"):
        detail = f"{len(details['unchecked'])} unchecked"
    return print_check_result("done_md_completion", passed, detail or description)


if __name__ == "__main__":
    raise SystemExit(main())
