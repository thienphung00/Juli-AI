"""Unit tests for executor_domain_matches_cache (#515 / META-3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(VALIDATE_DIR))
sys.path.insert(0, str(CI_DIR))

from check_executor_domain_matches_cache import run_check  # noqa: E402
from common import build_implementation_artifact, write_json  # noqa: E402


def _write_child_cache(repo: Path, *, executor_domain: str) -> None:
    cache_dir = repo / "agent-runtime" / "artifacts" / "workflow-cache"
    cache_dir.mkdir(parents=True)
    child = {
        "schemaVersion": "1.2.0",
        "artifactType": "issue_context_cache",
        "issueId": 515,
        "parentIssueId": 500,
        "issueLoadProfile": {"executorDomain": executor_domain},
    }
    (cache_dir / "issue-context-cache-515.json").write_text(json.dumps(child), encoding="utf-8")


def _write_impl(repo: Path, *, executor_domain: str) -> None:
    impl_dir = repo / "agent-runtime" / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        impl_dir / "implementation-issue-515.json",
        build_implementation_artifact(515, executor_domain),
    )


def test_executor_domain_match_passes(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write_child_cache(tmp_path, executor_domain="backend")
    _write_impl(tmp_path, executor_domain="backend")

    passed, description, details = run_check(515, repo_root=tmp_path)

    assert passed is True
    assert details["actualExecutorDomain"] == "backend"
    assert "matches" in description


def test_executor_domain_mismatch_fails(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", tmp_path / "agent-runtime" / "artifacts" / "implementations")
    _write_child_cache(tmp_path, executor_domain="backend")
    _write_impl(tmp_path, executor_domain="ui-ux")

    passed, description, details = run_check(515, repo_root=tmp_path)

    assert passed is False
    assert "mismatch" in description
    assert details["expectedExecutorDomain"] == "backend"
    assert details["actualExecutorDomain"] == "ui-ux"


def test_executor_domain_fails_when_implementation_missing(tmp_path: Path, monkeypatch) -> None:
    import common

    monkeypatch.setattr(
        common,
        "IMPLEMENTATIONS_DIR",
        tmp_path / "agent-runtime" / "artifacts" / "implementations",
    )
    _write_child_cache(tmp_path, executor_domain="backend")

    passed, description, _details = run_check(515, repo_root=tmp_path)

    assert passed is False
    assert "missing" in description.lower()
