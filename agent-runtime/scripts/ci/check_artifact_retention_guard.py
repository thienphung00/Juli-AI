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

from artifact_ref_resolution import (
    INDETERMINATE,
    MATCH,
    POLICY_LOCAL,
    RefResolution,
    resolve_record_refs,
)
from common import AGENT_RUNTIME_ROOT, REPO_ROOT, STATUS_DIR, print_check_result
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


def _summarise_refs(resolutions: list[RefResolution]) -> str:
    return "; ".join(resolution.detail for resolution in resolutions)


def _ref_verdict(
    gate_version: object, resolutions: list[RefResolution], record_path: Path
) -> tuple[bool, str] | None:
    """#1445: fail a gateVersion 2 record whose refs do not resolve or whose
    recorded sha256 does not match what they resolve to.

    Returns ``(False, reason)`` to fail the record, or ``None`` to let it stand.
    gateVersion 1 records never fail here: their verbose bodies exist on no
    machine (#670 recorded an integrity chain into a store that was never built),
    and the Architect lock on this slice forbids repairing history to invent them.
    They are marked instead -- see the detail strings built in ``evaluate``.
    """
    if gate_version != 2:
        return None
    broken = [resolution for resolution in resolutions if resolution.is_failure]
    if not broken:
        return None
    return False, (
        f"{record_path}: gateVersion 2 record has {len(broken)} artifactRef integrity "
        f"failure(s) — {_summarise_refs(broken)}"
    )


def evaluate(
    issue: int,
    *,
    status_dir: Path = STATUS_DIR,
    repo_root: Path = REPO_ROOT,
) -> tuple[bool, str]:
    """Existence + PASS + artifactRef-integrity check for one issue's status record.

    Returns ``(passed, detail)``. Every branch below either returns ``(False, <reason>)``
    or falls through to the single ``(True, ...)`` at the end, reached only after the
    record parsed as a JSON object, validated against the status-record schema, matched
    the requested issue number, both ``review.status`` and ``validation.status`` read
    ``"PASS"``, and -- from ``gateVersion`` 2 on -- every ``artifactRef`` either
    resolved to content matching its recorded ``sha256`` (``git-history:``) or
    honestly declared itself unretrievable by policy (``local-only:``, #1497).
    Either way the refs are named in the returned detail, never swallowed.
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
        return False, (f"{record_path} does not match the status-record schema: {schema_errors[0]}")

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
    if review_status not in {"PASS", "PASS_WITH_WARNINGS"}:
        return (
            False,
            f"{record_path}: review gate is {review_status!r}, "
            "required PASS or a fully signed-off PASS_WITH_WARNINGS",
        )

    # #1141: PASS_WITH_WARNINGS is what `validate` emits for a slice whose
    # warnings were reviewed, acknowledged per finding, and signed off by the
    # owner -- ADR-003 treats that as shippable. Requiring literal "PASS" here
    # made it unlandable, so the two states a reviewer can legitimately reach
    # were "clean" and "permanently blocked", with no way to ship an accepted
    # warning. This does not soften the gate: PASS_WITH_WARNINGS is admitted
    # ONLY with both signoff booleans true. They are written by
    # generate_status_records.py straight from the same `common` helpers
    # check_findings_acknowledged.py and check_owner_signoff.py use, so a record
    # cannot claim signoff the review body does not carry, and a record written
    # by an older generator has neither key -- absent reads as False, so the
    # guard stays fail-closed against anything it cannot positively verify.
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

    validation_status = validation.get("status")
    if validation_status != "PASS":
        return False, (
            f"{record_path}: validation gate is {validation_status!r}, required exactly PASS"
        )

    gate_version = payload.get("gateVersion")
    resolutions = resolve_record_refs(payload, repo_root=repo_root)
    failed = _ref_verdict(gate_version, resolutions, record_path)
    if failed is not None:
        return failed

    base = f"{record_path}: review {review_status}, validation PASS"
    unresolved = [resolution for resolution in resolutions if resolution.status != MATCH]
    if not unresolved:
        return True, f"{base}; both artifactRefs resolve and match their recorded sha256"
    # #1497: a ref that correctly declares its body unretrievable-by-policy is not
    # an unresolved integrity claim, it is a different and weaker claim that was
    # honoured. It is still NAMED here rather than swallowed, so a reader can see
    # exactly which evidence this record does and does not stand behind.
    policy_local = [r for r in unresolved if r.status == POLICY_LOCAL]
    if policy_local and all(r.status in {POLICY_LOCAL, INDETERMINATE} for r in unresolved):
        return True, (
            f"{base}; {len(policy_local)} artifactRef(s) name bodies that are "
            f"unretrievable by policy, never committed (ADR-003: emit is not commit) — "
            f"{_summarise_refs(unresolved)}"
        )
    if all(resolution.status == INDETERMINATE for resolution in unresolved):
        return True, (
            f"{base}; artifactRef integrity was NOT determined in this checkout — "
            f"{_summarise_refs(unresolved)}"
        )
    return True, (
        f"{base}; gateVersion {gate_version} artifactRefs marked unresolvable, not "
        f"repaired (Architect lock, #1445: history is not rewritten to invent files "
        f"that exist on no machine) — {_summarise_refs(unresolved)}"
    )


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
