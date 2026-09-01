"""Schema-driven artifact mutants, one operator per harness failure class (#1457).

Why the schemas and not the corpus
----------------------------------
The gates consume artifact *bodies*, and the five body directories are
gitignored, so only ~15 bodies survive anywhere on disk. Mutating those would
run at N is about 15 and would block on the `run{}` capture work in HE-B.
`implementation-artifact.schema.json`, `review-artifact.schema.json` and
`validation-artifact.schema.json` are all present today, so generating from the
schemas is unblocked and unbounded in N. Corpus-derived mutants are a second
population, added later.

What a mutant is
----------------
A clean, schema-valid baseline record with **exactly one** planted defect
applied to it. The defect is declared up front as a `PlantedDefect` naming the
JSON paths it touches, so a test can assert the record differs from its baseline
at those paths and nowhere else. Incidental drift would let a gate be credited
with a catch it did not earn.

Honesty note
------------
The seven operators are derived from the nine failure classes in
`docs/handoffs/issue-1434.md`. Gates designed against those classes are, by
construction, the gates that will catch them. Sensitivity measured here is
sensitivity against a synthetic population that mirrors our own taxonomy. It is
the best available measurement; it is not a generalisation claim.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "agent-runtime" / "docs" / "schemas"

#: Artifact types the three present schemas cover, plus the intent-review body
#: that several gates read alongside them. Only the first three are mutated —
#: intent-review has no schema in `agent-runtime/docs/schemas/` today, so a
#: mutant of it could not satisfy "validates against its schema".
ARTIFACT_TYPES = ("implementation", "review", "validation")

SCHEMA_FILES = {
    "implementation": "implementation-artifact.schema.json",
    "review": "review-artifact.schema.json",
    "validation": "validation-artifact.schema.json",
}

#: One operator per failure class. Order is fixed: it is the column order of the
#: committed score table.
OPERATORS = (
    "self_reported_pass",
    "vacuous_test_evidence",
    "narrowed_command_scope",
    "dangling_artifact_ref",
    "missing_artifact_as_skipped",
    "environment_mismatch",
    "unbacked_claim",
)

FAILURE_CLASSES = {
    "self_reported_pass": (
        "The agent grades itself. status=PASS is asserted while the record's own "
        "criticalFindings still carry an unresolved CRITICAL. 269 of 270 committed "
        "status records are shippable; a metric that never disagrees measures nothing."
    ),
    "vacuous_test_evidence": (
        "Red/green is narrated in prose with no command and no exit code. The "
        "canonical vacuous check: it passes because it could not determine an answer."
    ),
    "narrowed_command_scope": (
        "The recorded pytest selector is narrower than the oracle's. 487 of 541 "
        "pytest runs in the corpus are narrower than CI's."
    ),
    "dangling_artifact_ref": (
        "An artifactRef names a path present in no commit on any branch. "
        "240 of 538 artifactRef/sha256 pairs in the corpus do exactly this."
    ),
    "missing_artifact_as_skipped": (
        "A missing input is recorded as SKIP rather than FAIL, and the run still "
        "reports PASS. Violates Architect lock 2: fail-closed, always."
    ),
    "environment_mismatch": (
        "The green was obtained under an interpreter/PYTHONPATH the oracle does not "
        "use. One editable .pth decides where juli_backend resolves; a stale "
        "worktree's green is not CI's green."
    ),
    "unbacked_claim": (
        "An acceptance mapping cites a test node that exists nowhere in the tree, "
        "while reporting mapped == total. 88 of 239 gate-result claims in the "
        "corpus have no matching run."
    ),
}

#: The command CI actually runs, used as the reference for the scope and
#: environment operators.
ORACLE_PYTEST_COMMAND = "python -m pytest tests -q"


@dataclass(frozen=True)
class PlantedDefect:
    """One defect, and the exact JSON paths it is allowed to touch."""

    operator: str
    failure_class: str
    json_paths: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class Mutant:
    operator: str
    artifact_type: str
    record: dict[str, Any]
    defect: PlantedDefect


# ---------------------------------------------------------------------------
# schema access
# ---------------------------------------------------------------------------


def schema_for(artifact_type: str) -> dict[str, Any]:
    if artifact_type not in SCHEMA_FILES:
        raise KeyError(f"no schema for artifact type {artifact_type!r}")
    return json.loads((SCHEMA_DIR / SCHEMA_FILES[artifact_type]).read_text())


def validate_against_schema(record: dict[str, Any], artifact_type: str) -> None:
    """Raise ``jsonschema.ValidationError`` when the record violates its schema.

    Fail-closed: a missing or unparseable schema raises rather than passing.
    """
    Draft202012Validator(schema_for(artifact_type)).validate(record)


# ---------------------------------------------------------------------------
# path diffing — how "exactly one planted defect" is checked
# ---------------------------------------------------------------------------


def _walk(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            yield from _walk(value, path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{prefix}[{index}]")
    else:
        yield prefix, node


def changed_paths(baseline: dict[str, Any], mutated: dict[str, Any]) -> set[str]:
    """Leaf paths whose value differs, was added, or was removed."""
    left = dict(_walk(baseline))
    right = dict(_walk(mutated))
    changed = {path for path in left.keys() & right.keys() if left[path] != right[path]}
    return changed | (left.keys() ^ right.keys())


# ---------------------------------------------------------------------------
# clean baselines
# ---------------------------------------------------------------------------

_TIMESTAMP = "2026-09-01T09:00:00Z"


def _clean_implementation(issue: int) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "implementation",
        "issueId": issue,
        "executorDomain": "backend",
        "phaseRunId": f"{issue}-20260901T090000",
        "startedAt": _TIMESTAMP,
        "completedAt": "2026-09-01T09:42:00Z",
        "executionDurationMs": 2520000,
        "tokenUsage": {"input": 120000, "output": 18000, "total": 138000},
        "toolsUsed": [
            {"toolName": "Bash", "count": 31, "stage": "red"},
            {"toolName": "Bash", "count": 44, "stage": "green"},
        ],
        "toolInvocationCount": 75,
        "contextFilesLoaded": [
            "docs/handoffs/issue-1434.md",
            "agent-runtime/docs/schemas/implementation-artifact.schema.json",
        ],
        "skillsLoaded": ["backend-executor"],
        "rulesLoaded": [".cursor/rules/core-safety.mdc"],
        "mcpsUsed": [],
        "filesModified": ["eval/artifact_mutants.py", "eval/gate_scoring.py"],
        "testsAdded": ["tests/unit/test_mutants.py"],
        "testsUpdated": [],
        "redGreenRefactorEvidence": [
            {
                "cycle": 1,
                "failingTestEvidence": (
                    "ModuleNotFoundError: No module named 'eval.artifact_mutants' "
                    "— collection error, 1 error in 0.33s"
                ),
                "passingTestEvidence": "6 passed in 11.42s",
                "refactorEvidence": "Extracted the arm sweep from the CLI entrypoint.",
                "commands": [
                    {
                        "command": ORACLE_PYTEST_COMMAND,
                        "exitCode": 1,
                        "outputSummary": "1 error during collection (red)",
                    },
                    {
                        "command": ORACLE_PYTEST_COMMAND,
                        "exitCode": 0,
                        "outputSummary": "6 passed (green)",
                    },
                ],
            }
        ],
        "implementationSummary": (
            "Schema-driven mutant generator plus a differential scorer that runs "
            "every gate in agent-runtime/scripts/validate/ against the corpus."
        ),
        "assumptions": [
            "Operators mirror our own failure taxonomy; sensitivity is not a generalisation claim."
        ],
        "risks": ["Gates that never ran in CI may fail for environment reasons."],
    }


def _clean_review(issue: int) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "review",
        "id": f"review-issue-{issue}",
        "issue": issue,
        "timestamp": _TIMESTAMP,
        "reviewedBy": "review skill",
        "status": "PASS",
        "summary": "Clean baseline record with no planted defect.",
        "criticalFindings": [],
        "modulesTouched": [],
        "interfaceChanges": [],
        "moduleDrift": False,
        "driftDetails": [],
        "testCoverage": {
            "acceptance": {
                "total": 1,
                "mapped": 1,
                "unmapped": [],
                "mappings": [
                    {
                        "criterion": (
                            "GIVEN the three artifact schemas WHEN the mutator runs "
                            "THEN every mutant validates against its schema"
                        ),
                        "test": (
                            "tests/unit/test_mutants.py::"
                            "test_every_mutant_is_schema_valid_with_one_planted_defect"
                        ),
                    }
                ],
            },
            "unit": {"passed": 6, "failed": 0},
        },
        "recommendations": [],
        "approvalReady": True,
        "reviewerSignoff": None,
        "ownerSignoff": None,
        "mlGates": None,
        "priorReviewBlockers": [],
        "sourceImplementationArtifact": (
            f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json"
        ),
        "phaseRunId": f"{issue}-20260901T090000",
    }


def _clean_validation(issue: int) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "validation",
        "id": f"validation-issue-{issue}",
        "issue": issue,
        "timestamp": _TIMESTAMP,
        "validatedBy": "validate skill",
        "status": "PASS",
        "passedChecks": 2,
        "failedChecks": 0,
        "checks": [
            {
                "name": "implementation_artifact_present",
                "status": "PASS",
                "description": "Implementation artifact present; domain backend",
                "classification": "blocking",
            },
            {
                "name": "review_artifact_present",
                "status": "PASS",
                "description": "Review artifact present; status PASS",
                "classification": "blocking",
            },
        ],
        "advisoryFailures": [],
        "overallSummary": "Clean baseline record with no planted defect.",
        "readyForMerge": True,
        "reviewStatus": "PASS",
        "reviewWarningCount": 0,
        "sourceReviewArtifact": (f"agent-runtime/artifacts/reviews/review-issue-{issue}.json"),
        "phaseRunId": f"{issue}-20260901T090000",
        "testsExecuted": 6,
        "testsPassed": 6,
        "testsFailed": 0,
    }


def clean_records(issue: int) -> dict[str, dict[str, Any]]:
    """The unmutated baselines. These establish the false-positive floor."""
    return {
        "implementation": _clean_implementation(issue),
        "review": _clean_review(issue),
        "validation": _clean_validation(issue),
    }


# ---------------------------------------------------------------------------
# the seven operators
# ---------------------------------------------------------------------------


def _op_self_reported_pass(issue: int, record: dict[str, Any]) -> tuple[str, ...]:
    """status=PASS asserted over the record's own unresolved CRITICAL finding."""
    record["criticalFindings"] = [
        {
            "id": "F-1",
            "type": "test_gap",
            "module": "eval",
            "description": "Scorer credits catches to gates that FAIL on the clean arm.",
            "severity": "CRITICAL",
            "actionRequired": True,
            "suggestion": "Make the catch definition differential.",
        }
    ]
    return (
        "criticalFindings[0].id",
        "criticalFindings[0].type",
        "criticalFindings[0].module",
        "criticalFindings[0].description",
        "criticalFindings[0].severity",
        "criticalFindings[0].actionRequired",
        "criticalFindings[0].suggestion",
    )


