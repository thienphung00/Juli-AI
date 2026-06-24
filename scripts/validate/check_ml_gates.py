#!/usr/bin/env python3
"""Gate: ML-touched reviews document cold-start handling and promotion gate."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    load_review_artifact,
    ml_gates_satisfied,
    ml_modules_touched,
    parse_args,
    print_check_result,
    resolve_issue_number,
)
from ml_thresholds import verify_ml_gates_threshold_values  # noqa: E402


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {}

    touched = ml_modules_touched(review.get("modulesTouched") or [])
    if not touched:
        return True, "No ML modules touched (skipped)", {"skipped": True, "mlModules": []}

    satisfied, problems = ml_gates_satisfied(review)
    ml_gates = review.get("mlGates") or {}
    _, _, scan_details = verify_ml_gates_threshold_values(touched, ml_gates)
    details = {
        "mlModules": touched,
        "coldStartThresholdDocumented": bool(ml_gates.get("coldStartThresholdDocumented")),
        "promotionGateDocumented": bool(ml_gates.get("promotionGateDocumented")),
        "sourceScan": scan_details.get("sourceScan"),
        "declaredThresholds": scan_details.get("declaredThresholds"),
        "problems": problems,
    }
    if not satisfied:
        return False, problems[0], details
    return True, "ML cold-start and promotion gates documented", details


def main() -> int:
    args = parse_args("Validate ML gates")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("ml_gates_enforced", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
