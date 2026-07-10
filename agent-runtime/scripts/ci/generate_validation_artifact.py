#!/usr/bin/env python3
"""Run all validate gates and write validation-issue-<n>.json."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    VALIDATION_DIR,
    enrich_validation_artifact,
    load_review_artifact,
    merge_override_active,
    resolve_issue_number,
    utc_now_iso,
    write_json,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATE_DIR = REPO_ROOT / "scripts" / "validate"

CHECKS: list[tuple[str, str]] = [
    ("review_artifact_present", "check_review_artifact.py"),
    ("implementation_artifact_present", "check_implementation_artifact.py"),
    ("acceptance_criteria_mapped", "check_acceptance_mapping.py"),
    ("module_boundaries", "check_module_boundaries.py"),
    ("module_md_sync", "check_module_drift.py"),
    ("handoff_structure", "check_handoff.py"),
    ("adr_requirement", "check_adr.py"),
    ("done_md_completion", "check_done_md.py"),
    ("critical_findings_resolved", "check_critical_findings_resolved.py"),
    ("findings_acknowledged", "check_findings_acknowledged.py"),
    ("reviewer_signoff_present", "check_reviewer_signoff.py"),
    ("owner_signoff_present", "check_owner_signoff.py"),
    ("ml_gates_enforced", "check_ml_gates.py"),
]


def load_checker(script_name: str) -> Callable[..., tuple[bool, str, dict[str, Any]]]:
    path = VALIDATE_DIR / script_name
    spec = importlib.util.spec_from_file_location(script_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[script_name] = module
    spec.loader.exec_module(module)
    return module.run_check  # type: ignore[attr-defined]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=False)
    args = parser.parse_args()
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: could not resolve issue number", file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []
    failed = 0
    for check_name, script in CHECKS:
        run_check = load_checker(script)
        passed, description, details = run_check(issue)
        if not passed:
            failed += 1
        results.append(
            {
                "name": check_name,
                "status": "PASS" if passed else "FAIL",
                "description": description,
                "details": details,
            }
        )
        print(f"{check_name}: {'PASS' if passed else 'FAIL'}")

    status = "PASS" if failed == 0 else "FAIL"
    review = load_review_artifact(issue)
    warning_count = 0
    review_status = None
    if review:
        review_status = review.get("status")
        warning_count = sum(
            1
            for finding in review.get("criticalFindings", [])
            if finding.get("severity") == "WARNING"
        )

    if failed == 0 and review_status == "PASS_WITH_WARNINGS":
        overall = (
            f"All {len(results)} validation checks passed; review has {warning_count} "
            "gating warning(s) with explicit signoff (PASS_WITH_WARNINGS)."
        )
    elif failed == 0:
        overall = "All validation checks passed."
    else:
        overall = f"{failed} validation check(s) failed."

    merge_blocked_by_warnings = (
        review_status == "PASS_WITH_WARNINGS"
        and any(c["name"] in {
            "findings_acknowledged",
            "reviewer_signoff_present",
            "owner_signoff_present",
        } and c["status"] == "FAIL" for c in results)
    )

    merge_allowed_with_override = (
        review is not None
        and review.get("status") == "FAIL"
        and merge_override_active(review)
    )

    artifact: dict[str, Any] = {
        "id": f"validation-issue-{issue}",
        "issue": issue,
        "timestamp": utc_now_iso(),
        "validatedBy": "validate skill",
        "status": status,
        "passedChecks": len(results) - failed,
        "failedChecks": failed,
        "checks": results,
        "overallSummary": overall,
        "readyForMerge": failed == 0 and (review_status != "FAIL" or merge_allowed_with_override),
        "warningGated": review_status == "PASS_WITH_WARNINGS",
        "mergeBlockedByWarnings": merge_blocked_by_warnings,
        "mergeOverrideActive": merge_allowed_with_override,
    }
    if review_status:
        artifact["reviewStatus"] = review_status
        artifact["reviewWarningCount"] = warning_count
    enrich_validation_artifact(artifact, issue, review)

    out = VALIDATION_DIR / f"validation-issue-{issue}.json"
    write_json(out, artifact)
    print(f"wrote {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
