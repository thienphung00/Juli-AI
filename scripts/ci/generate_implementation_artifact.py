#!/usr/bin/env python3
"""Generate an implementation artifact template for an issue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    IMPLEMENTATIONS_DIR,
    RUNTIME_SCHEMA_VERSION,
    deep_merge_under,
    load_json,
    resolve_issue_number,
    utc_now_iso,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=False)
    parser.add_argument(
        "--executor-domain",
        choices=["ui-ux", "backend", "data-platform", "machine-learning"],
        default="backend",
    )
    parser.add_argument("--phase-run-id", type=str, default="")
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Optional JSON file to merge into the generated artifact",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore existing implementation artifact on disk",
    )
    args = parser.parse_args()
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print(
            "error: could not resolve issue number (use --issue or feat/issue-N branch)",
            file=sys.stderr,
        )
        return 1

    now = utc_now_iso()
    phase_run_id = args.phase_run_id or f"{issue}-{now[:10]}-draft"

    artifact = {
        "schemaVersion": RUNTIME_SCHEMA_VERSION,
        "artifactType": "implementation",
        "issueId": issue,
        "executorDomain": args.executor_domain,
        "phaseRunId": phase_run_id,
        "startedAt": now,
        "completedAt": now,
        "executionDurationMs": 0,
        "tokenUsage": {"input": 0, "output": 0, "total": 0},
        "toolsUsed": [],
        "toolInvocationCount": 0,
        "contextFilesLoaded": [],
        "skillsLoaded": [],
        "filesModified": [],
        "testsAdded": [],
        "testsUpdated": [],
        "redGreenRefactorEvidence": [],
        "implementationSummary": "",
        "assumptions": [],
        "risks": [],
    }

    out = IMPLEMENTATIONS_DIR / f"implementation-issue-{issue}.json"
    if not args.fresh and out.exists():
        artifact = deep_merge_under(artifact, load_json(out))
    if args.input_json and args.input_json.exists():
        artifact = deep_merge_under(artifact, load_json(args.input_json))

    artifact["schemaVersion"] = RUNTIME_SCHEMA_VERSION
    artifact["artifactType"] = "implementation"
    artifact["issueId"] = issue
    if args.executor_domain:
        artifact["executorDomain"] = args.executor_domain
    if args.phase_run_id:
        artifact["phaseRunId"] = args.phase_run_id
    artifact["completedAt"] = now

    write_json(out, artifact)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
