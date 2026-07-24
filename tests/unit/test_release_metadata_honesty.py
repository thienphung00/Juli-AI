"""Unit tests for release_metadata_honesty (#515 / META-3)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_release_metadata_honesty import run_check  # noqa: E402
from common import write_json  # noqa: E402


def _write_release(repo: Path, *, issue_id: int, metadata: dict) -> None:
    releases_dir = repo / "agent-runtime" / "artifacts" / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        releases_dir / "release-1.0.0.json",
        {
            "version": "1.0.0",
            "featuresShipped": [{"id": issue_id, "title": "Test feature"}],
            "deploymentMetadata": metadata,
        },
    )


def test_release_metadata_honesty_skips_without_release_artifact(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "RELEASES_DIR", tmp_path / "agent-runtime" / "artifacts" / "releases")

    passed, description, details = run_check(515)

    assert passed is True
    assert details.get("skipped") is True
    assert "skipped" in description.lower()


def test_release_metadata_honesty_passes_with_step_evidence(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "RELEASES_DIR", tmp_path / "agent-runtime" / "artifacts" / "releases")
    _write_release(
        tmp_path,
        issue_id=515,
        metadata={
            "smokeTestsPassed": True,
            "healthChecksPassed": True,
            "smokeTestResults": [{"step": "home", "status": "pass"}],
            "healthCheckResults": [{"target": "api", "status": "pass"}],
        },
    )

    passed, description, _details = run_check(515)

    assert passed is True
    assert "step evidence" in description


def test_release_metadata_honesty_fails_on_hardcoded_smoke(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "RELEASES_DIR", tmp_path / "agent-runtime" / "artifacts" / "releases")
    _write_release(
        tmp_path,
        issue_id=515,
        metadata={
            "smokeTestsPassed": True,
            "healthChecksPassed": False,
        },
    )

    passed, description, details = run_check(515)

    assert passed is False
    assert "smokeTestsPassed" in description
    assert details.get("problems")


def test_release_metadata_honesty_fails_on_hardcoded_health(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "RELEASES_DIR", tmp_path / "agent-runtime" / "artifacts" / "releases")
    _write_release(
        tmp_path,
        issue_id=515,
        metadata={
            "smokeTestsPassed": False,
            "healthChecksPassed": True,
        },
    )

    passed, description, _details = run_check(515)

    assert passed is False
    assert "healthChecksPassed" in description