def _op_vacuous_test_evidence(issue: int, record: dict[str, Any]) -> tuple[str, ...]:
    """Red/green narrated as prose; the commands array is dropped entirely."""
    cycle = record["redGreenRefactorEvidence"][0]
    cycle["failingTestEvidence"] = "Wrote the test first and watched it fail."
    cycle["passingTestEvidence"] = "All tests pass now."
    del cycle["commands"]
    return (
        "redGreenRefactorEvidence[0].failingTestEvidence",
        "redGreenRefactorEvidence[0].passingTestEvidence",
        "redGreenRefactorEvidence[0].commands[0].command",
        "redGreenRefactorEvidence[0].commands[0].exitCode",
        "redGreenRefactorEvidence[0].commands[0].outputSummary",
        "redGreenRefactorEvidence[0].commands[1].command",
        "redGreenRefactorEvidence[0].commands[1].exitCode",
        "redGreenRefactorEvidence[0].commands[1].outputSummary",
    )


def _op_narrowed_command_scope(issue: int, record: dict[str, Any]) -> tuple[str, ...]:
    """Real exit codes, but the selector is one node instead of CI's suite."""
    commands = record["redGreenRefactorEvidence"][0]["commands"]
    narrowed = (
        "python -m pytest tests/unit/test_mutants.py::"
        "test_every_mutant_is_schema_valid_with_one_planted_defect -q"
    )
    commands[0]["command"] = narrowed
    commands[1]["command"] = narrowed
    return (
        "redGreenRefactorEvidence[0].commands[0].command",
        "redGreenRefactorEvidence[0].commands[1].command",
    )


