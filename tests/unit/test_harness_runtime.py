from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from build_runtime import build_runtime, load_simple_yaml
from harness_optimizer import (
    apply_fix,
    build_optimization_artifact,
    collect_metrics,
    detect_root_cause,
    evaluate_before_after,
)


def test_build_runtime_uses_declarative_config() -> None:
    config = load_simple_yaml(REPO_ROOT / "agent-runtime.config.yml")

    runtime = build_runtime(config)

    assert runtime["modelConfiguration"]["primary"] == "claude-sonnet"
    assert "Shell" in runtime["activeTools"]
    assert runtime["activeSkills"]["ui-ux"] == ["ui-ux", "ui-ux-design", "nextjs"]
    assert runtime["executorRoutingTable"]["backend"]["threshold"] == 0.7
    prompt_variant = config["prompt"]["variants"][config["prompt"]["system_prompt"]]
    assert prompt_variant in runtime["effectivePrompt"]


def test_optimizer_proposes_context_budget_change(tmp_path: Path) -> None:
    config = load_simple_yaml(REPO_ROOT / "agent-runtime.config.yml")
    config["context"]["max_files"] = 1
    implementation = {
        "issueId": 123,
        "executorDomain": "backend",
        "phaseRunId": "123-2026-06-23-test",
        "executionDurationMs": 100,
        "tokenUsage": {"input": 10, "output": 5, "total": 15},
        "toolInvocationCount": 2,
        "contextFilesLoaded": ["a.md", "b.md"],
        "skillsLoaded": ["backend"],
    }
    review = {
        "issue": 123,
        "status": "PASS",
        "criticalFindings": [],
        "modulesTouched": ["api"],
        "testCoverage": {"acceptance": {"total": 1, "mapped": 1}, "unit": {"passed": 1, "failed": 0}},
    }
    validation = {
        "issue": 123,
        "status": "PASS",
        "checks": [{"name": "unit", "status": "PASS"}],
        "readyForMerge": True,
        "testsPassed": 1,
        "testsFailed": 0,
        "retryCount": 0,
    }
    source_paths = {
        "implementation": tmp_path / "implementation.json",
        "review": tmp_path / "review.json",
        "validation": tmp_path / "validation.json",
    }
    for path in source_paths.values():
        path.write_text("{}\n", encoding="utf-8")

    metrics = collect_metrics(implementation, review, validation, config)
    root_cause, fix = detect_root_cause(metrics)
    artifact = build_optimization_artifact(metrics, root_cause, fix, source_paths=source_paths)

    assert root_cause == "context_overloaded"
    assert artifact["configTarget"] == "context.max_files"
    assert artifact["autoApplyEligible"] is True
    assert artifact["baselineMetrics"]["testPassRate"] == 1.0


def test_apply_fix_updates_only_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "agent-runtime.config.yml"
    config_path.write_text((REPO_ROOT / "agent-runtime.config.yml").read_text(encoding="utf-8"), encoding="utf-8")
    config = load_simple_yaml(config_path)
    config["context"]["max_files"] = 1

    implementation = {
        "issueId": 123,
        "executorDomain": "backend",
        "phaseRunId": "123-2026-06-23-test",
        "executionDurationMs": 100,
        "toolInvocationCount": 2,
        "contextFilesLoaded": ["a.md", "b.md"],
        "skillsLoaded": ["backend"],
    }
    metrics = collect_metrics(implementation, {"issue": 123}, {"issue": 123}, config)
    _, fix = detect_root_cause(metrics)

    assert apply_fix(config_path, fix) is True
    updated = load_simple_yaml(config_path)
    assert updated["context"]["max_files"] == 5


def test_evaluate_before_after_detects_improvement() -> None:
    before = {
        "baselineMetrics": {
            "executionTimeMs": 100,
            "tokenUsageTotal": 200,
            "reviewFailureRate": 1,
            "validationFailureRate": 0,
            "retryCount": 2,
        }
    }
    after = {
        "baselineMetrics": {
            "executionTimeMs": 80,
            "tokenUsageTotal": 150,
            "reviewFailureRate": 0,
            "validationFailureRate": 0,
            "retryCount": 1,
        }
    }

    result = evaluate_before_after(before, after)

    assert result["status"] == "improved"
    assert result["regressedMetrics"] == 0
