#!/usr/bin/env python3
"""Migration: build compact status/issue-<N>.json records from existing
review + validation artifact pairs (#670 P1 Option A).

Reconciles the audit's committed-artifact-volume cost driver with ADR-052's
locked intent to keep a committed merge-time source of truth: a small
compact record replaces the verbose bodies as the wave->main artifact-gate
read path (see wave_manifest.py `_validate_issue_artifacts`), while the
verbose bodies themselves move to CI artifact retention (`git rm` is a
separate step — see the issue's migration recipe; this script only reads
and never deletes).

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
from capture_providers import (  # noqa: E402
    CaptureContext,
    capture_run_block,
    discover_providers,
)
from common import (  # noqa: E402
    REVIEWS_DIR,
    STATUS_DIR,
    VALIDATION_DIR,
    normalize_review_findings,
    owner_signoff_valid,
    unacknowledged_findings,
    utc_now_iso,
    warnings_require_signoff,
)


def _ref_scheme_seam() -> tuple[str, Any, Any]:
    """Load the artifactRef scheme vocabulary (#1497) from ``artifact_ref_resolution``.

    Imported inside a function, not at module scope: a third module-level import
    after the ``sys.path`` insert above would add a third ``# noqa: E402`` unit to
    this file, and the repo's debt ratchet counts suppression *units*, not just
    distinct identities (``tests/unit/test_ratchets.py``). Import cosmetics are not
    worth a unit of tracked debt -- the pattern is the one
    ``tests/unit/test_command_subsumption_provider.py::_load_seam`` uses.
    """
    from artifact_ref_resolution import (
        GIT_HISTORY_SCHEME,
        is_policy_local_path,
        policy_local_ref,
    )

    return GIT_HISTORY_SCHEME, is_policy_local_path, policy_local_ref


WAVES_DIR = STATUS_DIR.parent / "waves"
# 2 (#1438): records carry the run{} capture envelope. v1 records are NOT
# backfilled — see the schema's gateVersion description.
GATE_VERSION = 2

# Register every capture provider shipped under capture_providers/. This is the
# only line that knows the seam exists: a slice adding token counts, transcript
# parsing or git evidence drops one module into that package and is picked up
# here, so parallel slices never contend on this file. Failure to discover is
# not caught — a provider that cannot even be loaded must not produce a record
# that silently lacks its block.
discover_providers()


#: #1562: the two review-body limbs that mean "an interface moved". They are the
#: review-derived half of ``common.architectural_change_detected`` -- the same
#: two, named, so the record says *which* one fired instead of only that one did.
#: The third limb of that function (a ``docs/architecture/map.md`` edit) is
#: deliberately absent: it is a property of the diff, not of the review, this
#: script has no diff, and ``check_adr`` reads it directly and conclusively at
#: rung 1, ahead of the record. Folding it in would mean recording a stale
#: answer to a question the reader can always answer for itself.
SIGNAL_INTERFACE_CHANGE_FINDING = "interface-change-finding"
SIGNAL_BREAKING_INTERFACE_CHANGE = "breaking-interface-change"


def derive_architectural_change(review: dict[str, Any]) -> dict[str, Any]:
    """Answer "was this an architectural change?" from the review body, in a form
    a CI checkout can read (#1562).

    ``check_adr``'s rung 3 previously answered this from
    ``metrics.criticalFindings > 0`` -- an unfiltered count of findings of every
    type and severity, standing in for "an interface moved". It is lossy in both
    directions: it fires on 109 of the 316 committed records with a
    guard-admitted review status (a blocking demand for an ADR on a third of
    ordinary PRs), and it misses a ``breaking: true`` interface entry that
    produced no critical finding, because ``derive_review_status`` forces neither
    a finding nor a non-PASS status for one.

    So the answer is computed here, once, from the body that actually carries the
    evidence, and written into the one artifact directory ``.gitignore`` keeps
    tracked. ``signals`` is not decoration: it names the limb that fired, which
    makes the verdict auditable from the record alone and makes the shape hard to
    counterfeit -- a boolean re-derived from a finding count can set ``value``
    but cannot name a limb, and ``check_adr`` refuses a record whose ``value``
    and ``signals`` disagree.

    Never raises on a malformed body: a non-dict finding is skipped, not trusted.
    A body that names no limb yields ``value: False`` -- which is a real answer,
    because this function has read the whole body. It is the *record's absence*
    of the field, not a ``False`` in it, that means "could not tell".
    """
    signals: list[str] = []
    findings = review.get("criticalFindings")
    if isinstance(findings, list) and any(
        isinstance(finding, dict) and finding.get("type") == "interface_change"
        for finding in findings
    ):
        signals.append(SIGNAL_INTERFACE_CHANGE_FINDING)
    changes = review.get("interfaceChanges")
    if isinstance(changes, list) and any(
        isinstance(change, dict) and change.get("breaking") for change in changes
    ):
        signals.append(SIGNAL_BREAKING_INTERFACE_CHANGE)
    return {"value": bool(signals), "signals": signals}


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

    _, _, policy_local_ref = _ref_scheme_seam()
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

    # Providers run before the record is assembled so a raising provider aborts
    # generation outright (fail-closed): there is no path that writes a record
    # whose block is quietly missing. Nothing here knows what any block means.
    run = capture_run_block(
        CaptureContext(
            issue=issue,
            review=review,
            validation=validation,
            review_bytes=review_bytes,
            validation_bytes=validation_bytes,
        )
    )

    return {
        "issue": issue,
        "wave": _wave_for_issue(issue),
        "review": {
            "status": review_status,
            # #1141: PASS_WITH_WARNINGS is a legitimate ship state for `validate`
            # once both dual-signoff gates pass, but the retention guard reads
            # only this committed record -- the review body it would need to
            # re-check those gates lives in a gitignored directory and never
            # reaches CI. Carrying the two gate outcomes forward is what lets the
            # guard tell "warnings, acknowledged and signed off" apart from
            # "warnings, unaddressed" without widening what it trusts. Both are
            # derived here from the same `common` helpers the validate gates use,
            # never hand-written.
            "signoffRequired": warnings_require_signoff(review),
            "warningsAcknowledged": not unacknowledged_findings(normalize_review_findings(review)),
            "ownerSignoffPresent": owner_signoff_valid(review)[0],
            # #1497: NOT git-history:. .gitignore forbids committing this body by
            # policy (ADR-003: emit is not commit), so a git-history claim about it
            # can never be satisfied -- which is exactly what made every gateVersion
            # 2 record unpassable once #1445 began checking. local-only: claims only
            # what is true: the body existed on this machine and this is its sha256.
            "artifactRef": policy_local_ref(
                f"agent-runtime/artifacts/reviews/review-issue-{issue}.json"
            ),
            "sha256": _sha256_bytes(review_bytes),
        },
        "validation": {
            "status": effective_validation_status,
            "artifactRef": policy_local_ref(
                f"agent-runtime/artifacts/validation/validation-issue-{issue}.json"
            ),
            "sha256": _sha256_bytes(validation_bytes),
        },
        # #1562: the typed architectural-change answer, so check_adr's rung 3
        # reads a signal instead of guessing from a finding count. Sits beside
        # metrics rather than inside it: metrics is a bag of volume measures,
        # and this is a verdict about the change, not a measurement of it.
        "architecturalChange": derive_architectural_change(review),
        "metrics": {
            "acceptanceTotal": acceptance.get("total", 0),
            "acceptanceMapped": acceptance.get("mapped", 0),
            "criticalFindings": len(review.get("criticalFindings") or []),
            "modulesTouched": review.get("modulesTouched") or [],
        },
        "run": run,
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


def relabel_policy_local_refs(*, dry_run: bool = False) -> list[int]:
    """One-off correction for records committed before #1497.

    #1438's generator stamped ``git-history:`` onto body paths ``.gitignore``
    forbids committing. Those records cannot simply be regenerated -- their
    bodies are gitignored and long gone from the machines that wrote them -- but
    the wrong part of them is only the *label*. The ``sha256`` is still the
    digest of the body that existed, and stays byte-for-byte untouched here; all
    this does is replace a retrievability claim that was never true with the one
    that is.

    Two deliberate exclusions:

    * ``gateVersion`` 1 records are left alone. The Architect lock on #1445 says
      history is not backfilled, and those records are already handled by the
      guard's mark-don't-fail path.
    * A ``git-history:`` ref to a path outside the five body directories is left
      alone. Nothing forbids committing it, so its claim is checkable and must
      stay checked -- relabelling is a correction, never a way to silence a
      genuinely dangling ref.

    Returns the issue numbers whose records changed; idempotent.
    """
    git_history_scheme, is_policy_local_path, policy_local_ref = _ref_scheme_seam()
    changed: list[int] = []
    if not STATUS_DIR.is_dir():
        return changed
    for path in sorted(STATUS_DIR.glob("issue-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or record.get("gateVersion") != GATE_VERSION:
            continue
        touched = False
        for name in ("review", "validation"):
            block = record.get(name)
            if not isinstance(block, dict):
                continue
            ref = str(block.get("artifactRef", ""))
            if not ref.startswith(git_history_scheme):
                continue
            target = ref[len(git_history_scheme) :]
            if not is_policy_local_path(target):
                continue
            block["artifactRef"] = policy_local_ref(target)
            touched = True
        if not touched:
            continue
        if not dry_run:
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        issue = record.get("issue")
        if isinstance(issue, int):
            changed.append(issue)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be generated without writing files",
    )
    parser.add_argument(
        "--relabel-policy-local-refs",
        action="store_true",
        help=(
            "#1497 one-off: rewrite git-history: artifactRefs on gateVersion 2 "
            "records to local-only: where the path is a gitignored artifact body. "
            "sha256 values are never touched."
        ),
    )
    args = parser.parse_args()

    if args.relabel_policy_local_refs:
        changed = relabel_policy_local_refs(dry_run=args.dry_run)
        verb = "would relabel" if args.dry_run else "relabelled"
        print(f"status records: {verb} {len(changed)} for issues {changed}")
        return 0

    generated = migrate(dry_run=args.dry_run)
    verb = "would generate" if args.dry_run else "generated"
    print(f"status records: {verb} {len(generated)} for issues {generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
