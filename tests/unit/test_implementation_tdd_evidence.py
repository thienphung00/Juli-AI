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
