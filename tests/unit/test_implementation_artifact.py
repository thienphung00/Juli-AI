from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "validate"))

from common import build_implementation_artifact, write_json  # noqa: E402
from check_implementation_artifact import run_check  # noqa: E402


def test_build_implementation_artifact_includes_required_runtime_fields() -> None:
    artifact = build_implementation_artifact(247, "backend", phase_run_id="2026-06-24T1200Z")

    assert artifact["issueId"] == 247
    assert artifact["executorDomain"] == "backend"
    assert artifact["phaseRunId"] == "2026-06-24T1200Z"
    assert artifact["tokenUsage"]["total"] == 0
    assert artifact["toolInvocationCount"] == 0
    assert artifact["contextFilesLoaded"] == []
    assert artifact["skillsLoaded"] == []
    assert artifact["rulesLoaded"] == []
    assert artifact["mcpsUsed"] == []


def test_build_implementation_artifact_merges_overrides_without_clobbering_domain() -> None:
    artifact = build_implementation_artifact(
        247,
        "backend",
        overrides={
            "executionDurationMs": 1200,
            "tokenUsage": {"input": 100, "output": 50},
            "toolInvocationCount": 9,
            "contextFilesLoaded": ["scripts/ci/common.py"],
            "skillsLoaded": ["focus", "backend"],
        },
    )

    assert artifact["executionDurationMs"] == 1200
    assert artifact["tokenUsage"]["total"] == 150
    assert artifact["toolInvocationCount"] == 9
    assert artifact["executorDomain"] == "backend"


def test_implementation_artifact_gate_passes_when_present(tmp_path: Path, monkeypatch) -> None:
    impl_dir = tmp_path / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True)
    artifact_path = impl_dir / "implementation-issue-247.json"
    write_json(
        artifact_path,
        build_implementation_artifact(
            247,
            "backend",
            overrides={
                "executionDurationMs": 500,
                "tokenUsage": {"input": 10, "output": 5, "total": 15},
                "toolInvocationCount": 3,
                "contextFilesLoaded": ["agent-runtime.config.yml"],
                "skillsLoaded": ["focus"],
            },
            phase_run_id="2026-06-24T1200Z",
        ),
    )

    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)

    passed, description, _ = run_check(247)

    assert passed is True
    assert "backend" in description


def test_implementation_artifact_gate_fails_when_missing(tmp_path: Path, monkeypatch) -> None:
    impl_dir = tmp_path / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True)

    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)

    passed, description, _ = run_check(247)

    assert passed is False
    assert "missing" in description.lower()


def test_generate_implementation_artifact_cli(tmp_path: Path, monkeypatch) -> None:
    impl_dir = tmp_path / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True)

    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)

    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "executionDurationMs": 900,
                "tokenUsage": {"input": 20, "output": 10, "total": 30},
                "toolInvocationCount": 4,
                "contextFilesLoaded": ["scripts/ci/generate_implementation_artifact.py"],
                "skillsLoaded": ["focus", "backend"],
                "implementationSummary": "CLI smoke test",
            }
        ),
        encoding="utf-8",
    )

    from generate_implementation_artifact import main as generate_main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_implementation_artifact.py",
            "--issue",
            "247",
            "--executor-domain",
            "backend",
            "--input-json",
            str(overrides),
        ],
    )
    assert generate_main() == 0

    artifact = json.loads((impl_dir / "implementation-issue-247.json").read_text(encoding="utf-8"))
    assert artifact["issueId"] == 247
    assert artifact["executorDomain"] == "backend"
    assert artifact["executionDurationMs"] == 900
    assert artifact["toolInvocationCount"] == 4
