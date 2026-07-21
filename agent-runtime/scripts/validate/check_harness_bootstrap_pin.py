#!/usr/bin/env python3
"""Gate: parent bootstrapRef is pinned and child harnessUtility paths match pinned SHA."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from build_runtime import load_simple_yaml  # noqa: E402
from common import (  # noqa: E402
    REPO_ROOT,
    parse_args,
    print_check_result,
    resolve_issue_number,
)
from harness_bootstrap_pin import validate_bootstrap_ref  # noqa: E402
from workflow_cache_store import load_parent_child_caches  # noqa: E402

AGENT_RUNTIME_CONFIG = REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml"


def run_check(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    child_cache, parent_cache, _, _, error = load_parent_child_caches(
        issue, repo_root, config=config
    )
    if error or child_cache is None or parent_cache is None:
        return False, error or "Unable to load workflow caches", {"issueId": issue}

    runtime_config = config or load_simple_yaml(AGENT_RUNTIME_CONFIG)
    bootstrap_config = runtime_config.get("workflow_prompt_cache", {}).get("bootstrap") or {}

    return validate_bootstrap_ref(
        parent_cache,
        child_cache,
        bootstrap_config=bootstrap_config,
        repo_root=repo_root,
    )


def main() -> int:
    args = parse_args("Validate harness bootstrap pin")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1

    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result("harness_bootstrap_pinned", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
