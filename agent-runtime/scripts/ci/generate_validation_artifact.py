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
VALIDATE_DIR = Path(__file__).resolve().parents[1] / "validate"

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
    ("public_release_classification", "check_public_release_classification.py"),
    ("public_release_evidence_plan", "check_public_release_evidence_plan.py"),
    ("implementation_schema_valid", "check_implementation_schema_valid.py"),
    ("implementation_tdd_evidence", "check_implementation_tdd_evidence.py"),
    ("differential_tdd", "check_differential_tdd.py"),
    ("executor_domain_matches_cache", "check_executor_domain_matches_cache.py"),
    ("phase_run_correlation", "check_phase_run_correlation.py"),
    ("release_evidence_plan_continuity", "check_release_evidence_plan_continuity.py"),
    ("release_metadata_honesty", "check_release_metadata_honesty.py"),
    ("unpushed_issue_work", "check_unpushed_issue_work.py"),
]

# Advisory gates report a real signal but never decide `status` or
# `readyForMerge` — they are repo-health checks a slice author cannot act on
# from inside a single worktree (issue #1076). This is a single named
# constant, not a predicate or config key, so that widening it is a
# deliberate, reviewable edit to this line rather than something that can
# happen by accident: tests/unit/test_generate_validation_artifact.py pins
# its exact contents and fails if anything is added or removed. Advisory
# results still appear in full in `checks` (real PASS/FAIL + details) and are
# additionally recorded in `advisoryFailures` when they fail — never hidden.
#
# Every other gate stays blocking. Do not add to this set without updating
# the pinned test and agent-runtime/scripts/validate/checks.md.
ADVISORY_CHECKS: frozenset[str] = frozenset({"unpushed_issue_work"})


