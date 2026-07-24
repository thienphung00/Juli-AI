#!/usr/bin/env python3
"""Gate: phaseRunId correlation across implementation and phase artifacts."""

from __future__ import annotations

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
    parse_args,
    print_check_result,
    resolve_issue_number,
    validation_artifact_path,
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


def run_check(
    issue: int,
    *,
    repo_root: Path = REPO_ROOT,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    child_cache, _, error = load_child_cache(issue, repo_root, config=config)
    if error or child_cache is None:
        return False, error or "Unable to load child workflow cache", {"issueId": issue}

    implementation = load_implementation_artifact(issue)
    if implementation is None:
        return False, "Implementation artifact missing", {"issueId": issue}

    canonical = implementation.get("phaseRunId")
    if not canonical:
        return False, "Implementation artifact missing phaseRunId", {"issueId": issue}

    profile = child_cache.get("issueLoadProfile") or {}
    plan = profile.get("releaseEvidencePlan") or {}
    required_artifacts = plan.get("requiredArtifacts") or {}

    details: dict[str, Any] = {
        "issueId": issue,
        "canonicalPhaseRunId": canonical,
        "artifacts": {},
    }
    mismatches: list[str] = []

    for required_key, label, path_fn, loader in _ARTIFACT_SPECS:
        required = bool(required_artifacts.get(required_key, required_key == "implementation"))
        artifact = _load_artifact(issue, required_key, path_fn, loader)
        entry: dict[str, Any] = {"required": required, "present": artifact is not None}

        if artifact is None:
            entry["status"] = "missing"
            if required:
                mismatches.append(f"{label}: required but missing")
            else:
                entry["status"] = "skipped"
            details["artifacts"][label] = entry
            continue

        phase_run_id = artifact.get("phaseRunId")
        entry["phaseRunId"] = phase_run_id
        if phase_run_id != canonical:
            entry["status"] = "mismatch"
            mismatches.append(
                f"{label}: phaseRunId {phase_run_id!r} != {canonical!r}"
            )
        else:
            entry["status"] = "matched"
        details["artifacts"][label] = entry

    if mismatches:
        details["mismatches"] = mismatches
        return False, "; ".join(mismatches), details

    return True, f"phaseRunId {canonical} correlated across present artifacts", details


def main() -> int:
    args = parse_args("Validate phaseRunId correlation across artifacts")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue, repo_root=args.repo_root)
    return print_check_result("phase_run_correlation", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