def _op_dangling_artifact_ref(issue: int, record: dict[str, Any]) -> tuple[str, ...]:
    """sourceImplementationArtifact names a path in no commit and on no disk."""
    record["sourceImplementationArtifact"] = (
        "agent-runtime/artifacts/implementations/"
        f"implementation-issue-{issue}-cycle-2-superseded.json"
    )
    return ("sourceImplementationArtifact",)


def _op_missing_artifact_as_skipped(issue: int, record: dict[str, Any]) -> tuple[str, ...]:
    """A missing input recorded as SKIP, and the run still reports PASS."""
    record["checks"][0]["status"] = "SKIP"
    record["checks"][0]["description"] = "Implementation artifact not found on disk; check skipped."
    return ("checks[0].status", "checks[0].description")


def _op_environment_mismatch(issue: int, record: dict[str, Any]) -> tuple[str, ...]:
    """The green was obtained under an interpreter and PYTHONPATH CI never uses."""
    commands = record["redGreenRefactorEvidence"][0]["commands"]
    foreign = (
        "PYTHONPATH=/Users/macos/Juli-AI-v2/.worktrees/stale-w6/backend/src "
        "/opt/homebrew/anaconda3/bin/python -m pytest tests -q"
    )
    commands[0]["command"] = foreign
    commands[1]["command"] = foreign
    commands[1]["outputSummary"] = (
        "6 passed (green) under .worktrees/stale-w6; CI runs .venv-ci from repo root"
    )
    return (
        "redGreenRefactorEvidence[0].commands[0].command",
        "redGreenRefactorEvidence[0].commands[1].command",
        "redGreenRefactorEvidence[0].commands[1].outputSummary",
    )


