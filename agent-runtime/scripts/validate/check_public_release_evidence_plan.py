#!/usr/bin/env python3
"""Gate: when publicRelease, require schema-valid releaseEvidencePlan (ADR-035).

Plan SoT is a committed artifact (release-evidence-plan-issue-<N>.json or
meta-prepare injectionPlan). Workflow caches stay local / gitignored; ensure
hydrates the cache from the committed plan, and this gate prefers the
committed file so CI does not depend on force-committed caches.
"""

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
from release_evidence_plan import (  # noqa: E402
    resolve_release_evidence_plan,
    validate_release_evidence_plan,
)
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
    if error or child_cache is None or parent_cache is None:
        return False, error or "Unable to load workflow caches", {"issueId": issue}

    public = bool(child_cache.get("publicRelease"))
    plan, plan_source = resolve_release_evidence_plan(
        issue, repo_root, child_cache=child_cache
    )

    details: dict[str, Any] = {
        "issueId": issue,
        "parentIssueId": child_cache.get("parentIssueId"),
        "publicRelease": public,
        "planSource": plan_source,
        "authority": [
            "docs/adr/035-public-release-evidence-and-automatic-rollback.md",
            ".cursor/rules/core-orchestration.mdc",
        ],
    }

    if not public:
        details["skipped"] = True
        return (
            True,
            "publicRelease=false — releaseEvidencePlan not required",
            details,
        )

    result = validate_release_evidence_plan(plan)
    details["missingFields"] = result["missingFields"]
    details["errors"] = result["errors"]
    details["resolution"] = (
        "Commit agent-runtime/artifacts/release-evidence-plan-issue-"
        f"{issue}.json (schema-valid releaseEvidencePlan), then re-run "
        f"meta_prepare_executor --issue {issue}"
    )

    if not result["valid"]:
        details["halt"] = True
        missing = result["missingFields"]
        msg = (
            "publicRelease=true but releaseEvidencePlan invalid/missing; "
            f"missingFields={missing}"
        )
        return False, msg, details

    details["planId"] = (plan or {}).get("planId")
    return True, "releaseEvidencePlan present and schema-valid", details


def main() -> int:
    args = parse_args("Validate releaseEvidencePlan when publicRelease")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result(
        "public_release_evidence_plan", passed, description if not passed else ""
    )


if __name__ == "__main__":
    raise SystemExit(main())
