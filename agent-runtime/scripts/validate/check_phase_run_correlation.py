#!/usr/bin/env python3
"""Gate: phaseRunId correlation across implementation and phase artifacts.

#1439 — the required-artifact set is computed in CI from tier + branch
(``agent-runtime/scripts/ci/required_artifacts.py``), never read from the
release-evidence plan the same agent loop writes. The plan is still loaded, but
only recorded as evidence: any artifact it tries to relax that CI still requires
is listed under ``planNarrowingIgnored`` and the verdict ignores it.

Consequences of that change, both load-bearing:

* A missing artifact CI marks required is always ``"missing"`` and always a
  failure. It can never resolve to a skip.
* Tier narrowing still exists — a docs-lane or hotfix branch genuinely emits
  fewer artifacts — but it is computed from the tier and the branch, reported as
  ``"skipped_by_tier"``, and always carries its reason.

Fail-closed: an unresolvable tier fails the gate rather than defaulting to a
permissive set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    REPO_ROOT,
    intent_review_artifact_path,
    load_implementation_artifact,
    load_intent_review_artifact,
    load_json,
    load_review_artifact,
    print_check_result,
    resolve_issue_number,
    validation_artifact_path,
)
from release_evidence_plan import resolve_release_evidence_plan  # noqa: E402
from required_artifacts import (  # noqa: E402
    RequiredArtifactSet,
    UnresolvableTierError,
    plan_narrowing_ignored,
    resolve_required_artifacts,
)
from workflow_cache_store import load_child_cache  # noqa: E402

_ARTIFACT_SPECS: tuple[tuple[str, str, Any, Any], ...] = (
    ("implementation", "implementation", None, load_implementation_artifact),
    ("intentReview", "intent_review", intent_review_artifact_path, load_intent_review_artifact),
    ("review", "review", None, load_review_artifact),
    ("validation", "validation", validation_artifact_path, None),
)


def _load_artifact(
    issue: int,
    key: str,
    path_fn: Any,
    loader: Any,
) -> dict[str, Any] | None:
    if loader is not None:
        return loader(issue)
    if path_fn is None:
        return load_implementation_artifact(issue)
    path = path_fn(issue)
    if not path.exists():
        return None
    return load_json(path)


def _log_narrowing(issue: int, computed: RequiredArtifactSet) -> None:
    """Narrowing is never silent — stderr keeps the gate's stdout contract intact."""
    if not computed.narrowed:
        return
    print(
        f"phase_run_correlation[issue {issue}]: required set narrowed by tier — "
        f"tier={computed.tier} branchClass={computed.branch_class} "
        f"branch={computed.branch!r} narrowed={list(computed.narrowed)} "
        f"reason={computed.reason}",
        file=sys.stderr,
    )


def run_check(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    config: dict[str, Any] | None = None,
    tier: str | None = None,
    branch: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    # Fail closed before anything else: an unresolved tier means the required set
    # is unknown, and an unknown required set may never soften into a permissive one.
    try:
        computed = resolve_required_artifacts(tier=tier, branch=branch)
    except UnresolvableTierError as exc:
        return (
            False,
            f"unresolvable CI tier — required artifacts not computed: {exc}",
            {"issueId": issue, "requiredArtifactSet": None},
        )

    _log_narrowing(issue, computed)

    child_cache, _, error = load_child_cache(issue, repo_root, config=config)
    if error or child_cache is None:
        return False, error or "Unable to load child workflow cache", {"issueId": issue}

    implementation = load_implementation_artifact(issue)
    if implementation is None:
        return False, "Implementation artifact missing", {"issueId": issue}

    canonical = implementation.get("phaseRunId")
    if not canonical:
        return False, "Implementation artifact missing phaseRunId", {"issueId": issue}

    # The plan is evidence only. It cannot narrow the required set (#1439).
    plan, plan_source = resolve_release_evidence_plan(issue, repo_root, child_cache=child_cache)
    plan_required = (plan or {}).get("requiredArtifacts") or {}
    ignored = plan_narrowing_ignored(computed, plan_required)

    details: dict[str, Any] = {
        "issueId": issue,
        "canonicalPhaseRunId": canonical,
        "planSource": plan_source,
        "requiredArtifactSet": computed.to_details(),
        "planRequiredArtifacts": plan_required,
        "planNarrowingIgnored": ignored,
        "artifacts": {},
    }
    mismatches: list[str] = []

    for required_key, label, path_fn, loader in _ARTIFACT_SPECS:
        required = computed.required[required_key]
        artifact = _load_artifact(issue, required_key, path_fn, loader)
        entry: dict[str, Any] = {"required": required, "present": artifact is not None}

        if artifact is None:
            if required:
                entry["status"] = "missing"
                mismatches.append(f"{label}: required but missing")
            else:
                entry["status"] = "skipped_by_tier"
                entry["narrowingReason"] = computed.reason
            details["artifacts"][label] = entry
            continue

        phase_run_id = artifact.get("phaseRunId")
        entry["phaseRunId"] = phase_run_id
        if phase_run_id != canonical:
            entry["status"] = "mismatch"
            mismatches.append(f"{label}: phaseRunId {phase_run_id!r} != {canonical!r}")
        else:
            entry["status"] = "matched"
        details["artifacts"][label] = entry

    if mismatches:
        details["mismatches"] = mismatches
        return False, "; ".join(mismatches), details

    return True, f"phaseRunId {canonical} correlated across present artifacts", details


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate phaseRunId correlation across artifacts")
    parser.add_argument("--issue", type=int, help="GitHub issue number")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--tier",
        default=None,
        help="CI tier from classify-tier (issue|wave|main). Omit to resolve from env.",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="PR head branch. Omit to resolve from GITHUB_HEAD_REF/GITHUB_REF_NAME.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(
        issue, repo_root=args.repo_root, tier=args.tier, branch=args.branch
    )
    return print_check_result("phase_run_correlation", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
