"""#1457 (HE-C/P-EVAL-15) — schema-driven mutants, and all 29 gates scored on them.

Three questions, one test each:

1. Does the mutator emit *schema-valid* records that each carry *exactly one*
   planted defect?  A mutant that fails its own schema is caught by the schema,
   not by a gate, so it measures nothing.
2. Does the committed score table have a row for **every** gate, including the
   gates that caught nothing?  A table that silently drops its zeros overstates
   sensitivity.
3. Does a clean, unmutated record provoke a failure from any gate?  That is the
   false-positive floor, and it bounds what a catch is worth.

The score table itself is produced by ``eval/run_gate_scoring.py``, which really
runs the 29 gates as subprocesses.  It is far too slow for pytest's 30s budget,
so the table is committed and these tests read it — except in
``test_clean_record_produces_no_failures``, which re-runs the artifact-sensitive
subset live so the floor is observed here and not merely quoted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from eval.artifact_mutants import (  # noqa: E402
    ARTIFACT_TYPES,
    OPERATORS,
    changed_paths,
    clean_records,
    generate_mutants,
    validate_against_schema,
)
from eval.gate_scoring import (  # noqa: E402
    CLEAN_ARM,
    NO_ARTIFACT_ARM,
    RECURSIVE_GATES,
    discover_gates,
    installed_fixture,
    load_results,
    run_gate,
)

# Unique per pytest process. `check_differential_tdd` re-runs this very file as
# a probe, so a fixed number would let the nested run's fixture teardown delete
# the outer run's fixture mid-sweep — which is exactly what it did.
SYNTHETIC_ISSUE = 9_900_000 + os.getpid()


# --------------------------------------------------------------------------
# AC1 — the mutants themselves
# --------------------------------------------------------------------------


def test_every_mutant_is_schema_valid_with_one_planted_defect() -> None:
    mutants = generate_mutants(SYNTHETIC_ISSUE)
    clean = clean_records(SYNTHETIC_ISSUE)

    # Seven operators, one failure class each, no duplicates.
    assert len(OPERATORS) == 7, OPERATORS
    assert [m.operator for m in mutants] == list(OPERATORS)
    assert len({m.defect.failure_class for m in mutants}) == 7

    for mutant in mutants:
        assert mutant.artifact_type in ARTIFACT_TYPES, mutant.operator

        # It must validate against its own schema. If it does not, the schema
        # rejects it before any gate sees it and the mutant is worthless.
        validate_against_schema(mutant.record, mutant.artifact_type)

        # Exactly one planted defect, and the record differs from the clean
        # baseline *only* at that defect's declared paths — no incidental drift
        # that would let a gate "catch" something the operator did not plant.
        baseline = clean[mutant.artifact_type]
        actual = changed_paths(baseline, mutant.record)
        assert actual == set(mutant.defect.json_paths), (
            f"{mutant.operator}: declared {sorted(mutant.defect.json_paths)} "
            f"but actually changed {sorted(actual)}"
        )
        assert actual, f"{mutant.operator} planted no defect at all"

    # The clean baselines must themselves be schema-valid, or the diff above is
    # measured against an invalid record.
    for artifact_type, record in clean.items():
        validate_against_schema(record, artifact_type)


# --------------------------------------------------------------------------
# AC2 — the committed table
# --------------------------------------------------------------------------


def test_score_table_covers_all_29_gates() -> None:
    results = load_results()
    gates = discover_gates()

    assert len(gates) == 29, f"expected 29 gates, found {len(gates)}: {gates}"

    rows = results["rows"]
    assert [row["gate"] for row in rows] == gates, (
        "score table rows must cover every discovered gate, in order"
    )
    assert len(rows) == 29

    for row in rows:
        # Every operator gets an explicit verdict — a gate that caught nothing
        # still occupies a full row of falses rather than being omitted.
        assert set(row["caught"]) == set(OPERATORS), row["gate"]
        for operator in OPERATORS:
            assert isinstance(row["caught"][operator], bool), (row["gate"], operator)
        assert row["arms"][CLEAN_ARM]["verdict"] in {"PASS", "FAIL", "ERROR"}
        assert row["arms"][NO_ARTIFACT_ARM]["verdict"] in {"PASS", "FAIL", "ERROR"}

    # Zero-catch gates are named, not just counted: the issue calls them
    # deletion candidates and a bare count cannot be acted on.
    zero_catch = [row["gate"] for row in rows if not any(row["caught"].values())]
    assert results["zeroCatchGates"] == zero_catch
    assert results["zeroCatchCount"] == len(zero_catch)

    # A catch is differential by construction: a gate that already FAILs on the
    # clean record cannot be credited with catching anything, or every broken
    # gate would score a perfect seven.
    for row in rows:
        if row["arms"][CLEAN_ARM]["verdict"] != "PASS":
            assert not any(row["caught"].values()), (
                f"{row['gate']} is not PASSing on clean yet claims catches"
            )

    # The honesty note is part of the artifact, not just the PR description.
    assert "synthetic population that mirrors our own taxonomy" in results["honestyNote"]


# --------------------------------------------------------------------------
# AC4 — the false-positive floor
# --------------------------------------------------------------------------


def test_clean_record_produces_no_failures() -> None:
    results = load_results()
    rows = results["rows"]

    # (a) Recorded floor: no gate may go PASS-without-artifacts -> FAIL-on-clean.
    # That transition is the only kind of failure the clean record itself caused;
    # a gate that FAILs in both arms is blocked by its environment, not by the
    # record, and is reported separately rather than laundered into this number.
    regressions = [
        row["gate"]
        for row in rows
        if row["arms"][NO_ARTIFACT_ARM]["verdict"] == "PASS"
        and row["arms"][CLEAN_ARM]["verdict"] == "FAIL"
    ]
    assert regressions == [], f"clean record false-positives: {regressions}"

    # (b) The three outcomes must partition the gate set. If they did not, a
    # gate could be quietly dropped out of the denominator below and the floor
    # would be measured over a set chosen to make it look good.
    assert (
        set(results["caughtGates"]) | set(results["silentGates"]) | set(results["failClosedGates"])
    ) == {row["gate"] for row in rows}
    assert not (set(results["caughtGates"]) & set(results["failClosedGates"]))
    assert not (set(results["silentGates"]) & set(results["failClosedGates"]))
    assert not (set(results["caughtGates"]) & set(results["silentGates"]))

    # `fail-closed on a synthetic precondition` is a real, correct third
    # outcome — the gate refused to reach a verdict because the fixture is not a
    # real GitHub issue. It is neither sensitivity nor a false positive, so it is
    # excluded from the floor *by name*, never by silently shrinking the set.
    fail_closed = set(results["failClosedGates"])
    assert fail_closed, (
        "expected some gates to fail closed on the synthetic issue; if none do, "
        "the fixture has started satisfying preconditions it should not"
    )

    # (c) Live floor: re-run, in this checkout, the gates that the table says
    # both reached PASS on clean and actually read the record. A failure there
    # is a genuine false positive on record content. Reading (a) alone would
    # only prove the file agrees with itself.
    sensitive = [
        row["gate"]
        for row in rows
        if row["artifactSensitive"]
        and row["gate"] not in RECURSIVE_GATES
        and row["gate"] not in fail_closed
    ]
    assert sensitive, "no gate responded to artifact content at all — scorer is broken"

    with installed_fixture(SYNTHETIC_ISSUE, mutant=None) as fixture:
        observed = {gate: run_gate(gate, fixture.issue) for gate in sensitive}

    failed = {gate: result.verdict for gate, result in observed.items() if result.verdict != "PASS"}
    assert failed == {}, f"clean record failed live gates: {failed}"


# --------------------------------------------------------------------------
# Guard on the scorer itself (the epic's testing contract: plant a lie)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("operator", OPERATORS)
def test_each_operator_is_caught_by_at_least_one_gate_or_reported_uncaught(
    operator: str,
) -> None:
    """Every operator is either caught by a named gate or explicitly recorded as
    an uncaught failure class. Silence is not an acceptable third state."""
    results = load_results()
    catchers = [row["gate"] for row in results["rows"] if row["caught"][operator]]
    if catchers:
        assert operator not in results["uncaughtOperators"]
    else:
        assert operator in results["uncaughtOperators"], (
            f"{operator} was caught by no gate and is not listed as uncaught"
        )


def test_planted_defect_is_actually_detectable_in_the_written_file() -> None:
    """A mutant that never reaches disk cannot be caught by a gate that reads
    disk. Assert the planted value survives the round-trip the gates read."""
    mutants = {m.operator: m for m in generate_mutants(SYNTHETIC_ISSUE)}
    mutant = mutants["dangling_artifact_ref"]

    with installed_fixture(SYNTHETIC_ISSUE, mutant=mutant) as fixture:
        written = json.loads(fixture.path_for(mutant.artifact_type).read_text())

    assert written["sourceImplementationArtifact"] == mutant.record["sourceImplementationArtifact"]
    assert not (REPO_ROOT / written["sourceImplementationArtifact"]).exists(), (
        "the dangling ref must actually dangle, or the operator plants nothing"
    )
