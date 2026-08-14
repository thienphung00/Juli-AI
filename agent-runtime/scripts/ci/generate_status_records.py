#!/usr/bin/env python3
"""Migration: build compact status/issue-<N>.json records from existing
review + validation artifact pairs (#670 P1 Option A).

Reconciles the audit's committed-artifact-volume cost driver with ADR-052's
locked intent to keep a committed merge-time source of truth: a small
compact record replaces the verbose bodies as the wave->main artifact-gate
read path (see wave_manifest.py `_validate_issue_artifacts`) and, per #1064,
the issue-tier artifact-retention-guard read path, while the verbose bodies
themselves stay local only — gitignored, never committed, never uploaded
anywhere (`git rm` from history is a separate step — see the issue's
migration recipe; this script only reads and never deletes).

Idempotent: re-running overwrites each status/issue-<N>.json deterministically
from the current on-disk review/validation body content, so it is safe to run
again if a review or validation artifact is amended before the `git rm` step.
Only issues with BOTH a review and a validation artifact present are migrated
— this covers every issue recorded to date, including #660.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    REVIEWS_DIR,
    STATUS_DIR,
    VALIDATION_DIR,
    utc_now_iso,
)

WAVES_DIR = STATUS_DIR.parent / "waves"
GATE_VERSION = 1


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _issue_numbers() -> list[int]:
    numbers: set[int] = set()
    for path in REVIEWS_DIR.glob("review-issue-*.json"):
        suffix = path.stem.rsplit("-", 1)[-1]
        if suffix.isdigit():
            numbers.add(int(suffix))
    for path in VALIDATION_DIR.glob("validation-issue-*.json"):
        suffix = path.stem.rsplit("-", 1)[-1]
        if suffix.isdigit():
            numbers.add(int(suffix))
    return sorted(numbers)


def _wave_for_issue(issue: int) -> str | None:
    if not WAVES_DIR.is_dir():
        return None
    for wave_path in sorted(WAVES_DIR.glob("*.json")):
        try:
            manifest = json.loads(wave_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        issues = manifest.get("issues") if isinstance(manifest, dict) else None
        if isinstance(issues, list) and issue in issues:
            return manifest.get("waveId") or wave_path.stem
    return None


def build_status_record(issue: int) -> dict[str, Any] | None:
    """Build one compact status record from an existing review+validation pair.

    Returns ``None`` when either body is missing (not yet reviewed/validated,
    or already migrated-and-removed) so the caller can skip it.
    """
    review_path = REVIEWS_DIR / f"review-issue-{issue}.json"
    validation_path = VALIDATION_DIR / f"validation-issue-{issue}.json"
    if not review_path.is_file() or not validation_path.is_file():
        return None

    review_bytes = review_path.read_bytes()
    validation_bytes = validation_path.read_bytes()
    review = json.loads(review_bytes)
    validation = json.loads(validation_bytes)

    review_status = review.get("status")

    validation_status = validation.get("status")
    ready_for_merge = validation.get("readyForMerge")
    # Fold the old readyForMerge gate into a single effective status so the
    # compact record stays a flat PASS/FAIL without a separate boolean.
    effective_validation_status = (
        "PASS"
        if validation_status == "PASS" and ready_for_merge is True
        else (validation_status or "FAIL")
    )

    test_coverage = review.get("testCoverage")
    acceptance = (
        test_coverage.get("acceptance", {})
        if isinstance(test_coverage, dict) and isinstance(test_coverage.get("acceptance"), dict)
        else {}
    )

    return {
        "issue": issue,
        "wave": _wave_for_issue(issue),
        "review": {
            "status": review_status,
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json"
            ),
            "sha256": _sha256_bytes(review_bytes),
        },
        "validation": {
            "status": effective_validation_status,
            "artifactRef": (
                f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
            ),
            "sha256": _sha256_bytes(validation_bytes),
        },
        "metrics": {
            "acceptanceTotal": acceptance.get("total", 0),
            "acceptanceMapped": acceptance.get("mapped", 0),
            "criticalFindings": len(review.get("criticalFindings") or []),
            "modulesTouched": review.get("modulesTouched") or [],
        },
        "timestamp": validation.get("timestamp") or review.get("timestamp") or utc_now_iso(),
        "gateVersion": GATE_VERSION,
    }


def migrate(*, dry_run: bool = False) -> list[int]:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    generated: list[int] = []
    for issue in _issue_numbers():
        record = build_status_record(issue)
        if record is None:
            continue
        target = STATUS_DIR / f"issue-{issue}.json"
        payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
        if not dry_run:
            target.write_text(payload, encoding="utf-8")
        generated.append(issue)
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be generated without writing files",
    )
    args = parser.parse_args()

    generated = migrate(dry_run=args.dry_run)
    verb = "would generate" if args.dry_run else "generated"
    print(f"status records: {verb} {len(generated)} for issues {generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
