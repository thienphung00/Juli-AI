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
    JudgeVerdict,
    ensure_never_blocking,
    run_judge,
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
