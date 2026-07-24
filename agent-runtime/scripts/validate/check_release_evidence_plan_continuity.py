#!/usr/bin/env python3
"""Gate: releaseEvidencePlanId continuity for public-release issues (ADR-035)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    REPO_ROOT,
    load_implementation_artifact,
    load_json,
    parse_args,
    print_check_result,
    resolve_issue_number,
    validation_artifact_path,
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

    public = bool(child_cache.get("publicRelease"))
    profile = child_cache.get("issueLoadProfile") or {}
    plan = profile.get("releaseEvidencePlan") or {}
    expected_plan_id = plan.get("planId")

    details: dict[str, Any] = {
        "issueId": issue,
        "publicRelease": public,
        "expectedPlanId": expected_plan_id,
        "authority": [
            "docs/adr/035-public-release-evidence-and-automatic-rollback.md",
            ".cursor/rules/core-orchestration.mdc",
        ],
    }

    if not public:
        details["skipped"] = True
        return True, "publicRelease=false — releaseEvidencePlanId not required", details

    if not expected_plan_id:
        return False, "Child cache missing releaseEvidencePlan.planId", details

    implementation = load_implementation_artifact(issue)
    if implementation is None:
        return False, "Implementation artifact missing", details

    actual_plan_id = implementation.get("releaseEvidencePlanId")
    details["implementationPlanId"] = actual_plan_id

    if actual_plan_id != expected_plan_id:
        return (
            False,
            f"releaseEvidencePlanId mismatch: implementation={actual_plan_id!r}, "
            f"plan={expected_plan_id!r}",
            details,
        )

    validation_path = validation_artifact_path(issue)
    if validation_path.exists():
        validation = load_json(validation_path)
        validation_plan_id = validation.get("releaseEvidencePlanId")
        details["validationPlanId"] = validation_plan_id
        if validation_plan_id != expected_plan_id:
            return (
                False,
                f"validation releaseEvidencePlanId mismatch: {validation_plan_id!r} "
                f"!= {expected_plan_id!r}",
                details,
            )

    return True, f"releaseEvidencePlanId matches Meta plan ({expected_plan_id})", details


def main() -> int:
    args = parse_args("Validate releaseEvidencePlanId continuity")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result(
        "release_evidence_plan_continuity", passed, description if not passed else ""
    )


if __name__ == "__main__":
    raise SystemExit(main())
