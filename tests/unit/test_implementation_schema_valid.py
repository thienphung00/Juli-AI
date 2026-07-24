"""Unit tests for implementation_schema_valid (#515 / META-3)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_implementation_schema_valid import run_check  # noqa: E402
from common import build_implementation_artifact, write_json  # noqa: E402


def _valid_artifact(**overrides: Any) -> dict[str, Any]:
    artifact = build_implementation_artifact(
        515,
        "backend",
        phase_run_id="515-20260724T053540",
        overrides={
            "executionDurationMs": 1200,
            "tokenUsage": {"input": 10, "output": 5, "total": 15},
            "toolInvocationCount": 1,
            "contextFilesLoaded": ["agent-runtime/docs/agent-runtime.md"],
            "skillsLoaded": [".cursor/skills/domain/backend/SKILL.md"],
            "rulesLoaded": [".cursor/rules/code-quality.mdc"],
            "mcpsUsed": [],
            "filesModified": ["agent-runtime/scripts/validate/check_implementation_schema_valid.py"],
            "testsAdded": ["tests/unit/test_implementation_schema_valid.py"],
            "testsUpdated": [],
            "redGreenRefactorEvidence": [
                {
                    "cycle": 1,
                    "commands": [{"command": "pytest -q", "exitCode": 0}],
                }
            ],
            "implementationSummary": "schema validator",
            "assumptions": [],
            "risks": [],
            **overrides,
        },
    )
    return artifact


def _write_impl(repo: Path, artifact: dict[str, Any]) -> None:
    impl_dir = repo / "agent-runtime" / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True, exist_ok=True)
    write_json(impl_dir / "implementation-issue-515.json", artifact)


def test_schema_valid_passes_for_valid_artifact(tmp_path: Path, monkeypatch) -> None:
    import common

    impl_dir = tmp_path / "agent-runtime" / "artifacts" / "implementations"
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
    _write_impl(tmp_path, _valid_artifact())

    passed, description, details = run_check(515)

    assert passed is True
    assert details.get("valid") is True
    assert "schema-valid" in description


def test_schema_valid_fails_when_artifact_missing(tmp_path: Path, monkeypatch) -> None:
    import common

    impl_dir = tmp_path / "agent-runtime" / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True)
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)

    passed, description, _details = run_check(515)

    assert passed is False
    assert "missing" in description.lower()


def test_schema_valid_fails_on_invalid_executor_domain(tmp_path: Path, monkeypatch) -> None:
    import common

    impl_dir = tmp_path / "agent-runtime" / "artifacts" / "implementations"
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
    artifact = _valid_artifact()
    artifact["executorDomain"] = "not-a-domain"
    _write_impl(tmp_path, artifact)

    passed, _description, details = run_check(515)

    assert passed is False
    assert details.get("valid") is False
    assert any("enum" in err or "executorDomain" in err for err in details.get("errors", []))


def test_schema_valid_fails_on_additional_property(tmp_path: Path, monkeypatch) -> None:
    import common

    impl_dir = tmp_path / "agent-runtime" / "artifacts" / "implementations"
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
    artifact = _valid_artifact()
    artifact["unexpectedField"] = True
    _write_impl(tmp_path, artifact)

    passed, _description, details = run_check(515)

    assert passed is False
    assert any("additional property" in err for err in details.get("errors", []))


def test_schema_valid_fails_on_missing_required_field(tmp_path: Path, monkeypatch) -> None:
    import common

    impl_dir = tmp_path / "agent-runtime" / "artifacts" / "implementations"
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)
    artifact = _valid_artifact()
    del artifact["phaseRunId"]
    _write_impl(tmp_path, artifact)

    passed, _description, details = run_check(515)

    assert passed is False
    assert any("phaseRunId" in err for err in details.get("errors", []))
