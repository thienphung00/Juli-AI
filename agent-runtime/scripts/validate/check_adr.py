#!/usr/bin/env python3
"""Gate: architectural changes include a new ADR."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    ADR_FILE_RE,
    REPO_ROOT,
    STATUS_DIR,
    architectural_change_detected,
    git_changed_files,
    load_json,
    load_review_artifact,
    new_adr_files,
    parse_args,
    print_check_result,
    resolve_issue_number,
)

# The verdict when no source can answer. Kept as a named constant because the
# whole point of #1529 is that this state is distinguishable from "the review
# looked and found nothing".
UNRESOLVED = "unresolved"

# What the committed status record cannot see. Reported in the gate's details on
# every verdict it decides, so the residual gap is legible rather than implied.
STATUS_RECORD_BLIND_SPOT = (
    "status record carries no interfaceChanges: a breaking interface change that "
    "produced no critical finding is not visible to this source (#1529)"
)


def validate_adr_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    if "**Status:**" not in text and "## Status" not in text:
        problems.append("missing Status")
    for section in ("## Context", "## Decision", "## Rationale", "## Consequences"):
        if section not in text:
            problems.append(f"missing {section}")
    return problems


def _load_status_record(issue: int) -> dict[str, Any] | None:
    """Read the committed status record for an issue, or None if unreadable.

    ``agent-runtime/artifacts/status/`` is the one artifact directory that is
    not gitignored, so this is the only review-derived evidence a CI checkout
    can actually see.
    """
    try:
        record = load_json(STATUS_DIR / f"issue-{issue}.json")
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def resolve_architectural_change(
    issue: int, changed: list[str]
) -> tuple[bool | None, str, list[str]]:
    """Answer "was this an architectural change?", name the source, and declare
    what that source could not see.

    ``None`` means *no source could answer* -- which is not the same as "no", and
    is the distinction this gate previously did not make. It read
    ``load_review_artifact(issue) or {}`` and evaluated the two review-derived
    limbs of ``architectural_change_detected`` against an empty dict. Review
    bodies are gitignored by policy (ADR-003: emit is not commit), so in CI --
    the only place this gate blocks -- both limbs were structurally dead and the
    gate reported PASS on every commit, architectural or not.

    The ladder, strongest evidence first:

    1. ``diff`` -- a ``docs/architecture/map.md`` edit. CI sees the diff in full,
       and this limb is conclusive whenever it fires, review or no review.
    2. ``review-artifact`` -- the body on disk. The only source carrying both
       ``criticalFindings[].type == "interface_change"`` and
       ``interfaceChanges[].breaking``. Present in the local loop, never in CI.
    3. ``status-record`` -- ``agent-runtime/artifacts/status/issue-<N>.json`` is
       the one artifact directory that is not gitignored, so it is the only
       review-derived evidence a CI checkout can see, and
       ``metrics.criticalFindings`` is derived from the review body by
       ``generate_status_records.py``. It answers in both directions, with one
       gap it must declare rather than hide: the record carries no
       ``interfaceChanges``, and ``derive_review_status`` forces neither a
       critical finding nor a non-PASS status for a ``breaking: true`` entry, so
       a ``breaking`` interface change that produced no critical finding is
       invisible here. Closing that needs an ``architecturalChange`` boolean on
       the record itself (issue #1529, notes) -- a schema change to
       ``generate_status_records.py`` and its consumers, out of scope for this
       gate. Until then the limitation rides in the gate's own details, where a
       reader can see it, instead of being silently spent as a PASS.
    4. Nothing left: ``None``. The caller fails closed, matching
       ``check_artifact_retention_guard``'s posture -- red until the status
       record lands, by design.
    """
    if any("docs/architecture/map.md" in c for c in changed):
        return True, "diff", []

    try:
        review = load_review_artifact(issue)
    except (OSError, json.JSONDecodeError):
        review = None
    if review is not None:
        return architectural_change_detected(review, changed), "review-artifact", []

    record = _load_status_record(issue)
    if record is not None:
        metrics = record.get("metrics")
        count = metrics.get("criticalFindings") if isinstance(metrics, dict) else None
        if isinstance(count, int):
            return count > 0, "status-record", [STATUS_RECORD_BLIND_SPOT]

    return None, UNRESOLVED, []


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    changed = git_changed_files()
    arch_change, evidence_source, limitations = resolve_architectural_change(issue, changed)
    adrs = new_adr_files(changed)

    adr_problems: dict[str, list[str]] = {}
    for rel in adrs:
        path = REPO_ROOT / rel
        name = path.name
        if not ADR_FILE_RE.match(name):
            adr_problems[name] = ["filename must match NNN-slug.md"]
            continue
        problems = validate_adr_file(path)
        if problems:
            adr_problems[name] = problems

    details = {
        "architecturalChange": arch_change,
        "evidenceSource": evidence_source,
        "evidenceLimitations": limitations,
        "adrPresent": bool(adrs),
        "adrs": adrs,
        "adrProblems": adr_problems,
    }

    if arch_change is False:
        return True, "No architectural change detected", details
    if not adrs:
        if arch_change is None:
            return (
                False,
                (
                    f"Cannot determine whether issue {issue} is an architectural "
                    "change: the review body is gitignored by ADR-003 and no "
                    "status record exists at agent-runtime/artifacts/status/"
                    f"issue-{issue}.json, so no source could answer, and this diff "
                    "adds no ADR. Failing closed rather than reading silence as 'no'."
                ),
                details,
            )
        return False, "Architectural change requires new ADR in docs/adr/", details
    # Fail-closed, not fail-always: a well-formed ADR in the diff satisfies the
    # requirement whichever way the unreadable review would have gone, so an
    # unresolved signal has nothing left to be uncertain about.
    if adr_problems:
        return False, "ADR file structure invalid", details
    return True, "ADR present for architectural change", details


def main() -> int:
    args = parse_args("Validate ADR requirement")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("adr_requirement", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
