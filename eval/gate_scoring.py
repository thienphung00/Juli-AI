"""Score every gate in `agent-runtime/scripts/validate/` against the mutants (#1457).

The measurement is **differential**, over three kinds of arm:

``absent``
    No artifact bodies and no workflow cache for the issue at all.
``clean``
    The full unmutated fixture. This arm is the false-positive floor.
one arm per operator
    The clean fixture with exactly one planted defect swapped in.

A gate **catches** an operator iff it ``PASS``es on ``clean`` and ``FAIL``s on
that operator's arm. The clean precondition is what stops a gate that is simply
broken — one that fails on everything — from scoring a perfect seven. A gate
whose verdict never moves across all nine arms did not respond to artifact
content at all; it is a deletion candidate, not a tuning candidate.

Exit codes are read as the gates define them: 0 is PASS, 1 is FAIL. Anything
else, a crash, or a timeout is recorded as ``ERROR`` and is never silently
folded into either PASS or FAIL — a gate that cannot reach a verdict has not
passed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.artifact_mutants import (  # noqa: E402
    FAILURE_CLASSES,
    OPERATORS,
    Mutant,
    clean_records,
    generate_mutants,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
ARTIFACTS = REPO_ROOT / "agent-runtime" / "artifacts"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_JSON = RESULTS_DIR / "gate_operator_scores.json"
RESULTS_MD = RESULTS_DIR / "gate_operator_scores.md"

NO_ARTIFACT_ARM = "absent"
CLEAN_ARM = "clean"
ARMS: tuple[str, ...] = (NO_ARTIFACT_ARM, CLEAN_ARM, *OPERATORS)

GATE_TIMEOUT_SECONDS = 300

#: `check_differential_tdd` is the one gate that re-executes the change's own
#: tests. Scoring it from *inside* those tests is unbounded recursion, so the
#: live re-run in `tests/unit/test_mutants.py` skips it by name. The committed
#: table still scores it — the sweep is driven by the CLI, not by pytest.
RECURSIVE_GATES = frozenset({"check_differential_tdd"})

HONESTY_NOTE = (
    "The seven operators are derived from the nine failure classes in "
    "docs/handoffs/issue-1434.md and issue #1457. Gates written against those "
    "classes are, by construction, the gates that catch them. Every sensitivity "
    "number below is therefore sensitivity against a synthetic population that "
    "mirrors our own taxonomy — it is the best available measurement and it is "
    "NOT a claim that these gates generalise to defects we have not already "
    "named. Read a zero as informative and a non-zero as an upper bound."
)

BODY_PATHS = {
    "implementation": ("implementations", "implementation-issue-{issue}.json"),
    "review": ("reviews", "review-issue-{issue}.json"),
    "validation": ("validation", "validation-issue-{issue}.json"),
    "intent_review": ("intent-reviews", "intent-review-issue-{issue}.json"),
}


# ---------------------------------------------------------------------------
# gate discovery + execution
# ---------------------------------------------------------------------------


def discover_gates() -> list[str]:
    """Every gate module in the validate directory, sorted. Fail-closed: an
    unreadable directory raises rather than yielding an empty, flattering list."""
    if not GATE_DIR.is_dir():
        raise FileNotFoundError(f"gate directory missing: {GATE_DIR}")
    return sorted(p.stem for p in GATE_DIR.glob("*.py") if not p.stem.startswith("_"))


@dataclass(frozen=True)
class GateResult:
    gate: str
    verdict: str  # PASS | FAIL | ERROR
    exit_code: int | None
    output: str


def run_gate(gate: str, issue: int, *, timeout: int = GATE_TIMEOUT_SECONDS) -> GateResult:
    env = dict(os.environ)
    # Gates fall back to branch parsing when --issue is absent; pin it both ways
    # so the arm under test is the only thing that varies.
    env["ISSUE_NUMBER"] = str(issue)
    try:
        proc = subprocess.run(
            [sys.executable, str(GATE_DIR / f"{gate}.py"), "--issue", str(issue)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return GateResult(gate, "ERROR", None, f"timeout after {timeout}s")
    except OSError as exc:  # unreadable/unexecutable gate — never a pass
        return GateResult(gate, "ERROR", None, f"{type(exc).__name__}: {exc}")

    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0:
        verdict = "PASS"
    elif proc.returncode == 1:
        verdict = "FAIL"
    else:
        verdict = "ERROR"
    return GateResult(gate, verdict, proc.returncode, output[:600])


# ---------------------------------------------------------------------------
# fixture install / teardown
# ---------------------------------------------------------------------------


@dataclass
class Fixture:
    issue: int
    written: list[Path] = field(default_factory=list)

    def path_for(self, artifact_type: str) -> Path:
        directory, name = BODY_PATHS[artifact_type]
        return ARTIFACTS / directory / name.format(issue=self.issue)


def _render_template(name: str, issue: int) -> dict[str, Any]:
    raw = (FIXTURE_DIR / name).read_text()
    return json.loads(raw.replace("__ISSUE__", str(issue)))


def _intent_review(issue: int) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "intent_review",
        "id": f"intent-review-issue-{issue}",
        "issue": issue,
        "timestamp": "2026-09-01T09:00:00Z",
        "reviewedBy": "intent-review skill",
        "fixedPoint": "origin/main",
        "spec_fidelity": "pass",
        "specFidelityNotes": "Clean baseline record with no planted defect.",
        "smells": [],
        "convention_notes": [],
        "phaseRunId": f"{issue}-20260901T090000",
    }


def _write(path: Path, payload: dict[str, Any], fixture: Fixture) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    fixture.written.append(path)


@contextmanager
def installed_fixture(issue: int, mutant: Mutant | None = None) -> Iterator[Fixture]:
    """Install the clean fixture (optionally with one mutant swapped in), yield,
    then remove every file this call created.

    Teardown is unconditional. These paths live under gitignored artifact
    directories, so a leak would not show in `git status` and would silently
    contaminate the next arm.
    """
    fixture = Fixture(issue=issue)
    cache_dir = ARTIFACTS / "workflow-cache"
    try:
        records = clean_records(issue)
        if mutant is not None:
            records[mutant.artifact_type] = mutant.record

        _write(
            cache_dir / f"parent-cache-issue-{issue}.json",
            _render_template("parent-cache.template.json", issue),
            fixture,
        )
        _write(
            cache_dir / f"issue-context-cache-{issue}.json",
            _render_template("issue-context-cache.template.json", issue),
            fixture,
        )
        for artifact_type, record in records.items():
            _write(fixture.path_for(artifact_type), record, fixture)
        _write(fixture.path_for("intent_review"), _intent_review(issue), fixture)
        yield fixture
    finally:
        for path in fixture.written:
            path.unlink(missing_ok=True)
        # run_ensure_workflow_cache.py is a writer, not a read-only check; it can
        # recreate a cache for this issue during the sweep. Sweep those too.
        for stray in cache_dir.glob(f"*-{issue}.json"):
            stray.unlink(missing_ok=True)
        for artifact_type in BODY_PATHS:
            fixture.path_for(artifact_type).unlink(missing_ok=True)


@contextmanager
def no_artifacts(issue: int) -> Iterator[Fixture]:
    """The `absent` arm: assert nothing for this issue exists, then yield."""
    fixture = Fixture(issue=issue)
    cache_dir = ARTIFACTS / "workflow-cache"
    for path in list(cache_dir.glob(f"*-{issue}.json")):
        path.unlink(missing_ok=True)
    for artifact_type in BODY_PATHS:
        fixture.path_for(artifact_type).unlink(missing_ok=True)
    try:
        yield fixture
    finally:
        for path in list(cache_dir.glob(f"*-{issue}.json")):
            path.unlink(missing_ok=True)
        for artifact_type in BODY_PATHS:
            fixture.path_for(artifact_type).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# the sweep
# ---------------------------------------------------------------------------


def run_arms(issue: int, gates: list[str]) -> dict[str, dict[str, GateResult]]:
    arms: dict[str, dict[str, GateResult]] = {}

    with no_artifacts(issue):
        arms[NO_ARTIFACT_ARM] = {g: run_gate(g, issue) for g in gates}

    with installed_fixture(issue, mutant=None):
        arms[CLEAN_ARM] = {g: run_gate(g, issue) for g in gates}

    for mutant in generate_mutants(issue):
        with installed_fixture(issue, mutant=mutant):
            arms[mutant.operator] = {g: run_gate(g, issue) for g in gates}

    return arms


def build_table(issue: int, arms: dict[str, dict[str, GateResult]]) -> dict[str, Any]:
    gates = discover_gates()
    rows: list[dict[str, Any]] = []

    for gate in gates:
        clean = arms[CLEAN_ARM][gate]
        caught = {
            operator: (clean.verdict == "PASS" and arms[operator][gate].verdict == "FAIL")
            for operator in OPERATORS
        }
        verdicts = {arm: arms[arm][gate].verdict for arm in ARMS}
        rows.append(
            {
                "gate": gate,
                "caught": caught,
                "catchCount": sum(caught.values()),
                # "responded to artifact content at all", independent of
                # catching: either the verdict moved across the nine arms, or the
                # verdict held but the reported detail changed once the record
                # appeared. A gate constant in both did not read the record.
                "artifactSensitive": (
                    len(set(verdicts.values())) > 1 or _content_sensitive(gate, arms)
                ),
                "arms": {
                    arm: {
                        "verdict": arms[arm][gate].verdict,
                        "exitCode": arms[arm][gate].exit_code,
                        "detail": arms[arm][gate].output.splitlines()[0][:200]
                        if arms[arm][gate].output
                        else "",
                    }
                    for arm in ARMS
                },
            }
        )

    zero_catch = [row["gate"] for row in rows if row["catchCount"] == 0]

    # Three outcomes, mutually exclusive and covering all 29 gates. Keeping them
    # apart is the entire point of the table: collapsing the middle one into the
    # first inflates sensitivity, and collapsing it into the third condemns gates
    # this population never actually tested.
    #
    #   caught      — PASSed clean, FAILed at least one planted defect.
    #   silent      — PASSed clean and PASSed every planted defect. It saw a
    #                 record it was designed to judge and said nothing.
    #   fail-closed — never reached PASS on the clean arm, because a precondition
    #                 the fixture cannot synthesise is absent (a synthetic issue
    #                 number resolves to no GitHub issue; the working tree has
    #                 real stale branches). That is CORRECT behaviour and is not
    #                 evidence either way — the gate was not scored at all.
    caught_gates = [row["gate"] for row in rows if row["catchCount"] > 0]
    fail_closed = [row["gate"] for row in rows if row["arms"][CLEAN_ARM]["verdict"] != "PASS"]
    silent = [
        row["gate"]
        for row in rows
        if row["catchCount"] == 0 and row["arms"][CLEAN_ARM]["verdict"] == "PASS"
    ]
    assert len(caught_gates) + len(silent) + len(fail_closed) == len(rows), (
        "the three outcomes must partition the gate set exactly"
    )
    unscoreable = fail_closed
    deletion_candidates = silent
    errored = sorted(
        {row["gate"] for row in rows if any(row["arms"][arm]["verdict"] == "ERROR" for arm in ARMS)}
    )
    uncaught = [
        operator for operator in OPERATORS if not any(row["caught"][operator] for row in rows)
    ]

    return {
        "schemaVersion": "1.0.0",
        "artifactType": "gate_mutation_score",
        "issue": 1457,
        "syntheticIssue": issue,
        "gateCount": len(gates),
        "operators": list(OPERATORS),
        "failureClasses": FAILURE_CLASSES,
        "arms": list(ARMS),
        "rows": rows,
        "zeroCatchGates": zero_catch,
        "zeroCatchCount": len(zero_catch),
        "caughtGates": caught_gates,
        "caughtCount": len(caught_gates),
        "silentGates": silent,
        "silentCount": len(silent),
        "failClosedGates": fail_closed,
        "failClosedCount": len(fail_closed),
        "failClosedMeaning": (
            "Failed on a precondition the synthetic fixture cannot supply (no "
            "real GitHub issue behind the synthetic number; real stale branches "
            "in the working tree). Correct fail-closed behaviour. NOT scored as "
            "sensitivity and NOT a deletion candidate."
        ),
        "deletionCandidates": deletion_candidates,
        "deletionCandidateCount": len(deletion_candidates),
        "unscoreableGates": unscoreable,
        "unscoreableCount": len(unscoreable),
        "uncaughtOperators": uncaught,
        "erroredGates": errored,
        "cleanArmFailures": sorted(
            row["gate"] for row in rows if row["arms"][CLEAN_ARM]["verdict"] != "PASS"
        ),
        "falsePositivesOnClean": sorted(
            row["gate"]
            for row in rows
            if row["arms"][NO_ARTIFACT_ARM]["verdict"] == "PASS"
            and row["arms"][CLEAN_ARM]["verdict"] == "FAIL"
        ),
        "honestyNote": HONESTY_NOTE,
    }


def _content_sensitive(gate: str, arms: dict[str, dict[str, GateResult]]) -> bool:
    """True when the gate's *detail* (not just its verdict) moved between the
    absent and clean arms — it read the record even if it passed both times."""
    return arms[NO_ARTIFACT_ARM][gate].output.strip() != arms[CLEAN_ARM][gate].output.strip()


def load_results(path: Path = RESULTS_JSON) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"score table missing: {path}. Run `python -m eval.run_gate_scoring`."
        )
    return json.loads(path.read_text())


__all__ = [
    "ARMS",
    "CLEAN_ARM",
    "NO_ARTIFACT_ARM",
    "Fixture",
    "GateResult",
    "build_table",
    "discover_gates",
    "installed_fixture",
    "load_results",
    "RECURSIVE_GATES",
    "no_artifacts",
    "run_arms",
    "run_gate",
]
