#!/usr/bin/env python3
"""Gate: cached authorityChain matches live upstream sources at session entry."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    REPO_ROOT,
    parse_args,
    print_check_result,
    resolve_issue_number,
)
from scope_precedence import validate_authority_chain  # noqa: E402
from workflow_cache_linkage import resolve_handoff_path, resolve_slice_id  # noqa: E402
from workflow_cache_store import load_parent_child_caches  # noqa: E402


def run_check(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    child_cache, parent_cache, _, _, error = load_parent_child_caches(
        issue, repo_root, config=config
    )
    if error:
        resolution = "refresh_issue_cache"
        if error.startswith("Parent cache missing"):
            resolution = "refresh_epic_cache"
        return False, error, {
            "issueId": issue,
            "halt": True,
            "resolution": resolution,
        }

    if child_cache is None or parent_cache is None:
        return False, "Unable to load workflow caches", {
            "halt": True,
            "resolution": "refresh_issue_cache",
        }

    try:
        handoff_path = resolve_handoff_path(parent_cache, child_cache)
        slice_id = resolve_slice_id(parent_cache, child_cache)
    except ValueError as exc:
        return False, str(exc), {"halt": True, "resolution": "hitl_confirm", "error": str(exc)}

    return validate_authority_chain(
        child_cache=child_cache,
        parent_issue_id=child_cache["parentIssueId"],
        child_issue_id=issue,
        handoff_path=handoff_path,
        slice_id=slice_id,
    )


def main() -> int:
    args = parse_args("Validate workflow cache scope precedence")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1

    passed, description, details = run_check(issue, repo_root=args.repo_root)
    if not passed and details.get("halt"):
        print(json.dumps(details, indent=2))
    return print_check_result("scope_precedence", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
