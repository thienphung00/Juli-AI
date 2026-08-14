#!/usr/bin/env python3
"""Issue-tier artifact retention guard (#1064).

Design correction (see #1064's "Design correction before implementation" comment):
ADR-079 originally described this as an artifact-retention gate, but ``pr.yml`` has no
``upload-artifact`` step for the five gitignored artifact body directories and cannot
have one -- those bodies are never committed, so nothing reaches the runner to upload.
What CI *can* see is the compact per-issue record ``.gitignore`` deliberately keeps
tracked at ``agent-runtime/artifacts/status/issue-<N>.json`` (ADR-052's #670 P1 Option A
amendment). This script performs an existence + status read of that one committed file --
not the heavy per-push ``meta_prepare_executor`` / ``check_*.py`` re-run ADR-052 correctly
deferred off the issue tier. See ``docs/adr/052-wave-free-merge-deferred-artifact-gate.md``
for the note pointing back at this issue.

Fail-closed, always: a missing, unreadable, malformed, schema-invalid, or issue-mismatched
record is a FAIL. There is no code path that returns "passed" without having read a
genuine ``review.status == "PASS"`` and ``validation.status == "PASS"`` record for the
right issue. The one non-FAIL outcome is SKIP, reserved for a branch that never resolved
an issue number at all (docs/hotfix/non-issue branches reaching the issue tier) --
every skip still prints its reason; nothing is ever silently passed over.

This script only ever reads ``agent-runtime/artifacts/status/`` -- the one artifact
directory ``.gitignore`` keeps tracked. It never reads or writes the five gitignored
artifact body directories (``reviews/``, ``implementations/``, ``intent-reviews/``,
``validation/``, ``optimization/``) and never ``git add -f``s anything.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import AGENT_RUNTIME_ROOT, STATUS_DIR, print_check_result
from json_schema_validate import validate_json_schema

STATUS_SCHEMA_PATH = AGENT_RUNTIME_ROOT / "docs" / "schemas" / "status-record.schema.json"

# The command an Executor/Review agent runs to (re)produce a missing record from the
# review + validation artifacts already written to the working tree during the loop.
GENERATE_COMMAND = "python agent-runtime/scripts/ci/generate_status_records.py"


def status_record_path(issue: int, status_dir: Path = STATUS_DIR) -> Path:
    return status_dir / f"issue-{issue}.json"


def parse_issue_number(raw: str | None) -> int | None:
    """Return the resolved issue number, or ``None`` when ``raw`` is not one.

    ``None`` is the SKIP signal: the branch this job ran for is not an issue slice.
    ``resolve-issue`` in pr.yml already regexes ``issue-([0-9]+)`` out of the PR head
    branch; when that fails to match (docs/hotfix/non-issue branches on the issue tier)
    it emits an empty string, which lands here as ``raw=""``.
    """
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


def evaluate(issue: int, *, status_dir: Path = STATUS_DIR) -> tuple[bool, str]:
    """Existence + PASS check for one issue's committed status record.

    Returns ``(passed, detail)``. Every branch below either returns ``(False, <reason>)``
    or falls through to the single ``(True, ...)`` at the end, reached only after the
    record parsed as a JSON object, validated against the status-record schema, matched
    the requested issue number, and both ``review.status`` and ``validation.status`` read
    exactly ``"PASS"``.
    """
    record_path = status_record_path(issue, status_dir)

    if not record_path.is_file():
        return False, (
            f"missing {record_path} for issue {issue} — an issue-tier PR must commit a "
            f"PASS status record before this check can pass (produce it with: "
            f"{GENERATE_COMMAND})"
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
        detail = f"{record_path} does not match the status-record schema: {schema_errors[0]}"
        return False, detail

    if payload.get("issue") != issue:
        return False, (
            f"{record_path} is a record for issue {payload.get('issue')!r}, not {issue} — "
            "refusing to treat a mismatched record as evidence"
        )

    review = payload.get("review")
    validation = payload.get("validation")
    if not isinstance(review, dict) or not isinstance(validation, dict):
        return (
            False,
            f"{record_path} is missing review/validation objects (unexpected schema)",
        )

    review_status = review.get("status")
    if review_status != "PASS":
        return (
            False,
            f"{record_path}: review gate is {review_status!r}, required exactly PASS",
        )

    validation_status = validation.get("status")
    if validation_status != "PASS":
        return False, (
            f"{record_path}: validation gate is {validation_status!r}, required exactly PASS"
        )

    return True, f"{record_path}: review PASS, validation PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issue",
        default=None,
        help=(
            "Issue number resolved from the PR head branch by the resolve-issue job "
            "(empty/absent means the branch is not an issue slice; SKIP, not FAIL)"
        ),
    )
    args = parser.parse_args()

    issue = parse_issue_number(args.issue)
    if issue is None:
        print(
            "artifact_retention_guard: SKIP — head branch does not resolve to an issue "
            f"number (resolve-issue gave {args.issue!r}); treating as a non-issue-slice "
            "branch (docs/hotfix/wave) on the issue tier. Not silently passed: this is a "
            "deliberate, logged skip, not a green result."
        )
        return 0

    passed, detail = evaluate(issue)
    return print_check_result("artifact_retention_guard", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
