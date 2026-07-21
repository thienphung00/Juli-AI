#!/usr/bin/env python3
"""Gate: parent and child workflow caches match live upstream fingerprints."""

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
from upstream_fingerprints import (  # noqa: E402
    build_child_upstream_fingerprints,
    build_parent_upstream_fingerprints,
    compare_fingerprints,
    default_fetch_github_issue_body,
)
from workflow_cache_linkage import (  # noqa: E402
    resolve_handoff_path,
    resolve_scope_alignment_path,
    resolve_slice_id,
)
from workflow_cache_store import load_parent_child_caches  # noqa: E402


def format_mismatch(mismatch: dict[str, str]) -> str:
    path = mismatch["path"]
    expected = mismatch["expected"]
    actual = mismatch.get("actual")
    if actual is None:
        return f"{path} (no live fingerprint; cached {expected})"
    return f"{path} (cached {expected}, live {actual})"


def stale_action(parent_stale: bool, child_stale: bool) -> str:
    if parent_stale and child_stale:
        return "Refresh epic cache (parent) then issue cache (child) via scope alignment."
    if parent_stale:
        return "Refresh epic cache only; may affect all children."
    if child_stale:
        return "Refresh issue cache only; parent cache unchanged unless epic rescoped."
    return ""


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
        scope_alignment_path = resolve_scope_alignment_path(child_cache, issue)

        live_parent = build_parent_upstream_fingerprints(
            parent_issue_id=parent_issue_id,
            handoff_path=handoff_path,
            slice_id=slice_id,
            repo_root=repo_root,
            issue_body_fetcher=fetcher,
        )
        live_child = build_child_upstream_fingerprints(
            issue_id=issue,
            scope_alignment_path=scope_alignment_path,
            repo_root=repo_root,
            issue_body_fetcher=fetcher,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return False, f"Unable to compute live fingerprints: {exc}", {"error": str(exc)}

    parent_cached = parent_cache.get("upstreamFingerprints") or []
    child_cached = child_cache.get("upstreamFingerprints") or []
    parent_mismatches = compare_fingerprints(parent_cached, live_parent)
    child_mismatches = compare_fingerprints(child_cached, live_child)

    details: dict[str, Any] = {
        "issueId": issue,
        "parentIssueId": parent_issue_id,
        "sliceId": slice_id,
        "parentStale": bool(parent_mismatches),
        "childStale": bool(child_mismatches),
        "parentMismatches": parent_mismatches,
        "childMismatches": child_mismatches,
        "liveParentFingerprints": live_parent,
        "liveChildFingerprints": live_child,
    }

    if parent_mismatches or child_mismatches:
        parts: list[str] = []
        if parent_mismatches:
            parts.append(
                "Parent cache stale: "
                + "; ".join(format_mismatch(item) for item in parent_mismatches)
            )
        if child_mismatches:
            parts.append(
                "Child cache stale: "
                + "; ".join(format_mismatch(item) for item in child_mismatches)
            )
        message = ". ".join(parts)
        action = stale_action(bool(parent_mismatches), bool(child_mismatches))
        if action:
            message = f"{message}. {action}"
        return False, message, details

    return True, "Parent and child workflow caches match live upstream fingerprints", details


def main() -> int:
    args = parse_args("Validate workflow cache staleness")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1

    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result("workflow_cache_staleness", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
