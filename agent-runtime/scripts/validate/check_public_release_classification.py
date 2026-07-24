#!/usr/bin/env python3
"""Gate: child cache publicRelease classification matches live classifier (ADR-035)."""

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
from public_release_classification import (  # noqa: E402
    classify_public_release,
    paths_from_issue_load_profile,
)
from upstream_fingerprints import (  # noqa: E402
    default_fetch_github_issue_body,
    default_fetch_github_issue_labels,
)
from workflow_cache_store import load_parent_child_caches  # noqa: E402


def run_check(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    issue_body_fetcher=None,
    issue_labels_fetcher=None,
    labels: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    child_cache, parent_cache, _, _, error = load_parent_child_caches(
        issue, repo_root, config=config
    )
    if error or child_cache is None or parent_cache is None:
        return False, error or "Unable to load workflow caches", {"issueId": issue}

    fetcher = issue_body_fetcher or (
        lambda issue_id: default_fetch_github_issue_body(issue_id, repo_root)
    )
    try:
        issue_body = fetcher(issue)
    except (OSError, RuntimeError, ValueError) as exc:
        return False, f"Unable to fetch issue body: {exc}", {"error": str(exc)}

    if labels is not None:
        resolved_labels = list(labels)
    else:
        labels_fetcher = issue_labels_fetcher or (
            lambda issue_id: default_fetch_github_issue_labels(issue_id, repo_root)
        )
        try:
            resolved_labels = list(labels_fetcher(issue) or [])
        except (OSError, RuntimeError, ValueError) as exc:
            return False, f"Unable to fetch issue labels: {exc}", {"error": str(exc)}

    profile = child_cache.get("issueLoadProfile") or {}
    live = classify_public_release(
        paths=paths_from_issue_load_profile(profile),
        issue_body=issue_body,
        labels=resolved_labels,
    )
    cached_flag = child_cache.get("publicRelease")
    cached_reasons = child_cache.get("publicReleaseReasons")

    details: dict[str, Any] = {
        "issueId": issue,
        "parentIssueId": child_cache.get("parentIssueId"),
        "live": live,
        "cached": {
            "publicRelease": cached_flag,
            "publicReleaseReasons": cached_reasons,
        },
        "authority": [
            "docs/adr/035-public-release-evidence-and-automatic-rollback.md",
            ".cursor/rules/core-orchestration.mdc",
        ],
        "resolution": (
            "Re-run python agent-runtime/scripts/meta_prepare_executor.py --issue "
            f"{issue} so ensure persists publicRelease classification"
        ),
    }

    if cached_flag is None or cached_reasons is None:
        details["missingFields"] = [
            f for f, v in (("publicRelease", cached_flag), ("publicReleaseReasons", cached_reasons))
            if v is None
        ]
        return (
            False,
            "Child cache missing publicRelease classification fields",
            details,
        )

    if bool(cached_flag) != bool(live["publicRelease"]) or list(
        cached_reasons or []
    ) != list(live["publicReleaseReasons"]):
        details["halt"] = True
        return (
            False,
            "Cached publicRelease classification does not match live classifier",
            details,
        )

    return (
        True,
        f"publicRelease={live['publicRelease']} matches live classifier "
        f"({len(live['publicReleaseReasons'])} reason(s))",
        details,
    )


def main() -> int:
    args = parse_args("Validate public-release classification on child cache")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result(
        "public_release_classification", passed, description if not passed else ""
    )


if __name__ == "__main__":
    raise SystemExit(main())
