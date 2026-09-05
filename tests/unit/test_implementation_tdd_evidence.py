"""Unit tests for implementation_tdd_evidence (#515 / META-3)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_implementation_tdd_evidence import run_check  # noqa: E402
from common import build_implementation_artifact, write_json  # noqa: E402

_IMPL_DIR = Path("agent-runtime") / "artifacts" / "implementations"
_TDD_SCRIPT = "agent-runtime/scripts/validate/check_implementation_tdd_evidence.py"
_TDD_TEST = "tests/unit/test_implementation_tdd_evidence.py"


def _base_artifact(**overrides: Any) -> dict[str, Any]:
    return build_implementation_artifact(
        515,
        "backend",
        overrides={
            "executionDurationMs": 1200,
            "tokenUsage": {"input": 10, "output": 5, "total": 15},
            "filesModified": [_TDD_SCRIPT],
            "testsAdded": [_TDD_TEST],
            "testsUpdated": [],
            "redGreenRefactorEvidence": [
                {
                    "cycle": 1,
                    "evidenceState": "witnessed",
                    "commands": [{"command": "pytest -q", "exitCode": 0}],
                }
            ],
            **overrides,
        },
    )


def _write(repo: Path, artifact: dict[str, Any]) -> None:
    impl_dir = repo / "agent-runtime" / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True, exist_ok=True)
    write_json(impl_dir / "implementation-issue-515.json", artifact)


def _patch_impl_dir(monkeypatch, tmp_path: Path) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / _IMPL_DIR)


def test_tdd_evidence_passes_for_in_scope_changes(tmp_path: Path, monkeypatch) -> None:
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(tmp_path, _base_artifact())

    passed, description, details = run_check(515)

    assert passed is True
    assert details.get("requiresTddEvidence") is True
    assert "present" in description


def test_tdd_evidence_skips_docs_only_changes(tmp_path: Path, monkeypatch) -> None:
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(
        tmp_path,
        _base_artifact(
            filesModified=["docs/adr/035-public-release-evidence-and-automatic-rollback.md"],
            redGreenRefactorEvidence=[],
            testsAdded=[],
        ),
    )

    passed, _description, details = run_check(515)

    assert passed is True
    assert details.get("skipped") is True


def test_tdd_evidence_fails_without_cycles(tmp_path: Path, monkeypatch) -> None:
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(tmp_path, _base_artifact(redGreenRefactorEvidence=[]))

    passed, description, _details = run_check(515)

    assert passed is False
    assert "cycle" in description.lower()


def test_tdd_evidence_fails_without_passing_command(tmp_path: Path, monkeypatch) -> None:
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(
        tmp_path,
        _base_artifact(
            redGreenRefactorEvidence=[
                {"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 1}]}
            ]
        ),
    )

    passed, description, _details = run_check(515)

    assert passed is False
    assert "exitCode" in description or "passing" in description.lower()


def test_tdd_evidence_fails_without_tests(tmp_path: Path, monkeypatch) -> None:
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(tmp_path, _base_artifact(testsAdded=[], testsUpdated=[]))

    passed, description, _details = run_check(515)

    assert passed is False
    assert "tests" in description.lower()


# --- #1603: witnessed / reconstructed / unavailable must not collapse -----
#
# The predecessor gate gave the identical verdict to a fabricated claim, an
# honestly-disclosed reconstruction, and a real witnessed observation — it had
# no field to read the difference from. These tests pin the three states apart.


def test_tdd_evidence_fails_when_every_cycle_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    """'No evidence either way' must not read as success.

    An artifact that changed code and attests an exitCode but marks its own
    cycle 'unavailable' is exactly the shape of the false negative in #1603:
    a claim with no observation behind it. It must fail, not slide through on
    the exitCode check alone.
    """
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(
        tmp_path,
        _base_artifact(
            redGreenRefactorEvidence=[
                {
                    "cycle": 1,
                    "evidenceState": "unavailable",
                    "commands": [{"command": "pytest -q", "exitCode": 0}],
                }
            ]
        ),
    )

    passed, description, details = run_check(515)

    assert passed is False
    assert "unavailable" in description.lower() or "no evidence" in description.lower()
    assert details["evidenceStateCounts"] == {
        "witnessed": 0,
        "reconstructed": 0,
        "unavailable": 1,
        "omitted": 0,
    }


def test_tdd_evidence_omitted_evidence_state_is_legacy_and_passes(
    tmp_path: Path, monkeypatch
) -> None:
    """Omission is not a declaration — a legacy artifact must not fail outright.

    An artifact written before ``evidenceState`` existed has claimed nothing;
    failing it reads absence as a claim, which is the same error class as
    treating "could not determine" as an answer. This is the regression a
    coordinator caught: the mutants clean-record fixture and the
    public-release e2e matrices are exactly this shape, and both broke when
    'omitted' first shared a bucket with the explicit 'unavailable' claim.
    """
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(
        tmp_path,
        _base_artifact(
            redGreenRefactorEvidence=[
                {"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 0}]}
            ]
        ),
    )

    passed, description, details = run_check(515)

    assert passed is True
    assert details["evidenceStateCounts"] == {
        "witnessed": 0,
        "reconstructed": 0,
        "unavailable": 0,
        "omitted": 1,
    }
    assert details["evidenceQuality"] == "legacy"
    # Legacy must never be mistaken for a real witnessed observation.
    assert "predates" in description.lower()


def test_tdd_evidence_mixed_omitted_and_explicit_unavailable_still_passes(
    tmp_path: Path, monkeypatch
) -> None:
    """A legacy cycle alongside an explicit 'unavailable' one is still tolerated.

    The bar for the hard failure is *every* cycle explicitly declaring no
    evidence — not merely the absence of a witnessed/reconstructed cycle. Any
    omitted (legacy) cycle in the mix keeps the artifact on the tolerant path,
    since at least one cycle here predates the contract and asserted nothing.
    """
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(
        tmp_path,
        _base_artifact(
            redGreenRefactorEvidence=[
                {"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 0}]},
                {
                    "cycle": 2,
                    "evidenceState": "unavailable",
                    "commands": [{"command": "pytest -q", "exitCode": 0}],
                },
            ]
        ),
    )

    passed, _description, details = run_check(515)

    assert passed is True
    assert details["evidenceStateCounts"] == {
        "witnessed": 0,
        "reconstructed": 0,
        "unavailable": 1,
        "omitted": 1,
    }
    assert details["evidenceQuality"] == "legacy"


def test_tdd_evidence_witnessed_cycle_passes_cleanly(tmp_path: Path, monkeypatch) -> None:
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(tmp_path, _base_artifact())  # default fixture cycle is evidenceState: witnessed

    passed, description, details = run_check(515)

    assert passed is True
    assert details["evidenceStateCounts"] == {
        "witnessed": 1,
        "reconstructed": 0,
        "unavailable": 0,
        "omitted": 0,
    }
    assert details["evidenceQuality"] == "witnessed"
    assert "reconstructed" not in description.lower()


def test_tdd_evidence_reconstructed_cycle_passes_but_reads_differently(
    tmp_path: Path, monkeypatch
) -> None:
    """The core of #1603's fix: reconstructed must be visibly distinct from witnessed.

    A disclosed reconstruction is not a fabrication, so it still passes — but
    it must not come out of the gate looking identical to a real observation.
    """
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(tmp_path, _base_artifact())  # default fixture cycle is evidenceState: witnessed

    witnessed_passed, witnessed_description, witnessed_details = run_check(515)
    assert witnessed_passed is True  # sanity: baseline fixture still passes

    _write(
        tmp_path,
        _base_artifact(
            redGreenRefactorEvidence=[
                {
                    "cycle": 1,
                    "evidenceState": "reconstructed",
                    "commands": [{"command": "pytest -q", "exitCode": 0}],
                }
            ]
        ),
    )
    passed, description, details = run_check(515)

    assert passed is True
    assert details["evidenceQuality"] == "reconstructed"
    assert details["evidenceStateCounts"] == {
        "witnessed": 0,
        "reconstructed": 1,
        "unavailable": 0,
        "omitted": 0,
    }
    # The two verdicts must not read the same: a reviewer scanning descriptions
    # must be able to tell a reconstructed cycle from a witnessed one.
    assert description != witnessed_description
    assert "reconstructed" in description.lower()
    assert witnessed_details["evidenceQuality"] != details["evidenceQuality"]


def test_evidence_state_is_optional_and_backward_compatible_in_the_schema() -> None:
    """#1603 changed the schema; no committed artifact may stop validating.

    ``evidenceState`` is new and optional, so a cycle written before this field
    existed (no key at all) must still validate structurally — the gate's
    stricter *pass/fail* judgement is a separate, deliberate behaviour change,
    not a schema break. An invalid enum value must still be rejected.
    """
    import json
    import sys as _sys

    schema_path = (
        REPO_ROOT / "agent-runtime" / "docs" / "schemas" / "implementation-artifact.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    ci_dir = str(CI_DIR)
    if ci_dir not in _sys.path:
        _sys.path.insert(0, ci_dir)
    from json_schema_validate import validate_json_schema

    legacy_cycle_artifact = _base_artifact(
        redGreenRefactorEvidence=[
            {"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 0}]}
        ]
    )
    assert validate_json_schema(legacy_cycle_artifact, schema) == []

    for state in ("witnessed", "reconstructed", "unavailable"):
        artifact = _base_artifact(
            redGreenRefactorEvidence=[
                {
                    "cycle": 1,
                    "evidenceState": state,
                    "commands": [{"command": "pytest -q", "exitCode": 0}],
                }
            ]
        )
        assert validate_json_schema(artifact, schema) == [], state

    invalid = _base_artifact(
        redGreenRefactorEvidence=[
            {
                "cycle": 1,
                "evidenceState": "definitely-true-i-promise",
                "commands": [{"command": "pytest -q", "exitCode": 0}],
            }
        ]
    )
    assert validate_json_schema(invalid, schema) != []


def test_tdd_evidence_ignores_zero_tokens_long_run(tmp_path: Path, monkeypatch) -> None:
    _patch_impl_dir(monkeypatch, tmp_path)
    _write(
        tmp_path,
        _base_artifact(
            executionDurationMs=120_000,
            tokenUsage={"input": 0, "output": 0, "total": 0},
        ),
    )

    passed, description, _details = run_check(515)

    assert passed is True
    assert "TDD evidence present" in description


# --- which paths require TDD evidence at all -----------------------------
#
# This was an allowlist of code prefixes, which is fail-open: a code directory
# nobody remembered to add silently skipped TDD gating entirely. That is how
# agent-runtime/scripts/ci/ — 20+ gate and CI scripts — went ungated while its
# sibling agent-runtime/scripts/validate/ was covered. Inverted to a denylist:
# everything requires evidence unless it is docs, config, artifacts, or tests.

from implementation_tdd import files_trigger_tdd_evidence  # noqa: E402


def _requires(*paths: str) -> bool:
    required, _ = files_trigger_tdd_evidence(list(paths))
    return required


def test_ci_scripts_require_evidence_like_their_validate_siblings() -> None:
    """The gap the allowlist left open: ci/ was ungated, validate/ was not."""
    assert _requires("agent-runtime/scripts/ci/implementation_tdd.py") is True
    assert _requires("agent-runtime/scripts/validate/check_adr.py") is True
    assert _requires("agent-runtime/scripts/git/worktree_gc.py") is True


def test_previously_covered_code_paths_still_require_evidence() -> None:
    for path in (
        "backend/src/juli_backend/services/scoring/signals.py",
        "apps/demo/src/components/in-progress-panel.tsx",
        "packages/theme/tokens.css",
        "infra/nginx/api.app-juli.com.conf",
    ):
        assert _requires(path) is True, path


def test_code_in_directories_nobody_allowlisted_now_requires_evidence() -> None:
    """A denylist covers new code areas by default instead of by memory."""
    assert _requires("ios/Juli/Sources/ReorderView.swift") is True


def test_docs_config_and_artifacts_do_not_require_evidence() -> None:
    for path in (
        "docs/adr/035-public-release-evidence-and-automatic-rollback.md",
        "CLAUDE.md",
        "EXECUTION.md",
        ".cursor/skills/standalone/to-issues/SKILL.md",
        ".claude/agents/meta.md",
        "agent-runtime/config/agent-runtime.config.yml",
        "agent-runtime/artifacts/status/issue-1337.json",
        ".github/workflows/pr.yml",
    ):
        assert _requires(path) is False, path


def test_a_test_only_change_does_not_require_its_own_red_green() -> None:
    """Backfilling a characterisation test is not itself a TDD cycle.

    Such a test passes against unmodified source by design, so demanding it go
    red would make adding missing coverage impossible.
    """
    assert _requires("tests/unit/test_scoring.py") is False
    assert _requires("apps/demo/src/__tests__/run-ledger.test.ts") is False
    assert _requires("backend/tests/test_thing.py") is False


def test_mixed_change_requires_evidence_and_reports_only_the_code_paths() -> None:
    required, matched = files_trigger_tdd_evidence(
        [
            "docs/adr/099-thing.md",
            "backend/src/juli_backend/api/routes/action_cards.py",
            "tests/unit/test_action_card_inputs_contract.py",
        ]
    )
    assert required is True
    assert matched == ["backend/src/juli_backend/api/routes/action_cards.py"]


def test_malformed_input_requires_nothing() -> None:
    assert files_trigger_tdd_evidence(None) == (False, [])
    assert files_trigger_tdd_evidence("backend/x.py") == (False, [])
    assert files_trigger_tdd_evidence([None, 17]) == (False, [])
