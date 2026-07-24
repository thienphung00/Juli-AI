#!/usr/bin/env python3
"""Meta Agent entrypoint: ensure workflow caches, run gates, unlock Executor.

Run this before assigning any Executor Agent. Do not start TDD until exit 0.

Example::

    python agent-runtime/scripts/meta_prepare_executor.py --issue 420
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
# validate first, then ci — ci must win for ensure_workflow_cache / workflow_cache_* modules.
sys.path.insert(0, str(_SCRIPTS / "validate"))
sys.path.insert(0, str(_SCRIPTS / "ci"))

from common import REPO_ROOT, resolve_issue_number  # noqa: E402
from ensure_workflow_cache import ensure_workflow_caches, load_runtime_config  # noqa: E402
from check_workflow_cache import run_all_gates  # noqa: E402
from workflow_cache_store import load_parent_child_caches  # noqa: E402

TDD_CONTRACT: dict[str, Any] = {
    "required": True,
    "minRedGreenCycles": 1,
    "requireTestsAddedOrUpdated": True,
    "requirePassingCommandEvidence": True,
}

_REVIEW_VALIDATE_SKILL_MARKERS = ("intent-review", "guardrails", "validate")


def _filter_executor_harness(harness: dict[str, Any]) -> dict[str, Any]:
    filtered = dict(harness)
    skills = list(harness.get("skills") or [])
    filtered["skills"] = [
        skill
        for skill in skills
        if not any(marker in (skill.get("path") or "") for marker in _REVIEW_VALIDATE_SKILL_MARKERS)
    ]
    return filtered


def injection_plan(child: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    profile = child.get("issueLoadProfile") or {}
    harness = _filter_executor_harness(child.get("harnessUtility") or {})
    public_release = bool(child.get("publicRelease"))
    plan: dict[str, Any] = {
        "parentScopeBlock": parent.get("parentScopeBlock"),
        "doNotLoad": list(
            dict.fromkeys(list(parent.get("doNotLoad") or []) + list(child.get("doNotLoad") or []))
        ),
        "harnessUtility": harness,
        "issueLoadProfile": profile,
        "phaseCacheBlocks.meta": (child.get("phaseCacheBlocks") or {}).get("meta"),
        "promptCacheBlock": child.get("promptCacheBlock"),
        "executorDomain": profile.get("executorDomain"),
        "skillsPrimaryOnly": True,
        "publicRelease": public_release,
        "tddContract": dict(TDD_CONTRACT),
    }
    if public_release:
        release_plan = profile.get("releaseEvidencePlan")
        if release_plan is not None:
            plan["releaseEvidencePlan"] = release_plan
            plan["releaseEvidencePlanId"] = release_plan.get("planId")
    return plan


def executor_domain_mismatch(child: dict[str, Any], plan: dict[str, Any]) -> bool:
    profile_domain = (child.get("issueLoadProfile") or {}).get("executorDomain")
    return plan.get("executorDomain") != profile_domain


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--parent", type=int)
    parser.add_argument("--slice-id", dest="slice_id")
    parser.add_argument("--handoff", dest="handoff_path")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-ensure", action="store_true", help="Only run gates")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()

    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1

    config = load_runtime_config(args.repo_root, args.config)
    wpc = config.get("workflow_prompt_cache") or {}
    require_valid = bool(wpc.get("requireValidCacheBeforeExecutor", True))

    ensure_summary: dict[str, Any] | None = None
    if not args.skip_ensure and wpc.get("ensureOnMetaEntry", True):
        try:
            ensure_summary = ensure_workflow_caches(
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
            print(
                json.dumps(
                    {
                        "halt": True,
                        "readyForExecutor": False,
                        "error": str(exc),
                        "resolution": "ensure_workflow_cache_failed",
                    },
                    indent=2,
                )
            )
            return 1

    passed, gate_results = run_all_gates(issue, repo_root=args.repo_root, config=config)
    child, parent, _, _, load_error = load_parent_child_caches(
        issue, args.repo_root, config=config
    )

    cache_status = (child or {}).get("cacheStatus")
    ready = bool(
        passed
        and child is not None
        and parent is not None
        and (not require_valid or cache_status == "valid")
    )

    payload: dict[str, Any] = {
        "issueId": issue,
        "halt": not ready,
        "readyForExecutor": ready,
        "cacheStatus": cache_status,
        "ensure": ensure_summary,
        "gates": gate_results,
        "requireValidCacheBeforeExecutor": require_valid,
    }
    if load_error:
        payload["loadError"] = load_error
    if ready and child and parent:
        injection = injection_plan(child, parent)
        if executor_domain_mismatch(child, injection):
            ready = False
            payload["halt"] = True
            payload["readyForExecutor"] = False
            payload["failedGate"] = "executor_domain_alignment"
            payload["missingFields"] = []
            payload["resolution"] = (
                "Align injectionPlan.executorDomain with "
                "child.issueLoadProfile.executorDomain, then re-run "
                f"meta_prepare_executor --issue {issue}"
            )
        else:
            payload["injectionPlan"] = injection
            payload["executorDomain"] = (child.get("issueLoadProfile") or {}).get(
                "executorDomain"
            )
    elif not passed:
        failed = next(item for item in gate_results if not item["passed"])
        payload["halt"] = True
        payload["readyForExecutor"] = False
        payload["failedGate"] = failed["gate"]
        details = failed.get("details") or {}
        payload["missingFields"] = list(details.get("missingFields") or [])
        payload["resolution"] = details.get("resolution", "refresh_issue_cache")
        if details.get("halt"):
            payload["halt"] = True
    elif require_valid and cache_status != "valid":
        payload["resolution"] = "set_cache_status_valid"
        payload["error"] = (
            f"Child cacheStatus is {cache_status!r}; Executor requires 'valid'."
        )

    print(json.dumps(payload, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
