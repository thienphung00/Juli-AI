#!/usr/bin/env python3
"""Gate: cached issueLoadProfile matches Focus slice-derived context."""

from __future__ import annotations

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
from issue_load_profile import compare_issue_load_profile, derive_issue_load_profile  # noqa: E402
from upstream_fingerprints import default_fetch_github_issue_body  # noqa: E402
from workflow_cache_linkage import resolve_handoff_path, resolve_slice_id  # noqa: E402
from workflow_cache_store import load_parent_child_caches  # noqa: E402


def format_problem(problem: dict[str, Any]) -> str:
    field = problem["field"]
    problem_type = problem["type"]
    if problem_type == "value_mismatch":
        return f"{field} expected {problem.get('expected')!r}, cached {problem.get('actual')!r}"
    path = problem.get("path")
    if problem_type == "missing_required":
        return f"{field} omits derived required path {path!r}"
    if problem_type == "undeclared_path":
        return f"{field} adds undeclared path {path!r}"
    return f"{field} {problem_type}: {path!r}"


def run_check(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    issue_body_fetcher=None,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    child_cache, parent_cache, _, _, error = load_parent_child_caches(
        issue, repo_root, config=config
    )
    if error or child_cache is None or parent_cache is None:
        return False, error or "Unable to load workflow caches", {"issueId": issue}

    parent_issue_id = child_cache["parentIssueId"]
    fetcher = issue_body_fetcher or (
        lambda issue_id: default_fetch_github_issue_body(issue_id, repo_root)
    )

    try:
        handoff_path = resolve_handoff_path(parent_cache, child_cache)
        slice_id = resolve_slice_id(parent_cache, child_cache)
        if not slice_id:
            raise ValueError("sliceId missing from parent or child cache")
        issue_body = fetcher(issue)
        derived_profile = derive_issue_load_profile(
            slice_id=slice_id,
            issue_body=issue_body,
            handoff_path=handoff_path,
        )
    except (RuntimeError, ValueError) as exc:
        return False, f"Unable to derive issueLoadProfile: {exc}", {"error": str(exc)}

    cached_profile = child_cache.get("issueLoadProfile") or {}
    problems = compare_issue_load_profile(cached_profile, derived_profile)
    details: dict[str, Any] = {
        "issueId": issue,
        "parentIssueId": parent_issue_id,
        "sliceId": slice_id,
        "derivedProfile": derived_profile,
        "cachedProfile": cached_profile,
        "problems": problems,
    }

    if problems:
        message = "; ".join(format_problem(problem) for problem in problems)
        return False, f"issueLoadProfile drift: {message}", details

    return True, "Cached issueLoadProfile matches derived Focus slice profile", details


def main() -> int:
    args = parse_args("Validate derived issueLoadProfile")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1

    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result("issue_load_profile", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
