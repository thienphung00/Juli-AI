#!/usr/bin/env python3
"""Merge status gate: blocks merge when review.status is FAIL (#1569).

Complement to check_artifact_retention_guard.py: the guard checks that evidence
exists and is well-formed; this gate reads the verdict and blocks on FAIL.

#1569: Separates "is there evidence" (retention guard) from "did it pass"
(this check). A failed review is now committable as durable evidence, but the
merge is blocked by reading review.status in this gate, not by the record's
absence.

Fail-closed: missing, malformed, or unreadable record is a FAIL. Only a record
with review.status in {"PASS", "PASS_WITH_WARNINGS"} passes this gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import AGENT_RUNTIME_ROOT, STATUS_DIR, print_check_result
from json_schema_validate import validate_json_schema

STATUS_SCHEMA_PATH = AGENT_RUNTIME_ROOT / "docs" / "schemas" / "status-record.schema.json"


def status_record_path(issue: int, status_dir: Path = STATUS_DIR) -> Path:
    return status_dir / f"issue-{issue}.json"


def parse_issue_number(raw: str | None) -> int | None:
    """Return the resolved issue number, or ``None`` when ``raw`` is not one."""
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        value = int(stripped)
    except ValueError:
        return None
    if value < 1:
        return None
    return value


def _load_status_schema() -> dict[str, Any] | None:
    try:
        return json.loads(STATUS_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def evaluate(
    issue: int,
    *,
    status_dir: Path = STATUS_DIR,
) -> tuple[bool, str]:
    """Read review.status from committed record and block if FAIL.

    Returns ``(passed, detail)``. Passes only when review.status is PASS or
    PASS_WITH_WARNINGS. Any missing, malformed, or unreadable record fails.
    """
    record_path = status_record_path(issue, status_dir)

    if not record_path.is_file():
        return False, (
            f"missing {record_path} for issue {issue} — cannot determine merge verdict "
            f"without a status record"
        )

    try:
        raw_bytes = record_path.read_bytes()
    except OSError as exc:
        return False, f"could not read {record_path}: {exc}"

    try:
        payload: Any = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        return False, f"{record_path} is not valid JSON: {exc}"

    if not isinstance(payload, dict):
        return False, (
            f"{record_path} does not contain a JSON object (got {type(payload).__name__})"
        )

    schema = _load_status_schema()
    if schema is None:
        return False, f"could not load status-record schema at {STATUS_SCHEMA_PATH}"

    schema_errors = validate_json_schema(payload, schema)
    if schema_errors:
        return False, (f"{record_path} does not match the status-record schema: {schema_errors[0]}")

    if payload.get("issue") != issue:
        return False, (f"{record_path} is a record for issue {payload.get('issue')!r}, not {issue}")

    review = payload.get("review")
    if not isinstance(review, dict):
        return False, (f"{record_path} is missing review object (unexpected schema)")

    review_status = review.get("status")
    if review_status not in {"PASS", "PASS_WITH_WARNINGS"}:
        return False, (
            f"{record_path}: review.status is {review_status!r} — merge blocked. "
            f"Only PASS or PASS_WITH_WARNINGS (with owner signoff) may proceed to merge."
        )

    # The verdict is PASS or PASS_WITH_WARNINGS; check signoff for the latter.
    if review_status == "PASS_WITH_WARNINGS":
        if review.get("warningsAcknowledged") is not True:
            return False, (
                f"{record_path}: review is PASS_WITH_WARNINGS but "
                "warningsAcknowledged is not true — every gating WARNING needs "
                "reviewer acceptance and owner ack"
            )
        if review.get("ownerSignoffPresent") is not True:
            return False, (
                f"{record_path}: review is PASS_WITH_WARNINGS but "
                "ownerSignoffPresent is not true — a timestamped owner signoff "
                "is required to ship accepted warnings"
            )

    return True, f"{record_path}: review.status {review_status} — merge allowed to proceed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issue",
        default=None,
        help="Issue number from the resolved PR head branch",
    )
    args = parser.parse_args()

    issue = parse_issue_number(args.issue)
    if issue is None:
        print(
            "merge-status: SKIP — head branch does not resolve to an issue number; "
            "treating as a non-issue-slice branch. Not a green result, just logged."
        )
        return 0

    passed, detail = evaluate(issue)
    return print_check_result("merge-status", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
