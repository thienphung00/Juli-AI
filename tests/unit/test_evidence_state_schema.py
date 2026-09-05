"""#1647: `evidenceState` is optional and backward compatible in the schema.

Split from #1603 / PR #1634. `agent-runtime/docs` is a watched `sourcePath` and
`harness_bootstrap_pinned` compares the pin against the working tree
deliberately -- an executor reads the harness from disk -- so a PR editing a
schema there fails its own drift check. The gate's own message prescribes
landing the harness change on its own first. The gate logic that *reads* this
field ships in #1634; this file asserts only the schema contract it depends on.
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


def _ci_imports():
    """Import from `agent-runtime/scripts/ci` lazily, inside a function.

    A module-level import after the `sys.path` insert needs `# noqa: E402`,
    which the suppression ratchet counts as new debt. #1540 solved this in
    `eval/gate_scoring.py::_bootstrap_anchor_sha` by moving the import into a
    function, and E402 does not apply inside a function body at all. I required
    two executors to pay this exact debt down today and then incurred it myself
    on the first draft of this file.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    from generate_implementation_artifact import build_implementation_artifact
    from json_schema_validate import validate_json_schema

    return build_implementation_artifact, validate_json_schema


def _artifact(cycles: list[dict]) -> dict:
    """A structurally complete artifact, built by the real generator.

    Hand-rolling one omits required fields, and the first draft of this test
    failed on a missing `phaseRunId` rather than on anything to do with
    `evidenceState` -- a red that looked like evidence and was not.
    """
    build, _ = _ci_imports()
    return build(
        1647,
        "backend",
        overrides={
            "executionDurationMs": 1200,
            "tokenUsage": {"input": 10, "output": 5, "total": 15},
            "filesModified": [
                "agent-runtime/docs/schemas/implementation-artifact.schema.json",
            ],
            "testsAdded": ["tests/unit/test_evidence_state_schema.py"],
            "testsUpdated": [],
            "redGreenRefactorEvidence": cycles,
        },
    )


def test_a_cycle_written_before_the_field_existed_still_validates() -> None:
    """No committed artifact may stop validating because of this addition.

    The gate's stricter pass/fail judgement is a separate, deliberate behaviour
    change shipping in #1634 -- not a schema break. Absence must stay
    structurally legal, or every artifact predating the field becomes invalid
    retroactively, which the no-backfill lock forbids.
    """
    _, validate = _ci_imports()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    legacy = _artifact([{"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 0}]}])
    assert validate(legacy, schema) == []


def test_each_declared_state_validates_and_an_unknown_one_does_not() -> None:
    """The enum is closed, so a typo fails structurally rather than reaching the
    consumer as an unrecognised value it would treat as `unavailable`."""
    _, validate = _ci_imports()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    for state in ("witnessed", "reconstructed", "unavailable"):
        assert validate(_artifact([{"cycle": 1, "evidenceState": state}]), schema) == [], state

    invalid = _artifact([{"cycle": 1, "evidenceState": "probably"}])
    assert validate(invalid, schema) != [], (
        "an unknown evidenceState must be rejected; otherwise a typo reads as a "
        "state the consumer does not recognise and treats as unavailable"
    )
