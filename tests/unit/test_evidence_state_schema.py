"""#1603 schema half: `evidenceState` is optional and backward compatible.

Split from #1634 because `agent-runtime/docs` is a watched `sourcePath` and
`harness_bootstrap_pinned` compares the pin against the working tree — so a PR
editing a schema there fails its own drift check, and the gate's own message
prescribes landing the harness change on its own first. The gate logic that
*reads* this field ships in #1634; this file only asserts the schema contract
that logic depends on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
SCHEMA_PATH = (
    REPO_ROOT / "agent-runtime" / "docs" / "schemas" / "implementation-artifact.schema.json"
)

if str(CI_DIR) not in sys.path:
    sys.path.insert(0, str(CI_DIR))

from generate_implementation_artifact import build_implementation_artifact  # noqa: E402
from json_schema_validate import validate_json_schema  # noqa: E402


def _artifact(cycles: list[dict]) -> dict:
    """A structurally complete artifact, built by the real generator.

    Hand-rolling one omits required fields and makes the test fail for reasons
    unrelated to `evidenceState` -- which is what happened on the first attempt.
    """
    return build_implementation_artifact(
        1603,
        "backend",
        overrides={
            "executionDurationMs": 1200,
            "tokenUsage": {"input": 10, "output": 5, "total": 15},
            "filesModified": ["agent-runtime/docs/schemas/implementation-artifact.schema.json"],
            "testsAdded": [
                "tests/unit/test_evidence_state_schema.py::test_a_cycle_written_before_the_field_existed_still_validates"
            ],
            "testsUpdated": [],
            "redGreenRefactorEvidence": cycles,
        },
    )


def test_a_cycle_written_before_the_field_existed_still_validates() -> None:
    """No committed artifact may stop validating because of this addition.

    The gate's stricter pass/fail judgement is a separate, deliberate behaviour
    change shipping in #1634 — not a schema break. Absence must remain
    structurally legal here, or every artifact predating the field becomes
    invalid retroactively, which the no-backfill lock forbids.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    legacy = _artifact([{"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 0}]}])
    assert validate_json_schema(legacy, schema) == []


def test_each_declared_state_validates_and_an_unknown_one_does_not() -> None:
    """The enum is closed. A typo'd state must be rejected structurally rather
    than silently read as "not witnessed" by the consumer.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for state in ("witnessed", "reconstructed", "unavailable"):
        artifact = _artifact([{"cycle": 1, "evidenceState": state}])
        assert validate_json_schema(artifact, schema) == [], state

    invalid = _artifact([{"cycle": 1, "evidenceState": "probably"}])
    assert validate_json_schema(invalid, schema) != [], (
        "an unknown evidenceState must be rejected; otherwise a typo reads as a "
        "state the consumer does not recognise and treats as unavailable"
    )
