"""Canary corpus for the judge (#1460, HE-D/P-EVAL-17).

A canary is a record with a **known, planted defect** — the judge's rubric must
score it `fail`. Canaries run on *every* invocation, not only at promotion: a
judge that has quietly stopped discriminating (every verdict `pass`, say,
because a prompt regression made it stop reading the record) is indistinguishable
from a clean repo. 28 of 29 gates in `agent-runtime/scripts/validate/` issued
zero `subprocess` calls and nobody noticed for months — that exact failure mode,
here, for a judge instead of a gate.

Canaries are derived from #1457's mutants where possible: each of the seven
mutation operators in `eval.artifact_mutants` plants exactly one known defect
into a schema-valid record, which is precisely what a canary needs to be. The
corpus below is generated once, deterministically, from a fixed synthetic issue
number (`CANARY_SOURCE_ISSUE`) and committed, so every process reads
byte-identical canaries.

A rubric names canary IDs it must pass through before it verdicts anything
real. A named-but-missing canary is a **hard error** (`CanaryNotFoundError`) —
never a silent skip; a skipped canary is a canary that stopped canary-ing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval.artifact_mutants import generate_mutants

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where the shipped, committed canary corpus lives. Named `canary_corpus/`,
#: not `canaries/` — a same-named sibling directory shadows this module as a
#: namespace package the moment `eval/canaries.py` is absent from `sys.path`
#: resolution order, which turns "module not found" into a silent wrong-import
#: instead of a loud one. Caught by deliberately breaking it during this
#: slice's own TDD probe.
CANARY_DIR = Path(__file__).resolve().parent / "canary_corpus"

#: Fixed, not the pid-derived number `tests/unit/test_mutants.py` uses: canaries
#: are committed artifacts, so every process must derive the byte-identical
#: records from the same seed, or two checkouts of the same commit would ship
#: different canaries.
CANARY_SOURCE_ISSUE = 1457

CANARY_PREFIX = "mutant"

#: Every canary in this corpus is a known-bad record; there is no "known-good"
#: canary today. The judge's job here is only to prove it still discriminates,
#: not to characterise its false-positive rate — that needs a labelled corpus
#: (#1461).
EXPECTED_VERDICT = "fail"


class CanaryNotFoundError(LookupError):
    """A rubric names a canary ID with no record on disk.

    Always a hard error. A rubric that silently dropped a missing canary would
    let exactly the failure this module exists to catch — a judge that stopped
    discriminating — go unnoticed, because the "discriminates" check would
    never run at all.
    """


@dataclass(frozen=True)
class Canary:
    id: str
    artifact_type: str
    operator: str
    expected_verdict: str
    record: dict[str, Any]


def canary_id_for_operator(operator: str) -> str:
    return f"{CANARY_PREFIX}-{operator}"


def generate_canary_corpus(issue: int = CANARY_SOURCE_ISSUE) -> list[Canary]:
    """One canary per #1457 mutation operator.

    Every operator today plants a defect that some rubric's scorer can name
    ("derive canaries from P-EVAL-15's mutants where possible" — issue #1460) —
    all seven are used; nothing here is corpus-derived (#1457's own honesty
    note about schema-driven mutants applies identically to reusing them as
    canaries).
    """
    return [
        Canary(
            id=canary_id_for_operator(mutant.operator),
            artifact_type=mutant.artifact_type,
            operator=mutant.operator,
            expected_verdict=EXPECTED_VERDICT,
            record=mutant.record,
        )
        for mutant in generate_mutants(issue)
    ]


def _canary_payload(canary: Canary) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "id": canary.id,
        "artifactType": canary.artifact_type,
        "sourceOperator": canary.operator,
        "expectedVerdict": canary.expected_verdict,
        "record": canary.record,
    }


def write_canary_corpus(
    canary_dir: Path = CANARY_DIR, issue: int = CANARY_SOURCE_ISSUE
) -> list[Path]:
    """(Re)generate the on-disk canary corpus. Deterministic and idempotent —
    safe to re-run after a mutant operator changes shape."""
    canary_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for canary in generate_canary_corpus(issue):
        path = canary_dir / f"{canary.id}.json"
        path.write_text(json.dumps(_canary_payload(canary), indent=2) + "\n")
        written.append(path)
    return written


def load_canary(canary_id: str, canary_dir: Path = CANARY_DIR) -> Canary:
    """Fail-closed: a missing file raises `CanaryNotFoundError` rather than
    returning `None` or an empty canary a caller might mistake for "no defect"."""
    path = canary_dir / f"{canary_id}.json"
    if not path.is_file():
        raise CanaryNotFoundError(
            f"canary {canary_id!r} is named by a rubric but has no record at "
            f"{path}; a named-but-missing canary is a hard error, not a skip (#1460)"
        )
    payload = json.loads(path.read_text())
    return Canary(
        id=payload["id"],
        artifact_type=payload["artifactType"],
        operator=payload["sourceOperator"],
        expected_verdict=payload["expectedVerdict"],
        record=payload["record"],
    )


def list_available_canary_ids(canary_dir: Path = CANARY_DIR) -> set[str]:
    if not canary_dir.is_dir():
        return set()
    return {p.stem for p in canary_dir.glob("*.json")}


def check_all_named_canaries_exist(canary_ids: Any, canary_dir: Path = CANARY_DIR) -> None:
    """Raise `CanaryNotFoundError` (fail-closed) on the first named-but-missing
    canary. Used to validate a whole rubric set up front, independent of
    actually running the judge."""
    available = list_available_canary_ids(canary_dir)
    for canary_id in canary_ids:
        if canary_id not in available:
            raise CanaryNotFoundError(
                f"canary {canary_id!r} is named by a rubric but has no record "
                f"under {canary_dir}; a named-but-missing canary is a hard "
                "error, not a skip (#1460)"
            )


__all__ = [
    "CANARY_DIR",
    "CANARY_SOURCE_ISSUE",
    "EXPECTED_VERDICT",
    "Canary",
    "CanaryNotFoundError",
    "canary_id_for_operator",
    "check_all_named_canaries_exist",
    "generate_canary_corpus",
    "list_available_canary_ids",
    "load_canary",
    "write_canary_corpus",
]
