#!/usr/bin/env python3
"""CLI: bootstrap parent + child workflow caches for an issue (Meta pre-Executor)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import REPO_ROOT, resolve_issue_number  # noqa: E402
from ensure_workflow_cache import ensure_workflow_caches, load_runtime_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--parent", type=int, help="Parent/PRD issue id when not in body")
    parser.add_argument("--slice-id", dest="slice_id", help="EXECUTION / Focus slice id")
    parser.add_argument("--handoff", dest="handoff_path", help="Epic handoff path")
    parser.add_argument("--force", action="store_true", help="Rewrite caches from derivation")
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Leave cacheStatus=partial (default: valid / ready for Executor)",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()

    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1

    try:
        summary = ensure_workflow_caches(
            issue,
            repo_root=args.repo_root,
            config=load_runtime_config(args.repo_root, args.config),
            parent_issue_id=args.parent,
            slice_id=args.slice_id,
            handoff_path=args.handoff_path,
            force=args.force,
            mark_valid=not args.partial,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2))
    return 0 if summary.get("readyForExecutor") or args.partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
