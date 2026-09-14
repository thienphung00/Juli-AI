"""The judge runs as a sampler — advisory, with canaries on every invocation
(#1460, HE-D/P-EVAL-17).

A judge scored by the same model class that produced the output is not an
independent reward. `k=3` self-consistency does not supply independence either:
three samples from one model share its blind spots, so self-consistency
measures **variance**, not bias. What supplies independence is human labels,
canaries, and staying advisory until calibrated (#1461 — kappa against human
labels, a temporal holdout, a promotion PR; a separate, four-week HITL slice
not built here).

So until kappa clears: **the judge's job is triage, not verdict.** It is a
sampler that surfaces records worth a human's attention — which beats random
sampling of a corpus that is 98% passes. Concretely, this module enforces four
things and builds nothing beyond them:

1. Every invocation runs the invoked rubric's canaries **first**. A canary
   returning anything but `fail` aborts with exit code 2 — a judge that has
   quietly stopped discriminating is indistinguishable from a clean repo (see
   `eval.canaries`).
2. A named-but-missing canary is a hard error (`eval.canaries.CanaryNotFoundError`),
   never a silent skip.
3. Every verdict this module produces carries `state: "advisory"`. Nothing
   here can write `"calibrated"` — that is #1461's promotion path.
4. Sampling emits a stratified candidate list — 5 pass / 3 fail / 2
   cannot_determine — for human labelling, not a grade.

The `heuristic_scorer` below is a deterministic, offline stand-in for a real
model call. Building an actual LLM-backed judge is out of scope for this
slice; what this module owns is the contract around *any* scorer matching the
`Scorer` signature — canary-gated, advisory-only, sampler-shaped. #1461 (or a
later slice) can swap the scorer without touching this contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from eval.artifact_mutants import ORACLE_PYTEST_COMMAND
from eval.canaries import (
    CANARY_DIR,
    Canary,
    CanaryNotFoundError,
    load_canary,
)
from eval.rubrics import RUBRIC_DIR, STATE_DIR, Rubric, load_rubric

REPO_ROOT = Path(__file__).resolve().parents[1]

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_CANNOT_DETERMINE = "cannot_determine"
VERDICTS = (VERDICT_PASS, VERDICT_FAIL, VERDICT_CANNOT_DETERMINE)

#: A canary must score exactly this to prove the judge still discriminates.
REQUIRED_CANARY_VERDICT = VERDICT_FAIL

EXIT_OK = 0
#: "aborts the run with exit code 2" — acceptance criterion 1 (#1460).
EXIT_CANARY_FAILED = 2
#: Reserved for the CLI: a named-but-missing canary is a hard error, not a
#: silent skip, and gets a distinct exit code from "canary ran and disagreed".
EXIT_CANARY_MISSING = 3
#: #1896: the corpus could not fill a stratum. Distinct from both canary exit
#: codes above — this is neither "the judge stopped discriminating" nor "a
#: rubric names a canary that does not exist", it is "the corpus itself is too
#: skewed to sample from today". Reported, never turned into a short list that
#: reads as a full one.
EXIT_SAMPLER_SHORTFALL = 4

Scorer = Callable[[dict[str, Any], str], str]


class CanaryDidNotFailError(RuntimeError):
    """A canary — a record with a KNOWN, planted defect — scored anything but
    `fail`. Raised (not just turned into a CLI exit code) so library callers
    can observe it without spawning a subprocess."""


# ---------------------------------------------------------------------------
# the stand-in scorer
#
# Deliberately rule-based and offline. It exists to prove the canary/advisory/
# sampler *contract* end to end, matched precisely against what each of
# #1457's seven operators plants (`eval.artifact_mutants`), not to be a good
# judge of arbitrary prose.
# ---------------------------------------------------------------------------


def _score_review(record: dict[str, Any]) -> str:
    status = record.get("status")
    findings = record.get("criticalFindings") or []
    unresolved_critical = any(
        isinstance(f, dict) and f.get("severity") == "CRITICAL" for f in findings
    )
    # self_reported_pass: status=PASS asserted over the record's own
    # unresolved CRITICAL finding.
    if status == "PASS" and unresolved_critical:
        return VERDICT_FAIL

    # dangling_artifact_ref: sourceImplementationArtifact must follow the
    # repo's own fixed naming convention for the issue it claims to be. A
    # value that deviates from it names a path this record did not produce.
    issue = record.get("issue")
    source_ref = record.get("sourceImplementationArtifact")
    if issue is not None and source_ref is not None:
        expected_ref = f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json"
        if source_ref != expected_ref:
            return VERDICT_FAIL

    # unbacked_claim: an acceptance mapping cites a test node. Check the node
    # actually exists in the tree rather than trusting the claim.
    mappings = ((record.get("testCoverage") or {}).get("acceptance") or {}).get("mappings") or []
    for mapping in mappings:
        test_ref = mapping.get("test", "")
        path_part, _, symbol = test_ref.partition("::")
        test_path = REPO_ROOT / path_part
        if not path_part or not symbol or not test_path.is_file():
            return VERDICT_FAIL
        if symbol not in test_path.read_text():
            return VERDICT_FAIL

    if status in ("PASS", "FAIL"):
        return VERDICT_PASS if status == "PASS" else VERDICT_FAIL
    return VERDICT_CANNOT_DETERMINE


def _score_implementation(record: dict[str, Any]) -> str:
    cycles = record.get("redGreenRefactorEvidence") or []
    if not cycles:
        return VERDICT_CANNOT_DETERMINE
    for cycle in cycles:
        # vacuous_test_evidence: red/green narrated in prose, no commands array.
        commands = cycle.get("commands")
        if not commands:
            return VERDICT_FAIL
        for command in commands:
            # narrowed_command_scope + environment_mismatch: either the
            # selector is narrower than the oracle's, or the oracle command is
            # wrapped in a foreign interpreter/PYTHONPATH. Both show up as
            # "the recorded command is not the oracle command".
            if command.get("command") != ORACLE_PYTEST_COMMAND:
                return VERDICT_FAIL
    return VERDICT_PASS


def _score_validation(record: dict[str, Any]) -> str:
    checks = record.get("checks") or []
    # missing_artifact_as_skipped: a missing input recorded as SKIP while the
    # run still reports PASS overall.
    any_skipped = any(isinstance(c, dict) and c.get("status") == "SKIP" for c in checks)
    if any_skipped and record.get("status") == "PASS":
        return VERDICT_FAIL
    status = record.get("status")
    if status in ("PASS", "FAIL"):
        return VERDICT_PASS if status == "PASS" else VERDICT_FAIL
    return VERDICT_CANNOT_DETERMINE


_SCORERS_BY_TYPE: dict[str, Callable[[dict[str, Any]], str]] = {
    "review": _score_review,
    "implementation": _score_implementation,
    "validation": _score_validation,
}


def heuristic_scorer(record: dict[str, Any], artifact_type: str) -> str:
    """Deterministic stand-in for a real model call. See module docstring."""
    scorer = _SCORERS_BY_TYPE.get(artifact_type)
    if scorer is None:
        return VERDICT_CANNOT_DETERMINE
    return scorer(record)


# ---------------------------------------------------------------------------
# canary gate — every invocation, first
# ---------------------------------------------------------------------------


def run_canaries(
    rubric: Rubric,
    *,
    canary_dir: Path = CANARY_DIR,
    scorer: Scorer = heuristic_scorer,
) -> list[dict[str, str]]:
    """Evaluate every canary the rubric names, in order, before any real
    record is scored.

    Raises `CanaryNotFoundError` (propagated, not caught here) the moment a
    named canary has no record on disk — a hard error per acceptance
    criterion 2. Raises `CanaryDidNotFailError` the moment a canary scores
    anything but `fail` — acceptance criterion 1's exit-2 condition.
    """
    results: list[dict[str, str]] = []
    for canary_id in rubric.canary_ids:
        canary: Canary = load_canary(canary_id, canary_dir=canary_dir)
        verdict = scorer(canary.record, canary.artifact_type)
        results.append({"canaryId": canary_id, "verdict": verdict})
        if verdict != REQUIRED_CANARY_VERDICT:
            raise CanaryDidNotFailError(
                f"canary {canary_id!r} for rubric {rubric.id!r} scored "
                f"{verdict!r}, not {REQUIRED_CANARY_VERDICT!r} — the judge has "
                "stopped discriminating (#1460); aborting before any real "
                "record is scored"
            )
    return results


# ---------------------------------------------------------------------------
# advisory verdicts — never blocking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeVerdict:
    record_id: str
    rubric_id: str
    rubric_hash: str
    verdict: str
    #: Always "advisory" — see module docstring. Not Optional and not a free
    #: string: a caller cannot construct a blocking verdict through this type
    #: without lying about the constant.
    state: str = "advisory"


def is_blocking(verdict: JudgeVerdict) -> bool:
    """Always False today. Exists so a gate can call this instead of reading
    `verdict.state` itself — one seam, so the day #1461 introduces a
    calibrated/blocking state, every call site is already routed through a
    function that can be updated once instead of N inline string comparisons."""
    return False


def ensure_never_blocking(verdicts: Iterable[JudgeVerdict]) -> None:
    """Assert the invariant a gate must never violate: no verdict from this
    module may be consumed as blocking. Raises rather than returning a bool —
    a caller checking a bool can choose to ignore it; a caller that must catch
    an exception cannot silently proceed past a violation."""
    for verdict in verdicts:
        if verdict.state != "advisory" or is_blocking(verdict):
            raise AssertionError(
                f"verdict {verdict!r} is not advisory; no gate may consume a "
                "judge verdict as blocking (#1460)"
            )


def judge_records(
    rubric: Rubric,
    records: Sequence[tuple[str, dict[str, Any], str]],
    *,
    scorer: Scorer = heuristic_scorer,
) -> list[JudgeVerdict]:
    """Score real records under `rubric`. Callers must run `run_canaries`
    first — this function does not re-check them, so it must never be called
    directly from the CLI without that gate having already passed."""
    return [
        JudgeVerdict(
            record_id=record_id,
            rubric_id=rubric.id,
            rubric_hash=rubric.rubric_hash,
            verdict=scorer(record, artifact_type),
            state="advisory",
        )
        for record_id, record, artifact_type in records
    ]


# ---------------------------------------------------------------------------
# one entry point: canaries, then verdicts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeRunResult:
    exit_code: int
    rubric: Rubric | None
    canary_results: list[dict[str, str]]
    verdicts: list[JudgeVerdict]
    error: str | None = None


def run_judge(
    rubric_id: str,
    records: Sequence[tuple[str, dict[str, Any], str]] = (),
    *,
    rubric_dir: Path = RUBRIC_DIR,
    canary_dir: Path = CANARY_DIR,
    state_dir: Path = STATE_DIR,
    scorer: Scorer = heuristic_scorer,
) -> JudgeRunResult:
    """The one function a caller needs. `CanaryNotFoundError` propagates
    uncaught — a missing canary is a hard error, not a result to report."""
    rubric = load_rubric(rubric_id, rubric_dir=rubric_dir, state_dir=state_dir)

    try:
        canary_results = run_canaries(rubric, canary_dir=canary_dir, scorer=scorer)
    except CanaryDidNotFailError as exc:
        return JudgeRunResult(
            exit_code=EXIT_CANARY_FAILED,
            rubric=rubric,
            canary_results=[],
            verdicts=[],
            error=str(exc),
        )

    verdicts = judge_records(rubric, records, scorer=scorer)
    ensure_never_blocking(verdicts)
    return JudgeRunResult(
        exit_code=EXIT_OK,
        rubric=rubric,
        canary_results=canary_results,
        verdicts=verdicts,
    )


# ---------------------------------------------------------------------------
# sampler — stratified candidates for human labelling
# ---------------------------------------------------------------------------

#: Fixed stratification per acceptance criterion 4 (#1460): 5 pass, 3 fail, 2
#: cannot_determine. Order matters only for output readability; selection
#: within a stratum preserves input order for determinism.
STRATA: tuple[tuple[str, int], ...] = (
    (VERDICT_PASS, 5),
    (VERDICT_FAIL, 3),
    (VERDICT_CANNOT_DETERMINE, 2),
)


class InsufficientCandidatesError(RuntimeError):
    """A stratum has fewer verdicts than the sampler needs. Raised rather than
    silently sampling fewer — a short list a human cannot tell is short is
    worse than a loud failure."""


def _verdict_of(item: JudgeVerdict | dict[str, Any]) -> str:
    return item.verdict if isinstance(item, JudgeVerdict) else item["verdict"]


def _record_id_of(item: JudgeVerdict | dict[str, Any]) -> str:
    if isinstance(item, JudgeVerdict):
        return item.record_id
    return item.get("recordId", item.get("record_id", item.get("id", "")))


def stratified_sample(
    candidates: Sequence[JudgeVerdict] | Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    """Emit the stratified candidate list a sampler run hands to a human
    labeller: 5 `pass`, 3 `fail`, 2 `cannot_determine`, always in that order.
    """
    pools: dict[str, list[dict[str, str]]] = {v: [] for v, _ in STRATA}
    for item in candidates:
        verdict = _verdict_of(item)
        if verdict not in pools:
            continue
        pools[verdict].append({"recordId": _record_id_of(item), "verdict": verdict})

    selected: list[dict[str, str]] = []
    for verdict, count in STRATA:
        pool = pools[verdict]
        if len(pool) < count:
            raise InsufficientCandidatesError(
                f"sampler needs {count} {verdict!r} candidates for stratified "
                f"labelling, only {len(pool)} available"
            )
        selected.extend(pool[:count])
    return selected


# ---------------------------------------------------------------------------
# corpus reader — the committed status-record corpus, the only artifact set
# that survives merge (#1896)
# ---------------------------------------------------------------------------

#: `agent-runtime/artifacts/status/issue-*.json`. The five body directories
#: (`reviews/`, `implementations/`, `intent-reviews/`, `validation/`,
#: `optimization/`) are gitignored per ADR-003 and never reach a pushed
#: branch — this is the one directory a checkout of `main` actually has.
STATUS_DIR = REPO_ROOT / "agent-runtime" / "artifacts" / "status"


def _review_view(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the review sub-record a committed status record carries.

    Two shapes exist on disk. The current one nests it:
    `{"review": {"status": "PASS", ...}, "validation": {...}, ...}`
    (`generate_status_records.py`, gateVersion 1 and 2 alike — both copy
    `review.status` straight from the review artifact's own `status` field).
    One record predating that migration (`issue-1291.json`) is flat instead:
    `{"reviewStatus": "PASS", ...}`. Both are tolerated so the loader does not
    silently drop the older shape; nothing here invents a third meaning for
    either — a missing status in both shapes surfaces as `None`, which
    `heuristic_scorer`'s review scorer already turns into `cannot_determine`.
    """
    review = payload.get("review")
    if isinstance(review, dict):
        return review
    return {"status": payload.get("reviewStatus")}


