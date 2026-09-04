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

# What the committed status record still cannot see, now that it carries the
# answer itself (#1562). Reported in the gate's details on every verdict this
# source decides, so the residual gap stays legible rather than implied.
#
# It is deliberately no longer the interfaceChanges gap #1529 declared. The
# record now carries both review-derived limbs, so continuing to announce that
# gap would be a notice outliving its limitation -- which is worse than none: it
# teaches a reader to discount the whole list. What is left is narrower and true:
# the answer was computed when the record was generated and is not re-derived
# now, so a review body amended afterwards is not reflected here.
STATUS_RECORD_SNAPSHOT_LIMIT = (
    "status record answers from the review body's interface limbs as they stood "
    "when the record was generated; the body is not re-read here, so a review "
    "amended after generation is not reflected (#1562)"
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


def _architectural_change_from_record(record: dict[str, Any]) -> bool | None:
    """Read the record's typed architectural-change answer, or ``None`` if it has
    none this gate is willing to trust (#1562).

    Three ways to get ``None``, and the difference matters to the caller only in
    that all three fall through to the fail-closed rung:

    * **Absent.** Every one of the ~317 records already on ``main`` predates this
      field and is never backfilled. Absence means *this source cannot answer* --
      it must not be read as "no", which is the precise defect #1529 was filed
      for and would simply have moved one field to the left.
    * **Malformed.** A ``value`` that is not a boolean, or ``signals`` that is
      not a list, was not written by ``generate_status_records``.
    * **Internally inconsistent.** ``value`` is true exactly when ``signals``
      names a limb that fired. A record breaking that invariant is refused in
      *both* directions rather than half-trusted -- this is what makes the field
      harder to counterfeit than the ``metrics.criticalFindings`` count it
      replaces, where any non-zero integer was a positive verdict.

    Note what is NOT consulted: ``metrics.criticalFindings``. It is a count of
    findings of every type and severity, non-zero on 109 of the 316 committed
    records with a guard-admitted review status, and reading it as "an interface
    moved" made this blocking gate demand an ADR on a third of ordinary PRs.
    """
    block = record.get("architecturalChange")
    if not isinstance(block, dict):
        return None
    value = block.get("value")
    signals = block.get("signals")
    if not isinstance(value, bool) or not isinstance(signals, list):
        return None
    if value is not bool(signals):
        return None
    return value


def _unresolved_reason(issue: int) -> str:
    """Say which of the two ways rung 4 was reached actually happened (#1562).

    The verdict, the exit code and the fail-closed posture are #1529's and are
    untouched; only the sentence is corrected. #1529 wrote one message asserting
    "no status record exists", which was true then because a record could always
    answer -- it carried a ``criticalFindings`` integer. Now a record can be
    present and silent (every record on ``main`` predates ``architecturalChange``
    and none is backfilled), so the single message had become false for the
    commonest case: run against issue 718, whose record is committed, it told the
    reader to go look for a file that is already there.
    """
    record_path = STATUS_DIR / f"issue-{issue}.json"
    # Named repo-relative, as #1529 did: an absolute path from a CI runner's
    # checkout directory is noise to the person reading the log.
    shown = f"agent-runtime/artifacts/status/issue-{issue}.json"
    if record_path.is_file():
        why = (
            f"the review body is gitignored by ADR-003 and {shown} carries no "
            "architecturalChange signal (records written before #1562 are not "
            "backfilled), so no source could answer"
        )
    else:
        why = (
            "the review body is gitignored by ADR-003 and no status record exists at "
            f"{shown}, so no source could answer"
        )
    return (
        f"Cannot determine whether issue {issue} is an architectural change: {why}, "
        "and this diff adds no ADR. Failing closed rather than reading silence as 'no'."
    )


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
       review-derived evidence a CI checkout can see. It carries
       ``architecturalChange``, the typed answer ``generate_status_records.py``
       computes from the *same two review-body limbs* rung 2 evaluates live
       (#1562), so this rung is now as informative as rung 2 rather than a
       narrower guess at it. It answers in both directions.

       It reads that field and nothing else. In particular it does not read
       ``metrics.criticalFindings``, which #1529 used as a proxy for "an
       interface moved": an unfiltered count of findings of every type and
       severity, non-zero on 109 of the 316 committed records with a
       guard-admitted review status, so a blocking gate built on it demanded an
       ADR on a third of ordinary PRs -- a factual gate that false-positives,
       which Architect lock 5 forbids, and an inversion of this epic's own defect
       class from "a gate that passes by not looking" into "a review that reports
       nothing so the gate passes".

       A record with no ``architecturalChange`` field -- every record already on
       ``main``, none of which is backfilled -- is not an answer, and drops to
       rung 4 rather than being read as "no".
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
        answer = _architectural_change_from_record(record)
        if answer is not None:
            return answer, "status-record", [STATUS_RECORD_SNAPSHOT_LIMIT]

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
            return False, _unresolved_reason(issue), details
        return False, "Architectural change requires new ADR in docs/adr/", details
    # Fail-closed, not fail-always: a well-formed ADR in the diff satisfies the
    # requirement whichever way the unreadable review would have gone, so an
    # unresolved signal has nothing left to be uncertain about.
    if adr_problems:
        return False, "ADR file structure invalid", details
    return True, "ADR present for architectural change", details


def format_evidence(description: str, details: dict[str, Any]) -> str:
    """Render the verdict *and* the evidence it rests on into one detail line.

    ``main`` previously did ``passed, description, _ = run_check(issue)`` and
    passed ``"" if passed else description`` to ``print_check_result``, so on the
    PASS path CI printed a bare ``adr_requirement: PASS`` and on the FAIL path
    the reason with no provenance. ``evidenceSource`` and ``evidenceLimitations``
    -- which this module's docstring says ride in the gate's own details "where a
    reader can see it" -- were reachable only from unit tests and never appeared
    in the one place the gate actually blocks. A declaration nobody is shown is
    not a declaration, so both verdicts now carry it.
    """
    evidence = (
        f"evidenceSource={details['evidenceSource']}, "
        f"architecturalChange={details['architecturalChange']}"
    )
    limitations = details.get("evidenceLimitations") or []
    if limitations:
        evidence += "; limitations: " + " | ".join(limitations)
    return f"{description} [{evidence}]"


def main() -> int:
    args = parse_args("Validate ADR requirement")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    return print_check_result("adr_requirement", passed, format_evidence(description, details))


if __name__ == "__main__":
    raise SystemExit(main())
