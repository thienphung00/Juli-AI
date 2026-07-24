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


def _base_artifact(**overrides: Any) -> dict[str, Any]:
    return build_implementation_artifact(
        515,
        "backend",
        overrides={
            "executionDurationMs": 1200,
            "tokenUsage": {"input": 10, "output": 5, "total": 15},
            "filesModified": ["agent-runtime/scripts/validate/check_implementation_tdd_evidence.py"],
            "testsAdded": ["tests/unit/test_implementation_tdd_evidence.py"],
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


def test_tdd_evidence_passes_for_in_scope_changes(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write(tmp_path, _base_artifact())

    passed, description, details = run_check(515)

    assert passed is True
    assert details.get("requiresTddEvidence") is True
    assert "present" in description


def test_tdd_evidence_skips_docs_only_changes(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
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
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write(tmp_path, _base_artifact(redGreenRefactorEvidence=[]))

    passed, description, _details = run_check(515)

    assert passed is False
    assert "cycle" in description.lower()


def test_tdd_evidence_fails_without_passing_command(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
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
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write(tmp_path, _base_artifact(testsAdded=[], testsUpdated=[]))

    passed, description, _details = run_check(515)

    assert passed is False
    assert "tests" in description.lower()


def test_tdd_evidence_fails_zero_tokens_long_run(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write(
        tmp_path,
        _base_artifact(
            executionDurationMs=120_000,
            tokenUsage={"input": 0, "output": 0, "total": 0},
        ),
    )

    passed, description, _details = run_check(515)

    assert passed is False
    assert "tokenUsage" in description