def _op_unbacked_claim(issue: int, record: dict[str, Any]) -> tuple[str, ...]:
    """mapped == total, but the cited test node exists nowhere in the tree."""
    record["testCoverage"]["acceptance"]["mappings"][0]["test"] = (
        "tests/unit/test_mutants.py::test_gate_sensitivity_is_generalisable"
    )
    return ("testCoverage.acceptance.mappings[0].test",)


_OPERATOR_IMPLS = {
    "self_reported_pass": ("review", _op_self_reported_pass),
    "vacuous_test_evidence": ("implementation", _op_vacuous_test_evidence),
    "narrowed_command_scope": ("implementation", _op_narrowed_command_scope),
    "dangling_artifact_ref": ("review", _op_dangling_artifact_ref),
    "missing_artifact_as_skipped": ("validation", _op_missing_artifact_as_skipped),
    "environment_mismatch": ("implementation", _op_environment_mismatch),
    "unbacked_claim": ("review", _op_unbacked_claim),
}


def generate_mutants(issue: int) -> list[Mutant]:
    """One mutant per operator, each schema-valid, each with one planted defect."""
    baselines = clean_records(issue)
    mutants: list[Mutant] = []
    for operator in OPERATORS:
        artifact_type, apply = _OPERATOR_IMPLS[operator]
        record = copy.deepcopy(baselines[artifact_type])
        json_paths = apply(issue, record)
        mutants.append(
            Mutant(
                operator=operator,
                artifact_type=artifact_type,
                record=record,
                defect=PlantedDefect(
                    operator=operator,
                    failure_class=FAILURE_CLASSES[operator],
                    json_paths=json_paths,
                    description=apply.__doc__ or operator,
                ),
            )
        )
    return mutants