def load_status_corpus(status_dir: Path = STATUS_DIR) -> list[tuple[str, dict[str, Any], str]]:
    """Read every committed `issue-*.json` status record and shape it for
    `judge_records`/`run_judge`: `(record_id, record, artifact_type)`.

    Every row is scored as artifact type `"review"`, against the review
    sub-record the status record itself carries — the same `status` field
    `_score_review` already understands (`PASS` / `FAIL` / anything else,
    including `PASS_WITH_WARNINGS`, falls to `cannot_determine` — that is
    `_score_review`'s existing, already-tested behaviour, not a rule invented
    here). A malformed file is skipped, not silently coerced into a verdict:
    a status record this module cannot parse is not evidence about a record
    that exists, it is evidence of nothing.
    """
    if not status_dir.is_dir():
        return []
    records: list[tuple[str, dict[str, Any], str]] = []
    for path in sorted(status_dir.glob("issue-*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        records.append((path.stem, _review_view(payload), "review"))
    return records


def stratum_counts(candidates: Sequence[JudgeVerdict] | Sequence[dict[str, Any]]) -> dict[str, int]:
    """How many candidates fall in each of the three strata, without raising.

    Companion to `stratified_sample`, which raises on the *first* insufficient
    stratum it hits and stops — correct for "never backfill", too narrow for
    "report the shortfall", which needs every stratum's actual count, not just
    the first short one.
    """
    counts: dict[str, int] = {verdict: 0 for verdict, _ in STRATA}
    for item in candidates:
        verdict = _verdict_of(item)
        if verdict in counts:
            counts[verdict] += 1
    return counts


@dataclass(frozen=True)
class SamplerRunResult:
    exit_code: int
    rubric: Rubric | None
    canary_results: list[dict[str, str]]
    #: `{record_id, rubric_id, verdict, note, rubric_hash}` rows, in the shape
    #: #1461 consumes — populated only when `exit_code == EXIT_OK`.
    candidates: list[dict[str, str]]
    #: Every stratum's actual count against this corpus, always populated
    #: once canaries have passed — reported whether or not the sample filled.
    stratum_counts: dict[str, int]
    #: `None` unless a stratum came up short. Never partially populated with a
    #: short candidate list alongside it — AC2's "never backfilled" applies to
    #: the whole run, not just to `stratified_sample`'s own return value.
    shortfall: dict[str, dict[str, int]] | None = None
    error: str | None = None


def run_sampler(
    rubric_id: str,
    *,
    status_dir: Path = STATUS_DIR,
    rubric_dir: Path = RUBRIC_DIR,
    canary_dir: Path = CANARY_DIR,
    state_dir: Path = STATE_DIR,
    scorer: Scorer = heuristic_scorer,
) -> SamplerRunResult:
    """The sampler entrypoint #1896 adds: read the committed corpus, judge it,
    emit the stratified candidate list — or an explicit, non-backfilled
    shortfall.

    Canaries run first on this path exactly as on every other invocation
    (`run_judge` owns that gate; this function does not re-implement it) —
    acceptance criterion 3. `CanaryNotFoundError` propagates uncaught, same
    contract as `run_judge`.
    """
    corpus_records = load_status_corpus(status_dir)
    result = run_judge(
        rubric_id,
        corpus_records,
        rubric_dir=rubric_dir,
        canary_dir=canary_dir,
        state_dir=state_dir,
        scorer=scorer,
    )
    if result.exit_code != EXIT_OK:
        # Canary gate failed (or, for a missing canary, `run_judge` never
        # returned at all — `CanaryNotFoundError` already propagated past
        # this function). Nothing about the corpus has been read for scoring.
        return SamplerRunResult(
            exit_code=result.exit_code,
            rubric=result.rubric,
            canary_results=result.canary_results,
            candidates=[],
            stratum_counts={},
            error=result.error,
        )

    counts = stratum_counts(result.verdicts)
    shortfall = {
        verdict: {"needed": needed, "available": counts.get(verdict, 0)}
        for verdict, needed in STRATA
        if counts.get(verdict, 0) < needed
    }
    if shortfall:
        return SamplerRunResult(
            exit_code=EXIT_SAMPLER_SHORTFALL,
            rubric=result.rubric,
            canary_results=result.canary_results,
            candidates=[],
            stratum_counts=counts,
            shortfall=shortfall,
            error=(
                f"stratified sample short against {len(corpus_records)} corpus "
                f"record(s): {shortfall} — reported, not backfilled from "
                "another stratum (#1896)"
            ),
        )

    rows = stratified_sample(result.verdicts)
    assert result.rubric is not None  # EXIT_OK implies a rubric loaded.
    candidates = [
        {
            "record_id": row["recordId"],
            "rubric_id": result.rubric.id,
            "verdict": row["verdict"],
            "note": "",
            "rubric_hash": result.rubric.rubric_hash,
        }
        for row in rows
    ]
    return SamplerRunResult(
        exit_code=EXIT_OK,
        rubric=result.rubric,
        canary_results=result.canary_results,
        candidates=candidates,
        stratum_counts=counts,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_record_arg(spec: str) -> tuple[str, dict[str, Any], str]:
    """Parse `path:artifactType[:recordId]` into `(recordId, record, artifactType)`."""
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"--record must be path:artifactType[:recordId], got {spec!r}")
    path_str, artifact_type = parts[0], parts[1]
    record_id = parts[2] if len(parts) == 3 else path_str
    record = json.loads(Path(path_str).read_text())
    return record_id, record, artifact_type


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", required=True, help="rubric id under eval/rubrics/")
    parser.add_argument(
        "--record",
        action="append",
        default=[],
        help="path:artifactType[:recordId], repeatable",
    )
    parser.add_argument(
        "--sample-corpus",
        action="store_true",
        help=(
            "read the committed agent-runtime/artifacts/status/issue-*.json corpus, "
            "judge every record under --rubric, and emit the stratified 5/3/2 "
            "candidate list for human labelling (#1461). Canaries still run first. "
            "Mutually exclusive with --record."
        ),
    )
    parser.add_argument(
        "--status-dir",
        type=Path,
        default=STATUS_DIR,
        help="override the status-record corpus directory (tests only)",
    )
    args = parser.parse_args(argv)

    if args.sample_corpus:
        if args.record:
            print("ERROR: --sample-corpus cannot be combined with --record", file=sys.stderr)
            return 1
        return _run_sampler_cli(args)

    try:
        records = [_load_record_arg(spec) for spec in args.record]
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        result = run_judge(args.rubric, records)
    except CanaryNotFoundError as exc:
        print(f"HARD ERROR (missing canary): {exc}", file=sys.stderr)
        return EXIT_CANARY_MISSING

    if result.exit_code == EXIT_CANARY_FAILED:
        print(f"CANARY FAILURE: {result.error}", file=sys.stderr)
        return EXIT_CANARY_FAILED

    print(
        json.dumps(
            {
                "rubricId": result.rubric.id if result.rubric else args.rubric,
                "rubricHash": result.rubric.rubric_hash if result.rubric else None,
                "state": "advisory",
                "canaryResults": result.canary_results,
                "verdicts": [
                    {
                        "recordId": v.record_id,
                        "verdict": v.verdict,
                        "state": v.state,
                    }
                    for v in result.verdicts
                ],
            },
            indent=2,
        )
    )
    return EXIT_OK


def _run_sampler_cli(args: argparse.Namespace) -> int:
    try:
        result = run_sampler(args.rubric, status_dir=args.status_dir)
    except CanaryNotFoundError as exc:
        print(f"HARD ERROR (missing canary): {exc}", file=sys.stderr)
        return EXIT_CANARY_MISSING

    if result.exit_code == EXIT_CANARY_FAILED:
        print(f"CANARY FAILURE: {result.error}", file=sys.stderr)
        return EXIT_CANARY_FAILED

    payload = {
        "rubricId": result.rubric.id if result.rubric else args.rubric,
        "rubricHash": result.rubric.rubric_hash if result.rubric else None,
        "state": "advisory",
        "canaryResults": result.canary_results,
        "stratumCounts": result.stratum_counts,
    }

    if result.exit_code == EXIT_SAMPLER_SHORTFALL:
        payload["shortfall"] = result.shortfall
        payload["candidates"] = []
        print(f"SAMPLER SHORTFALL: {result.error}", file=sys.stderr)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return EXIT_SAMPLER_SHORTFALL

    payload["candidates"] = result.candidates
    print(json.dumps(payload, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
