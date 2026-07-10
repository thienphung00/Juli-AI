from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_config import (  # noqa: E402
    HarnessConfigError,
    allowed_auto_apply_fields,
    apply_change,
    check_path,
    list_targets,
    preview_change,
    read_field,
)
from harness_optimizer import build_optimization_artifact, collect_metrics, detect_root_cause  # noqa: E402
from build_runtime import build_runtime, load_simple_yaml  # noqa: E402


def test_list_targets_includes_agent_runtime_fields() -> None:
    targets = list_targets()
    ids = {target["id"] for target in targets}
    assert "agent_runtime_context" in ids
    assert "agent_runtime_routing" in ids
    assert "agent_runtime_benchmark_thresholds" in ids


def test_allowed_auto_apply_fields_loaded_from_schema() -> None:
    fields = allowed_auto_apply_fields()
    assert "context.budget_tokens" in fields
    assert "routing.ui_threshold" in fields
    assert "benchmark.thresholds.failure_regression_count" in fields


def test_check_path_blocks_skills() -> None:
    allowed, reason = check_path(".cursor/skills/domain/backend/SKILL.md")
    assert allowed is False
    assert "skills" in reason.lower()


def test_check_path_allows_benchmarks_doc_exception() -> None:
    allowed, _ = check_path("docs/architecture/agent-runtime-benchmarks.md")
    assert allowed is True


def test_preview_change_emits_diff_without_writing(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "agent-runtime.config.yml"
    config_path.write_text((REPO_ROOT / "agent-runtime.config.yml").read_text(encoding="utf-8"), encoding="utf-8")
    before = read_field("routing.ui_threshold", config_path=config_path)

    result = preview_change("routing.ui_threshold", 0.64, config_path=config_path)

    assert result["before"] == before
    assert result["after"] == 0.64
    assert "ui_threshold" in result["unifiedDiff"]
    assert read_field("routing.ui_threshold", config_path=config_path) == before


def test_apply_change_requires_confirm(tmp_path: Path) -> None:
    config_path = tmp_path / "agent-runtime.config.yml"
    config_path.write_text((REPO_ROOT / "agent-runtime.config.yml").read_text(encoding="utf-8"), encoding="utf-8")

    dry = apply_change("routing.ui_threshold", 0.64, config_path=config_path, confirm=False)
    assert dry["applied"] is False

    applied = apply_change("routing.ui_threshold", 0.64, config_path=config_path, confirm=True)
    assert applied["applied"] is True
    assert read_field("routing.ui_threshold", config_path=config_path) == 0.64


def test_preview_change_rejects_forbidden_field() -> None:
    try:
        preview_change("skills.backend", ["backend"])
    except HarnessConfigError as exc:
        assert "not eligible" in str(exc).lower() or "forbidden" in str(exc).lower()
    else:
        raise AssertionError("expected HarnessConfigError")


def test_build_runtime_includes_cross_layer_hints() -> None:
    runtime = build_runtime(load_simple_yaml(REPO_ROOT / "agent-runtime.config.yml"))
    ui = runtime["executorRoutingTable"]["ui-ux"]["crossLayer"]
    assert "apps/dashboard" in ui["related_paths"]
    assert runtime["context"]["retrieval_depth"] == 3


def test_optimizer_dry_run_artifact_includes_config_diff() -> None:
    config = load_simple_yaml(REPO_ROOT / "agent-runtime.config.yml")
    implementation = {
        "issueId": 123,
        "executorDomain": "backend",
        "phaseRunId": "123-test",
        "executionDurationMs": 100,
        "tokenUsage": {"input": 10, "output": 5, "total": 15},
        "toolInvocationCount": 2,
        "contextFilesLoaded": ["a.md", "b.md", "c.md", "d.md", "e.md", "f.md"],
        "skillsLoaded": ["backend"],
    }
    review = {
        "issue": 123,
        "status": "PASS",
        "criticalFindings": [],
        "modulesTouched": ["web"],
        "testCoverage": {"acceptance": {"total": 1, "mapped": 1}, "unit": {"passed": 1, "failed": 0}},
    }
    validation = {"issue": 123, "status": "PASS", "checks": [], "readyForMerge": True}
    metrics = collect_metrics(implementation, review, validation, config)
    root_cause, fix = detect_root_cause(metrics)
    diff = preview_change(fix.config_target, fix.value) if fix.value is not None else None
    artifact = build_optimization_artifact(
        metrics,
        root_cause,
        fix,
        source_paths={"implementation": Path("x"), "review": Path("y"), "validation": Path("z")},
        applied=False,
        dry_run=True,
        config_diff=diff,
    )

    assert artifact["dryRun"] is True
    assert artifact["humanApprovalRequired"] is True
    assert artifact["configDiff"] is not None
    assert artifact["predictedImpact"]["summary"]
