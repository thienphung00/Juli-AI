"""#1460 (HE-D/P-EVAL-17) — the judge runs as a sampler, advisory, canary-gated.

A judge scored by the same model class that produced the output is not an
independent reward, and k=3 self-consistency does not supply one either — it
measures variance, not bias. Until kappa clears against human labels (#1461,
not built here), the judge's job is triage, not verdict: every rubric ships
`state: advisory`, and canaries run on *every* invocation so a judge that has
quietly stopped discriminating cannot hide behind a clean-looking repo.

Five behaviours, one test each:

1. Every canary the invoked rubric names runs first; one that does not score
   `fail` aborts the run with exit code 2.
2. A named-but-missing canary is a hard error, not a skip.
3. An uncalibrated rubric's verdict is recorded advisory, and nothing this
   module produces can be consumed as blocking.
4. Sampling emits a stratified candidate list: 5 pass / 3 fail / 2
   cannot_determine.
5. Editing a rubric's prompt/anchors/model changes its `rubric_hash` and
   resets its state to advisory, even if a prior run had it calibrated.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from eval.artifact_mutants import OPERATORS, clean_records
from eval.canaries import (
    CanaryNotFoundError,
    canary_id_for_operator,
    write_canary_corpus,
)
from eval.judge import (
    EXIT_CANARY_FAILED,
    EXIT_OK,
    EXIT_SAMPLER_SHORTFALL,
    JudgeVerdict,
    ensure_never_blocking,
    heuristic_scorer,
    load_status_corpus,
    run_judge,
    run_sampler,
    stratified_sample,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_ISSUE = 9_970_001


def _write_rubric(rubric_dir: Path, rubric_id: str, *, prompt: str, canary_ids: list[str]) -> None:
    rubric_dir.mkdir(parents=True, exist_ok=True)
    (rubric_dir / f"{rubric_id}.json").write_text(
        json.dumps(
            {
                "prompt": prompt,
                "anchors": ["anchor A"],
                "model": "heuristic-v1",
                "canaryIds": canary_ids,
            }
        )
    )


def _write_canary(canary_dir: Path, canary_id: str, artifact_type: str, record: dict) -> None:
    canary_dir.mkdir(parents=True, exist_ok=True)
    (canary_dir / f"{canary_id}.json").write_text(
        json.dumps(
            {
                "id": canary_id,
                "artifactType": artifact_type,
                "sourceOperator": "test-fixture",
                "expectedVerdict": "fail",
                "record": record,
            }
        )
    )


# --------------------------------------------------------------------------
# AC1 — canaries run first; a non-fail canary aborts with exit code 2
# --------------------------------------------------------------------------


def test_canary_pass_aborts_with_exit_2(tmp_path: Path) -> None:
    rubric_dir = tmp_path / "rubrics"
    canary_dir = tmp_path / "canaries"
    state_dir = tmp_path / "state"

    clean = clean_records(SYNTHETIC_ISSUE)
    # A canary is supposed to be a KNOWN-BAD record. Installing the clean
    # (defect-free) record under a canary id simulates a judge/scorer that has
    # quietly stopped discriminating: the canary now scores "pass" instead of
    # the required "fail".
    _write_canary(canary_dir, "broken-canary", "review", clean["review"])
    _write_rubric(rubric_dir, "test-rubric", prompt="judge it", canary_ids=["broken-canary"])

    result = run_judge(
        "test-rubric",
        records=[("rec-1", clean["review"], "review")],
        rubric_dir=rubric_dir,
        canary_dir=canary_dir,
        state_dir=state_dir,
    )

    assert result.exit_code == EXIT_CANARY_FAILED
    # Aborted before any real record was scored.
    assert result.verdicts == []


# --------------------------------------------------------------------------
# AC2 — a named-but-missing canary is a hard error
# --------------------------------------------------------------------------


def test_missing_canary_is_hard_error(tmp_path: Path) -> None:
    rubric_dir = tmp_path / "rubrics"
    canary_dir = tmp_path / "canaries"
    state_dir = tmp_path / "state"
    canary_dir.mkdir(parents=True, exist_ok=True)

    _write_rubric(rubric_dir, "test-rubric", prompt="judge it", canary_ids=["does-not-exist"])

    with pytest.raises(CanaryNotFoundError) as exc_info:
        run_judge(
            "test-rubric",
            records=[],
            rubric_dir=rubric_dir,
            canary_dir=canary_dir,
            state_dir=state_dir,
        )

    # The hard error must name the missing canary, not just fail generically —
    # a human debugging a broken rubric set needs to know which id is absent.
    assert "does-not-exist" in str(exc_info.value)


# --------------------------------------------------------------------------
# AC3 — an uncalibrated rubric's verdict is advisory and never blocking
# --------------------------------------------------------------------------


def test_advisory_verdict_never_blocks(tmp_path: Path) -> None:
    rubric_dir = tmp_path / "rubrics"
    canary_dir = tmp_path / "canaries"
    state_dir = tmp_path / "state"

    write_canary_corpus(canary_dir, issue=SYNTHETIC_ISSUE)
    canary_ids = [canary_id_for_operator(op) for op in OPERATORS]
    _write_rubric(rubric_dir, "quality-rubric", prompt="judge it", canary_ids=canary_ids)

    clean = clean_records(SYNTHETIC_ISSUE)
    result = run_judge(
        "quality-rubric",
        records=[("rec-1", clean["review"], "review")],
        rubric_dir=rubric_dir,
        canary_dir=canary_dir,
        state_dir=state_dir,
    )

    assert result.exit_code == EXIT_OK
    assert len(result.verdicts) == 1
    assert result.verdicts[0].state == "advisory"
    assert result.rubric is not None and result.rubric.state == "advisory"
    # Must not raise: nothing produced here may be consumed as blocking.
    ensure_never_blocking(result.verdicts)


# --------------------------------------------------------------------------
# AC4 — sampler emits stratified candidates: 5 pass / 3 fail / 2 cannot_determine
# --------------------------------------------------------------------------


def test_sampler_emits_stratified_candidates() -> None:
    candidates = (
        [
            JudgeVerdict(record_id=f"p{i}", rubric_id="r", rubric_hash="h", verdict="pass")
            for i in range(6)
        ]
        + [
            JudgeVerdict(record_id=f"f{i}", rubric_id="r", rubric_hash="h", verdict="fail")
            for i in range(4)
        ]
        + [
            JudgeVerdict(
                record_id=f"c{i}", rubric_id="r", rubric_hash="h", verdict="cannot_determine"
            )
            for i in range(3)
        ]
    )

    sample = stratified_sample(candidates)

    assert len(sample) == 10
    assert Counter(item["verdict"] for item in sample) == {
        "pass": 5,
        "fail": 3,
        "cannot_determine": 2,
    }


# --------------------------------------------------------------------------
# #1900 — `_score_review` grades the `metrics` companion the committed corpus
# actually carries, not just the three-field `review` sub-object.
# --------------------------------------------------------------------------
#
# The committed status-record corpus's `review` sub-object is exactly
# `{artifactRef, sha256, status}` on all 385 records: none of the three
# existing quality checks (`self_reported_pass`, `dangling_artifact_ref`,
# `unbacked_claim`) have the fields they read, so all three no-op and every
# record falls through to `status in (PASS, FAIL)`. But every record also
# carries a sibling `metrics` object (`acceptanceMapped`, `acceptanceTotal`,
# `criticalFindings`, ...) that the scorer never saw. These three tests grade
# that companion directly, independent of the sampler/corpus-loader plumbing
# tested below.


def test_score_review_flags_self_reported_pass_via_metrics_critical_findings() -> None:
    # The exact shape #1900 measured 97-of-385 times: status=PASS asserted
    # while `metrics.criticalFindings` is nonzero. Not necessarily a defect
    # (the CRITICALs may have been resolved before the PASS) -- but it is the
    # judge's prediction that this record is worth a human's attention.
    record = {"status": "PASS", "metrics": {"criticalFindings": 2}}
    assert heuristic_scorer(record, "review") == "fail"


def test_score_review_still_passes_with_zero_metrics_critical_findings() -> None:
    # AC2 (revised issue #1900): the corpus must not flip to uniformly
    # negative. A PASS with zero critical findings is still `pass`.
    record = {"status": "PASS", "metrics": {"criticalFindings": 0}}
    assert heuristic_scorer(record, "review") == "pass"


def test_score_review_flags_unbacked_claim_via_metrics_acceptance_shortfall() -> None:
    # `metrics.acceptanceMapped < metrics.acceptanceTotal` is the
    # `unbacked_claim` shape restated over the thin `metrics` companion. This
    # currently matches nothing in the real corpus (0-of-385) -- correctly,
    # per the issue -- but the rule itself must fire when it is true.
    record = {
        "status": "PASS",
        "metrics": {"acceptanceMapped": 3, "acceptanceTotal": 5, "criticalFindings": 0},
    }
    assert heuristic_scorer(record, "review") == "fail"


def test_score_review_full_artifact_shape_ignores_metrics_key() -> None:
    # Requirement 4: a record carrying the FULL review-artifact shape (a real
    # `criticalFindings` list, `sourceImplementationArtifact`,
    # `testCoverage.acceptance.mappings`) must score exactly as before,
    # whether or not an unrelated thin `metrics` companion is also present.
    # `metrics.criticalFindings` (a count) must never be confused with the
    # top-level `criticalFindings` (a list of finding dicts) the full shape
    # uses for its own `self_reported_pass` check.
    record = {
        "status": "PASS",
        "criticalFindings": [],
        "metrics": {"criticalFindings": 0},
    }
    assert heuristic_scorer(record, "review") == "pass"


# --------------------------------------------------------------------------
# #1896 — the sampler CLI reads the committed status-record corpus
# --------------------------------------------------------------------------
#
# #1460 built and tested `stratified_sample` against an in-memory list. #1896
# closes the gap: there was no entrypoint that reads the committed
# `agent-runtime/artifacts/status/issue-*.json` corpus — the only artifact set
# that survives merge (ADR-003; the five body directories are gitignored) —
# judges each record, and emits the stratified candidate list #1461 needs.


def _write_status_record(
    status_dir: Path,
    issue: int,
    *,
    review_status: str | None = "PASS",
    legacy_flat: bool = False,
    metrics: dict | None = None,
) -> None:
    """Write one committed-shape status record.

    `legacy_flat=True` reproduces the one pre-#670-migration record actually
    observed on disk (`issue-1291.json`): a flat `reviewStatus` field instead
    of a nested `review.status`. The corpus loader must tolerate both shapes
    rather than silently dropping the older one.

    `metrics`, when given, reproduces the `metrics` sub-object every committed
    record actually carries (#1900) -- `acceptanceMapped`, `acceptanceTotal`,
    `criticalFindings`, ... -- which the three-field `review` sub-object alone
    does not.
    """
    status_dir.mkdir(parents=True, exist_ok=True)
    if legacy_flat:
        payload = {"issue": issue, "reviewStatus": review_status}
    else:
        payload = {
            "gateVersion": 2,
            "issue": issue,
            "review": {"status": review_status},
            "validation": {"status": "PASS"},
        }
    if metrics is not None:
        payload["metrics"] = metrics
    (status_dir / f"issue-{issue}.json").write_text(json.dumps(payload))


def _setup_sampler_rubric(tmp_path: Path) -> dict[str, Path]:
    rubric_dir = tmp_path / "rubrics"
    canary_dir = tmp_path / "canaries"
    state_dir = tmp_path / "state"
    write_canary_corpus(canary_dir, issue=SYNTHETIC_ISSUE)
    canary_ids = [canary_id_for_operator(op) for op in OPERATORS]
    _write_rubric(rubric_dir, "quality-rubric", prompt="judge it", canary_ids=canary_ids)
    return {"rubric_dir": rubric_dir, "canary_dir": canary_dir, "state_dir": state_dir}


def test_sampler_reads_real_corpus_and_emits_stratified_candidates(tmp_path: Path) -> None:
    dirs = _setup_sampler_rubric(tmp_path)
    status_dir = tmp_path / "status"
    for i in range(6):
        _write_status_record(status_dir, 20_000 + i, review_status="PASS")
    for i in range(4):
        _write_status_record(status_dir, 21_000 + i, review_status="FAIL")
    for i in range(3):
        _write_status_record(status_dir, 22_000 + i, review_status="PASS_WITH_WARNINGS")

    result = run_sampler(
        "quality-rubric",
        status_dir=status_dir,
        rubric_dir=dirs["rubric_dir"],
        canary_dir=dirs["canary_dir"],
        state_dir=dirs["state_dir"],
    )

    assert result.exit_code == EXIT_OK
    assert result.shortfall is None
    assert len(result.candidates) == 10
    assert Counter(row["verdict"] for row in result.candidates) == {
        "pass": 5,
        "fail": 3,
        "cannot_determine": 2,
    }
    # Every row carries exactly the shape #1461 will consume, plus the hash
    # labels are bound to. #1900 AC4: a human receiving a bare record_id
    # cannot adjudicate anything, so `note` now carries the issue number, the
    # record's own self-reported status, and the finding count -- not left
    # empty as it was pre-#1900.
    for row in result.candidates:
        assert set(row) == {"record_id", "rubric_id", "verdict", "note", "rubric_hash"}
        assert row["rubric_id"] == "quality-rubric"
        assert row["rubric_hash"] == result.rubric.rubric_hash
        assert row["note"] != ""
        assert "issue" in row["note"]


def test_sampler_shortfall_is_reported_never_backfilled(tmp_path: Path) -> None:
    dirs = _setup_sampler_rubric(tmp_path)
    status_dir = tmp_path / "status"
    # Plenty of pass and cannot_determine candidates, but zero fail — the real
    # corpus's actual shape (#1896): 98% passes, zero review FAIL.
    for i in range(20):
        _write_status_record(status_dir, 30_000 + i, review_status="PASS")
    for i in range(5):
        _write_status_record(status_dir, 31_000 + i, review_status="PASS_WITH_WARNINGS")

    result = run_sampler(
        "quality-rubric",
        status_dir=status_dir,
        rubric_dir=dirs["rubric_dir"],
        canary_dir=dirs["canary_dir"],
        state_dir=dirs["state_dir"],
    )

    assert result.exit_code == EXIT_SAMPLER_SHORTFALL
    # No short list that reads as a full one: the shortfall path emits no
    # candidates at all, never a partial 7-of-10.
    assert result.candidates == []
    assert result.shortfall is not None
    assert result.shortfall["fail"] == {"needed": 3, "available": 0}
    # The strata that WERE fillable are not reported as short.
    assert "pass" not in result.shortfall
    assert "cannot_determine" not in result.shortfall


def test_sampler_runs_canaries_first_and_aborts_before_reading_corpus(tmp_path: Path) -> None:
    rubric_dir = tmp_path / "rubrics"
    canary_dir = tmp_path / "canaries"
    state_dir = tmp_path / "state"
    status_dir = tmp_path / "status"

    clean = clean_records(SYNTHETIC_ISSUE)
    _write_canary(canary_dir, "broken-canary", "review", clean["review"])
    _write_rubric(rubric_dir, "test-rubric", prompt="judge it", canary_ids=["broken-canary"])

    # A corpus that would trivially fill every stratum — if the sampler ever
    # read it. It must not: the canary gate runs first, on this path exactly
    # as on every other invocation (#1460's whole point).
    for i in range(6):
        _write_status_record(status_dir, 40_000 + i, review_status="PASS")
    for i in range(4):
        _write_status_record(status_dir, 41_000 + i, review_status="FAIL")
    for i in range(3):
        _write_status_record(status_dir, 42_000 + i, review_status="PASS_WITH_WARNINGS")

    result = run_sampler(
        "test-rubric",
        status_dir=status_dir,
        rubric_dir=rubric_dir,
        canary_dir=canary_dir,
        state_dir=state_dir,
    )

    assert result.exit_code == EXIT_CANARY_FAILED
    assert result.candidates == []
    assert result.shortfall is None


def test_sampler_corpus_loader_tolerates_the_legacy_flat_schema(tmp_path: Path) -> None:
    status_dir = tmp_path / "status"
    _write_status_record(status_dir, 1291, review_status="PASS", legacy_flat=True)
    _write_status_record(status_dir, 1002, review_status="FAIL")

    records = load_status_corpus(status_dir)

    by_id = {record_id: (record, artifact_type) for record_id, record, artifact_type in records}
    # #1900: the view now also carries the record's own `issue` number (used
    # for `dangling_artifact_ref` on full-shape records, and for the
    # sampler's candidate adjudication context here) -- still no `metrics`
    # key when the payload does not carry one.
    assert by_id["issue-1291"] == ({"status": "PASS", "issue": 1291}, "review")
    assert by_id["issue-1002"] == ({"status": "FAIL", "issue": 1002}, "review")


def test_sampler_fills_fail_stratum_from_metrics_self_reported_pass_shape(tmp_path: Path) -> None:
    # Mirrors the real corpus's actual shape at small scale (#1900): every
    # record's `review.status` is PASS (no review ever recorded FAIL), and
    # the only gradeable negative signal is `metrics.criticalFindings > 0` on
    # some of them. Before #1900 this stratum could never fill; the fix reads
    # `metrics`, not a schema change or a backfill.
    dirs = _setup_sampler_rubric(tmp_path)
    status_dir = tmp_path / "status"
    for i in range(6):
        _write_status_record(
            status_dir, 50_000 + i, review_status="PASS", metrics={"criticalFindings": 0}
        )
    for i in range(3):
        _write_status_record(
            status_dir, 51_000 + i, review_status="PASS", metrics={"criticalFindings": 2}
        )
    for i in range(2):
        _write_status_record(status_dir, 52_000 + i, review_status="PASS_WITH_WARNINGS")

    result = run_sampler(
        "quality-rubric",
        status_dir=status_dir,
        rubric_dir=dirs["rubric_dir"],
        canary_dir=dirs["canary_dir"],
        state_dir=dirs["state_dir"],
    )

    assert result.exit_code == EXIT_OK
    assert result.shortfall is None
    assert result.stratum_counts["fail"] == 3
    assert Counter(row["verdict"] for row in result.candidates) == {
        "pass": 5,
        "fail": 3,
        "cannot_determine": 2,
    }


def test_sampler_candidate_rows_carry_adjudication_context(tmp_path: Path) -> None:
    # #1900 AC4: a candidate row must carry enough for a human to adjudicate
    # without opening the corpus file themselves -- at minimum the issue
    # number, the record's own recorded status, and the finding count that
    # triggered the `fail` prediction (which is NOT necessarily a defect --
    # the CRITICALs may already be resolved).
    dirs = _setup_sampler_rubric(tmp_path)
    status_dir = tmp_path / "status"
    for i in range(6):
        _write_status_record(
            status_dir, 60_000 + i, review_status="PASS", metrics={"criticalFindings": 0}
        )
    for i in range(3):
        _write_status_record(
            status_dir, 61_000 + i, review_status="PASS", metrics={"criticalFindings": 2}
        )
    for i in range(2):
        _write_status_record(status_dir, 62_000 + i, review_status="PASS_WITH_WARNINGS")

    result = run_sampler(
        "quality-rubric",
        status_dir=status_dir,
        rubric_dir=dirs["rubric_dir"],
        canary_dir=dirs["canary_dir"],
        state_dir=dirs["state_dir"],
    )

    assert result.exit_code == EXIT_OK
    fail_rows = [row for row in result.candidates if row["verdict"] == "fail"]
    assert len(fail_rows) == 3
    for row in fail_rows:
        issue_number = row["record_id"].removeprefix("issue-")
        assert issue_number in row["note"]
        assert "PASS" in row["note"]
        assert "2" in row["note"]


# --------------------------------------------------------------------------
# AC5 — editing a rubric changes rubric_hash and resets state to advisory
# --------------------------------------------------------------------------


def test_rubric_edit_resets_to_advisory(tmp_path: Path) -> None:
    from eval.rubrics import load_rubric

    rubric_dir = tmp_path / "rubrics"
    state_dir = tmp_path / "state"

    _write_rubric(rubric_dir, "r1", prompt="Judge whether X.", canary_ids=[])
    rubric_v1 = load_rubric("r1", rubric_dir=rubric_dir, state_dir=state_dir)
    assert rubric_v1.state == "advisory"

    # Simulate a rubric #1461's (not-built-here) promotion path had earlier
    # marked calibrated. This module never writes "calibrated" itself, so the
    # only way to exercise the reset is to seed it directly.
    state_path = state_dir / "r1.json"
    payload = json.loads(state_path.read_text())
    payload["state"] = "calibrated"
    state_path.write_text(json.dumps(payload))

    rubric_same_hash = load_rubric("r1", rubric_dir=rubric_dir, state_dir=state_dir)
    assert rubric_same_hash.rubric_hash == rubric_v1.rubric_hash
    assert rubric_same_hash.state == "calibrated"  # unchanged: hash did not move

    _write_rubric(rubric_dir, "r1", prompt="Judge whether X, revised.", canary_ids=[])
    rubric_v2 = load_rubric("r1", rubric_dir=rubric_dir, state_dir=state_dir)

    assert rubric_v2.rubric_hash != rubric_v1.rubric_hash
    assert rubric_v2.state == "advisory"
