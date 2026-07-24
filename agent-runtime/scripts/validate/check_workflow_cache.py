#!/usr/bin/env python3
"""Orchestrator: run workflow cache gates in documented session-entry order.

Prefer ``python agent-runtime/scripts/meta_prepare_executor.py --issue N`` for
Meta → Executor handoff (ensure + gates + cacheStatus=valid).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_VALIDATE = Path(__file__).resolve().parents[1] / "validate"
_CI = Path(__file__).resolve().parents[1] / "ci"
sys.path.insert(0, str(_VALIDATE))
sys.path.insert(0, str(_CI))  # ci wins over validate for shared module names
from common import REPO_ROOT, print_check_result, resolve_issue_number  # noqa: E402
from ensure_workflow_cache import ensure_workflow_caches, load_runtime_config  # noqa: E402
from workflow_cache_store import load_parent_child_caches  # noqa: E402

from check_harness_bootstrap_pin import run_check as run_bootstrap  # noqa: E402
from check_issue_load_profile import run_check as run_load_profile  # noqa: E402
from check_public_release_classification import (  # noqa: E402
    run_check as run_public_release_classification,
)
from check_public_release_evidence_plan import (  # noqa: E402
    run_check as run_public_release_evidence_plan,
)
from check_scope_precedence import run_check as run_precedence  # noqa: E402
from check_workflow_cache_staleness import run_check as run_staleness  # noqa: E402

GATE_SEQUENCE: list[tuple[str, Any]] = [
    ("workflow_cache_staleness", run_staleness),
    ("scope_precedence", run_precedence),
    ("harness_bootstrap_pinned", run_bootstrap),
    ("issue_load_profile", run_load_profile),
    ("public_release_classification", run_public_release_classification),
    ("public_release_evidence_plan", run_public_release_evidence_plan),
]


def run_all_gates(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    config: dict[str, Any] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    for gate_name, run_check in GATE_SEQUENCE:
        passed, description, details = run_check(issue, repo_root=repo_root, config=config)
        results.append(
            {
                "gate": gate_name,
                "passed": passed,
                "description": description,
                "details": details,
            }
        )
        if not passed:
            return False, results
    return True, results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run workflow cache gate chain")
    parser.add_argument("--issue", type=int, help="GitHub issue number")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--ensure",
        action="store_true",
        help="Bootstrap/refresh parent+child caches before running gates",
    )
    parser.add_argument("--parent", type=int, help="Parent issue when using --ensure")
    parser.add_argument("--slice-id", dest="slice_id", help="Slice id when using --ensure")
    parser.add_argument("--handoff", dest="handoff_path", help="Handoff path when using --ensure")
    parser.add_argument("--force", action="store_true", help="Force rewrite caches with --ensure")
    parser.add_argument(
        "--require-valid",
        action="store_true",
        help="Fail unless child cacheStatus == valid (Executor unlock)",
    )
    args = parser.parse_args()

    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1

    config = load_runtime_config(args.repo_root)
    if args.ensure or (config.get("workflow_prompt_cache") or {}).get("ensureOnMetaEntry"):
        # Only auto-ensure when explicitly requested via --ensure; config-driven
        # ensure is owned by meta_prepare_executor.py to avoid surprise writes
        # during plain gate checks.
        if args.ensure:
            try:
                ensure_workflow_caches(
                    issue,
                    repo_root=args.repo_root,
                    config=config,
                    parent_issue_id=args.parent,
                    slice_id=args.slice_id,
                    handoff_path=args.handoff_path,
                    force=args.force,
                    mark_valid=True,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                return print_check_result("workflow_cache_ensure", False, str(exc))

    passed, results = run_all_gates(issue, repo_root=args.repo_root, config=config)
    if not passed:
        failed = next(item for item in results if not item["passed"])
        if failed["details"].get("halt"):
            print(json.dumps(failed["details"], indent=2))
        return print_check_result(
            failed["gate"],
            False,
            failed["description"],
        )

    require_valid = args.require_valid or bool(
        (config.get("workflow_prompt_cache") or {}).get("requireValidCacheBeforeExecutor")
    )
    if require_valid:
        child, _, _, _, error = load_parent_child_caches(
            issue, args.repo_root, config=config
        )
        if error or child is None:
            return print_check_result("workflow_cache_valid", False, error or "missing cache")
        if child.get("cacheStatus") != "valid":
            return print_check_result(
                "workflow_cache_valid",
                False,
                f"cacheStatus={child.get('cacheStatus')!r}; Executor requires valid",
            )

    print(json.dumps({"issueId": issue, "gates": [item["gate"] for item in results]}, indent=2))
    return print_check_result("workflow_cache_gates", True, "")


if __name__ == "__main__":
    raise SystemExit(main())
