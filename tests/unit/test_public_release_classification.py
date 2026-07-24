"""Unit tests for public-release classification (issue #513 / META-1)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from public_release_classification import classify_public_release  # noqa: E402


@pytest.mark.parametrize(
    ("paths", "reason_prefix"),
    [
        (["apps/demo/src/app/page.tsx"], "path:apps/demo"),
        (["apps/dashboard/package.json"], "path:apps/dashboard"),
        (["apps/landing/src/app/layout.tsx"], "path:apps/landing"),
        (["infra/nginx/demo.app-juli.com.conf"], "path:infra/nginx"),
        (["infra/systemd/juli-api.service"], "path:infra/systemd"),
        (["infra/scripts/deploy-backend.sh"], "path:infra/scripts/deploy"),
        (["infra/scripts/smoke-public.sh"], "path:infra/scripts/smoke"),
        (["infra/scripts/build-demo.sh"], "path:infra/scripts/build-"),
        ([".github/workflows/release.yml"], "path:.github/workflows/release.yml"),
        ([".github/workflows/rollback.yml"], "path:.github/workflows/rollback.yml"),
        ([".github/workflows/uptime.yml"], "path:.github/workflows/uptime.yml"),
        (["infra/ecs/demo-task.json"], "path:infra/ecs"),
        (["infra/terraform/alb.tf"], "path:infra/terraform"),
        (["infra/cdk/stack.ts"], "path:infra/cdk"),
    ],
    ids=[
        "apps-demo",
        "apps-dashboard",
        "apps-landing",
        "infra-nginx",
        "infra-systemd",
        "deploy-script",
        "smoke-script",
        "build-script",
        "release-workflow",
        "rollback-workflow",
        "uptime-workflow",
        "ecs",
        "terraform",
        "cdk",
    ],
)
def test_path_trigger_marks_public(paths: list[str], reason_prefix: str) -> None:
    result = classify_public_release(paths=paths, issue_body="Harness-only notes")
    assert result["publicRelease"] is True
    assert any(r.startswith(reason_prefix) or r == reason_prefix for r in result["publicReleaseReasons"])


def test_hostname_surface_trigger_marks_public() -> None:
    result = classify_public_release(
        paths=["docs/runbooks/notes.md"],
        issue_body="Smoke demo.app-juli.com after deploy",
    )
    assert result["publicRelease"] is True
    assert any(r.startswith("surface:") for r in result["publicReleaseReasons"])


def test_label_only_public_release_marks_public() -> None:
    result = classify_public_release(
        paths=["agent-runtime/scripts/ci/ensure_workflow_cache.py"],
        issue_body="Agent-runtime Meta gate docs only; no Demo UI changes.",
        labels=["public-release"],
    )
    assert result["publicRelease"] is True
    assert "label:public-release" in result["publicReleaseReasons"]


def test_runtime_config_signal_marks_public() -> None:
    result = classify_public_release(
        paths=["infra/systemd/juli-api.service"],
        issue_body="Update systemd unit start command for public API host",
    )
    assert result["publicRelease"] is True
    assert any(
        r.startswith("path:infra/systemd") or r.startswith("runtime:")
        for r in result["publicReleaseReasons"]
    )


def test_non_public_agent_runtime_only_is_false() -> None:
    result = classify_public_release(
        paths=[
            "agent-runtime/scripts/meta_prepare_executor.py",
            "agent-runtime/docs/schemas/issue-context-cache-artifact.schema.json",
            "tests/unit/test_ensure_workflow_cache.py",
        ],
        issue_body=(
            "## What to build\n"
            "Add Meta classification modules under agent-runtime only.\n"
            "No Demo or Dashboard UI changes.\n"
        ),
        labels=["enhancement", "to-dos"],
    )
    assert result["publicRelease"] is False
    assert result["publicReleaseReasons"] == []


def test_docs_only_prose_cannot_waive_path_match() -> None:
    result = classify_public_release(
        paths=["infra/nginx/demo.app-juli.com.conf", "docs/adr/035-public-release.md"],
        issue_body="Docs only — ignore nginx path; documentation update.",
    )
    assert result["publicRelease"] is True
    assert any("path:infra/nginx" in r for r in result["publicReleaseReasons"])


def test_mixed_docs_and_infra_is_public() -> None:
    result = classify_public_release(
        paths=[
            "docs/adr/035-public-release-evidence-and-automatic-rollback.md",
            "infra/scripts/deploy-demo.sh",
        ],
        issue_body="Document and ship deploy script",
    )
    assert result["publicRelease"] is True
    assert any("path:infra/scripts/deploy" in r for r in result["publicReleaseReasons"])


def test_authority_references_adr_035_and_core_orchestration_public_release_gate() -> None:
    repo = Path(__file__).resolve().parents[2]
    adr = (repo / "docs/adr/035-public-release-evidence-and-automatic-rollback.md").read_text(
        encoding="utf-8"
    )
    runtime = (repo / "agent-runtime/docs/agent-runtime.md").read_text(encoding="utf-8")
    core = (repo / ".cursor/rules/core-orchestration.mdc").read_text(encoding="utf-8")
    assert "release-evidence plan" in adr.lower() or "release evidence" in adr.lower()
    assert "public_release_classification" in runtime
    assert "public_release_evidence_plan" in runtime
    assert "public-release" in core.lower() or "release-evidence" in core.lower()
