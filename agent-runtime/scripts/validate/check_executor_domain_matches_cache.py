#!/usr/bin/env python3
"""Gate: implementation.executorDomain matches child cache issueLoadProfile."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    REPO_ROOT,
    implementation_artifact_path,
    load_json,
    parse_args,
    print_check_result,
    resolve_issue_number,
)
from workflow_cache_store import load_child_cache  # noqa: E402


def run_check(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    child_cache, _, error = load_child_cache(issue, repo_root, config=config)
    if error or child_cache is None:
        return False, error or "Unable to load child workflow cache", {"issueId": issue}

    path = implementation_artifact_path(issue)
    if not path.exists():
        return False, "Implementation artifact missing", {
            "path": f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json",
            "issueId": issue,
        }

    artifact = load_json(path)
    expected = (child_cache.get("issueLoadProfile") or {}).get("executorDomain")
    actual = artifact.get("executorDomain")
    details: dict[str, Any] = {
        "issueId": issue,
        "expectedExecutorDomain": expected,
        "actualExecutorDomain": actual,
    }

    if not expected:
        return False, "Child cache missing issueLoadProfile.executorDomain", details

    if actual != expected:
        return (
            False,
            f"executorDomain mismatch: artifact={actual!r}, cache={expected!r}",
            details,
        )

    return True, f"executorDomain matches cache ({actual})", details


def main() -> int:
    args = parse_args("Validate executor domain matches child cache")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result(
        "executor_domain_matches_cache", passed, description if not passed else ""
    )


if __name__ == "__main__":
    raise SystemExit(main())
