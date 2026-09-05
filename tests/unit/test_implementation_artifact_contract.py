"""#1441: the implementation artifact must be able to say "unavailable".

The defect this closes is a *jointly unsatisfiable* contract. The schema makes
``tokenUsage`` optional but, when present, requires ``{input, output, total}``
integers under ``additionalProperties: false`` — there is no shape that means
"not measured". Meanwhile ``check_implementation_artifact.py`` listed
``tokenUsage`` among its required fields and hard-required ``tokenUsage.total``.
So an unmeasured run had exactly two options: omit the field and fail the gate,
or invent a number and pass it.

A reviewer took the second option and recorded an annotated ``{0, 0, 0}``
sentinel — into the very corpus this epic exists to measure. That zero is not a
harmless placeholder. It is indistinguishable from a real measurement, and a
zero is exactly as unsourceable as 1,800,000 while being far more convincing.

The fix is the ``unavailable()`` shape already used by ``assemble_evidence.py``:
``{"available": false, "reason": ...}`` with **no** ``value`` key, so a consumer
that skips the ``available`` check gets a ``KeyError`` rather than a number.

Every test here plants a lie and asserts it is caught.

Schema validation goes through the repo's own stdlib validator, never
``jsonschema``: that package is not in ``./backend[dev] -c backend/constraints.txt``
and a peer importing it once passed locally and died on CI collection.
``test_the_contract_surface_imports_nothing_outside_the_ci_dependency_set``
plants that lie so the next author cannot repeat it.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
SCHEMA_PATH = (
    REPO_ROOT / "agent-runtime" / "docs" / "schemas" / "implementation-artifact.schema.json"
)


def _load_gate():
    """Import the gate and the stdlib schema validator.

    Inside a function on purpose: hoisting the ``sys.path`` inserts above the
    module-level imports needs ``# noqa: E402`` suppressions, and the repo's
    debt ratchet counts suppression identities rather than a total.
    """
    for directory in (VALIDATE_DIR, CI_DIR):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    import check_implementation_artifact
    from json_schema_validate import validate_json_schema

    return check_implementation_artifact, validate_json_schema


check_implementation_artifact, validate_json_schema = _load_gate()

ISSUE = 1441

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

MEASURED = {"input": 180, "output": 8762, "total": 10_588_988}
UNAVAILABLE = {
    "available": False,
    "reason": "no persisted task transcript for this run; recorded unavailable rather than 0",
}


def _artifact(**overrides) -> dict:
    artifact = {
        "schemaVersion": "1.0.0",
        "artifactType": "implementation",
        "issueId": ISSUE,
        "executorDomain": "backend",
        "phaseRunId": "run-1441",
        "startedAt": "2026-09-02T01:00:00Z",
        "completedAt": "2026-09-02T02:00:00Z",
        "executionDurationMs": 3_600_000,
        "toolsUsed": [],
        "toolInvocationCount": 110,
        "contextFilesLoaded": ["agent-runtime/scripts/ci/capture_providers/__init__.py"],
        "skillsLoaded": ["backend-executor"],
        "rulesLoaded": [],
        "mcpsUsed": [],
        "filesModified": [],
        "testsAdded": [],
        "testsUpdated": [],
        "redGreenRefactorEvidence": [],
        "implementationSummary": "",
        "assumptions": [],
        "risks": [],
    }
    artifact.update(overrides)
    return artifact


def _run_gate(tmp_path: Path, artifact: dict) -> tuple[bool, str, dict]:
    path = tmp_path / f"implementation-issue-{ISSUE}.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return check_implementation_artifact.run_check(ISSUE, path=path)


def _schema_errors(artifact: dict) -> list[str]:
    """Validate through the same validator the CI gate uses, not a second one.

    Checking the published schema with a validator no gate runs would prove the
    document is well-formed and nothing about what is enforced.
    """
    return validate_json_schema(artifact, SCHEMA)


# ---------------------------------------------------------------------------


def test_unavailable_token_usage_is_expressible_and_passes(tmp_path: Path) -> None:
    """The two halves of the contract must be satisfiable at the same time."""
    artifact = _artifact(tokenUsage=UNAVAILABLE)

    assert _schema_errors(artifact) == [], "the schema must admit the unavailable shape"

    passed, description, details = _run_gate(tmp_path, artifact)
    assert passed, description
    assert details["tokenUsageAvailable"] is False
    # No number is reported for an unmeasured field, not even in the gate's own
    # details — a reported zero there is the same lie one layer down.
    assert "tokenUsageTotal" not in details

    # An artifact that legitimately carries no tokenUsage at all also passes:
    # the field is optional in the schema and must be optional in the gate.
    omitted = _artifact()
    omitted.pop("tokenUsage", None)
    assert _schema_errors(omitted) == []
    passed, description, _ = _run_gate(tmp_path, omitted)
    assert passed, description


def test_the_unavailable_shape_cannot_smuggle_a_value(tmp_path: Path) -> None:
    """The lie: ``available: false`` alongside a plausible number.

    ``unavailable()`` omits the key so a careless consumer crashes. A shape that
    allowed both would hand that consumer a zero and restore the whole defect.
    """
    smuggled = _artifact(tokenUsage={**UNAVAILABLE, "value": 0})
    assert _schema_errors(smuggled), "schema must reject a value on an unavailable reading"
    passed, description, _ = _run_gate(tmp_path, smuggled)
    assert not passed
    assert "value" in description

    no_reason = _artifact(tokenUsage={"available": False})
    assert _schema_errors(no_reason), "an unavailable reading must say why"
    passed, _, _ = _run_gate(tmp_path, no_reason)
    assert not passed


def test_the_zero_sentinel_is_rejected_now_that_unavailable_exists(tmp_path: Path) -> None:
    """The lie this slice was filed over: ``{0, 0, 0}`` as a stand-in for unknown.

    It was the only satisfiable shape before; it is a plain falsehood after, so
    the gate must name the honest alternative rather than accept it.
    """
    sentinel = _artifact(tokenUsage={"input": 0, "output": 0, "total": 0})
    passed, description, _ = _run_gate(tmp_path, sentinel)
    assert not passed
    assert "available" in description, "the failure must point at the unavailable shape"


def test_a_measured_reading_still_validates_and_passes(tmp_path: Path) -> None:
    """Regression: the fix must not cost the measured path."""
    artifact = _artifact(tokenUsage=MEASURED)
    assert _schema_errors(artifact) == []
    passed, description, details = _run_gate(tmp_path, artifact)
    assert passed, description
    assert details["tokenUsageTotal"] == 10_588_988
    assert details["tokenUsageAvailable"] is True


def test_a_malformed_token_usage_is_neither_shape_and_fails(tmp_path: Path) -> None:
    """A third shape must fail closed rather than be read on a guess."""
    for lie in ({"total": "lots"}, {"available": True}, {"input": 5}, []):
        artifact = _artifact(tokenUsage=lie)
        passed, _, _ = _run_gate(tmp_path, artifact)
        assert not passed, lie


@pytest.mark.parametrize("shape", [MEASURED, UNAVAILABLE])
def test_both_shapes_round_trip_through_the_published_schema(shape: dict) -> None:
    """The schema file on disk — not a copy in this test — admits exactly two."""
    assert _schema_errors(_artifact(tokenUsage=shape)) == []


#: Third-party names that are not in ``./backend[dev] -c backend/constraints.txt``
#: and have broken CI collection here before.
BANNED_IMPORTS = {"jsonschema", "yaml", "pydantic", "requests", "httpx", "dotenv", "fastapi"}

CONTRACT_SURFACE = (
    REPO_ROOT / "agent-runtime" / "scripts" / "ci" / "task_transcripts.py",
    REPO_ROOT / "agent-runtime" / "scripts" / "ci" / "capture_providers" / "run_metrics.py",
    REPO_ROOT / "agent-runtime" / "scripts" / "ci" / "json_schema_validate.py",
    REPO_ROOT / "agent-runtime" / "scripts" / "validate" / "check_implementation_artifact.py",
)


@pytest.mark.parametrize("module_path", CONTRACT_SURFACE, ids=lambda p: p.name)
def test_the_contract_surface_imports_nothing_outside_the_ci_dependency_set(
    module_path: Path,
) -> None:
    """These run during status-record generation in CI, where the set is thin.

    The lie this catches is the one a peer already shipped: a convenient
    ``import jsonschema`` that passes on a developer machine and fails at CI
    collection, where the package was never installed.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    offenders = sorted(imported & BANNED_IMPORTS)
    assert offenders == [], f"{module_path.name} imports {offenders}"