def load_checker(script_name: str) -> Callable[..., tuple[bool, str, dict[str, Any]]]:
    path = VALIDATE_DIR / script_name
    spec = importlib.util.spec_from_file_location(script_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[script_name] = module
    spec.loader.exec_module(module)
    return module.run_check  # type: ignore[attr-defined]


# #1143: gates that read validation-issue-<N>.json off disk. Running them in
# the same pass as everything else means they judge the PREVIOUS generation's
# file (or its absence, on a first-ever run — failing with `phaseRunId None !=
# canonical` even when every artifact already agrees). main() runs these AFTER
# the first write, against the file this run just produced, then rebuilds the
# artifact so their results land in the registry position with correct
# counters. A named frozenset for the same reason ADVISORY_CHECKS is one:
# widening it must require a human to touch this line.
SELF_REFERENTIAL_CHECKS = frozenset({"phase_run_correlation"})


def run_checks(
    issue: int,
    *,
    only: frozenset[str] | None = None,
    exclude: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Run registered gates and return one result dict per gate.

    Each result carries an explicit ``classification`` ("blocking" or
    "advisory") so the artifact is self-documenting about which gates decide
    merge readiness — nothing is inferred silently downstream.

    ``only``/``exclude`` exist for #1143's two-pass generation and filter by
    gate name; both default to running everything, so every other caller is
    unchanged.
    """
    results: list[dict[str, Any]] = []
    for check_name, script in CHECKS:
        if only is not None and check_name not in only:
            continue
        if check_name in exclude:
            continue
        run_check = load_checker(script)
        passed, description, details = run_check(issue)
        is_advisory = check_name in ADVISORY_CHECKS
        results.append(
            {
                "name": check_name,
                "status": "PASS" if passed else "FAIL",
                "description": description,
                "details": details,
                "classification": "advisory" if is_advisory else "blocking",
            }
        )
        suffix = " (advisory — not merge-blocking)" if is_advisory else ""
        print(f"{check_name}: {'PASS' if passed else 'FAIL'}{suffix}")
    return results


def build_artifact(
    issue: int,
    results: list[dict[str, Any]],
    review: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the validation artifact from gate results and the review.

    `status` and `readyForMerge` are computed from **blocking** gates only
    (issue #1076) — a repo-wide advisory FAIL (e.g. ``unpushed_issue_work``)
    is still fully reported in ``checks`` and in ``advisoryFailures``, but it
    never flips `status` to FAIL or blocks merge on its own.
    """
    blocking_total = sum(1 for name, _ in CHECKS if name not in ADVISORY_CHECKS)
    blocking_failures = [
        r for r in results if r["status"] == "FAIL" and r["name"] not in ADVISORY_CHECKS
    ]
    advisory_failures = [
        {"name": r["name"], "description": r["description"]}
        for r in results
        if r["status"] == "FAIL" and r["name"] in ADVISORY_CHECKS
    ]
    blocking_failed = len(blocking_failures)
    total_failed = sum(1 for r in results if r["status"] == "FAIL")

    status = "PASS" if blocking_failed == 0 else "FAIL"
    review_status = None
    warning_count = 0
    if review:
        review_status = review.get("status")
        warning_count = sum(
            1
            for finding in review.get("criticalFindings", [])
            if finding.get("severity") == "WARNING"
        )

    if blocking_failed == 0 and review_status == "PASS_WITH_WARNINGS":
        overall = (
            f"All {blocking_total} blocking validation check(s) passed; review has "
            f"{warning_count} gating warning(s) with explicit signoff (PASS_WITH_WARNINGS)."
        )
    elif blocking_failed == 0:
        overall = "All blocking validation checks passed."
    else:
        overall = f"{blocking_failed} blocking validation check(s) failed."

    if advisory_failures:
        names = ", ".join(f["name"] for f in advisory_failures)
        overall += (
            f" {len(advisory_failures)} advisory check(s) failed (repo-health signal, "
            f"reported but not merge-blocking — see advisoryFailures): {names}."
        )

    merge_blocked_by_warnings = (
        review_status == "PASS_WITH_WARNINGS"
        and any(
            r["name"] in {
                "findings_acknowledged",
                "reviewer_signoff_present",
                "owner_signoff_present",
            }
            and r["status"] == "FAIL"
            for r in results
        )
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
        "passedChecks": len(results) - total_failed,
        "failedChecks": total_failed,
        "checks": results,
        "overallSummary": overall,
        "readyForMerge": blocking_failed == 0
        and (review_status != "FAIL" or merge_allowed_with_override),
        "warningGated": review_status == "PASS_WITH_WARNINGS",
        "mergeBlockedByWarnings": merge_blocked_by_warnings,
        "mergeOverrideActive": merge_allowed_with_override,
        "advisoryFailures": advisory_failures,
    }
    if review_status:
        artifact["reviewStatus"] = review_status
        artifact["reviewWarningCount"] = warning_count
    enrich_validation_artifact(artifact, issue, review)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=False)
    args = parser.parse_args()
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: could not resolve issue number", file=sys.stderr)
        return 1

    # #1143 two-pass generation. Pass 1 runs every gate EXCEPT the
    # self-referential ones and writes the enriched artifact — that write is
    # what stamps this run's phaseRunId onto disk. Pass 2 runs the deferred
    # gates against the file that now exists, splices their results back into
    # registry order, and rebuilds. build_artifact is a pure function of
    # (issue, results, review), so the rebuild recomputes every counter and
    # status honestly rather than patching them in place.
    review = load_review_artifact(issue)
    first_pass = run_checks(issue, exclude=SELF_REFERENTIAL_CHECKS)
    out = VALIDATION_DIR / f"validation-issue-{issue}.json"
    write_json(out, build_artifact(issue, first_pass, review))

    deferred = run_checks(issue, only=SELF_REFERENTIAL_CHECKS)
    by_name = {r["name"]: r for r in first_pass + deferred}
    results = [by_name[name] for name, _ in CHECKS if name in by_name]
    artifact = build_artifact(issue, results, review)
    write_json(out, artifact)
    print(f"wrote {out}")
    blocking_failed = sum(
        1 for r in results if r["status"] == "FAIL" and r["name"] not in ADVISORY_CHECKS
    )
    return 0 if blocking_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
