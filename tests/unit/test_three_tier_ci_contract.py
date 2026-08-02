"""Contract tests for the three-tier CI workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_DIR = ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from release_evidence_plan import validate_release_evidence_plan  # noqa: E402

PR_WORKFLOW = ROOT / ".github" / "workflows" / "pr.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
EVIDENCE_PLAN = ROOT / "docs" / "handoffs" / "ci-three-tier-release-evidence-plan.json"


def _workflow() -> str:
    return PR_WORKFLOW.read_text(encoding="utf-8")


def test_workflow_triggers_issue_wave_and_main_tiers() -> None:
    workflow = _workflow()

    assert 'branches: [main, staging, "feature/*-wave"]' in workflow
    assert "push:" in workflow
    assert '"feature/*-wave"' in workflow
    assert "classify-tier:" in workflow
    for tier in ("issue", "wave", "main"):
        assert f"tier={tier}" in workflow


def test_issue_tier_has_required_fast_checks() -> None:
    workflow = _workflow()

    for job in (
        "lint:",
        "typecheck:",
        "test:",
        "policy-checks:",
        "frontend:",
        "demo-frontend:",
    ):
        assert job in workflow
    assert "needs.classify-tier.outputs.tier == 'issue'" in workflow


def test_wave_tier_has_integration_and_contract_checks() -> None:
    workflow = _workflow()

    for job in (
        "integration-tests:",
        "dependency-validation:",
        "cross-module-contracts:",
        "architecture-gates:",
    ):
        assert job in workflow
    assert "needs.classify-tier.outputs.tier == 'wave'" in workflow


def test_main_tier_has_full_premerge_gates() -> None:
    workflow = _workflow()

    for job in (
        "full-regression:",
        "demo-e2e:",
        "performance-smoke:",
        "security-scan:",
        "deployment-checks:",
    ):
        assert job in workflow
    assert "needs.classify-tier.outputs.tier == 'main'" in workflow
    assert 'require "dependency-validation" "$deps" "false"' in workflow
    assert 'require "test-live-sandbox" "$live_sandbox"' in workflow


def test_issue_tier_does_not_block_on_artifact_validate_or_generate_jobs() -> None:
    """AC1: validate/generate artifact jobs are not issue-tier blockers."""
    workflow = _workflow()

    assert "validate-artifacts:" not in workflow
    assert "generate-validation-artifact:" not in workflow


def test_base_only_unchanged_head_skips_issue_tier_work() -> None:
    """AC2: base-only synchronize (before == after) skips issue-tier heavy jobs."""
    workflow = _workflow()

    assert "skip_unchanged_head" in workflow
    assert (
        'EVENT_ACTION == "synchronize"' in workflow or '$EVENT_ACTION" == "synchronize"' in workflow
    )
    assert '"$EVENT_BEFORE" == "$EVENT_AFTER"' in workflow
    assert "needs.classify-tier.outputs.skip_unchanged_head != 'true'" in workflow


def test_policy_checks_enforces_wave_manifest_membership_via_ci_wave1_validator() -> None:
    """AC3: policy-checks requires feature/issue-N* linkage and manifest membership."""
    workflow = _workflow()

    policy_job = workflow.split("policy-checks:", 1)[1].split("\n\n  ", 1)[0]
    assert "wave_manifest.py" in policy_job
    assert "--issue" in policy_job
    assert "--wave-id" in policy_job


def test_artifact_gate_renamed_from_ai_review_and_runs_on_main_tier_only() -> None:
    """AC4/AC5: ai-review is renamed to artifact-gate; deferred to wave->main."""
    workflow = _workflow()

    assert "ai-review:" not in workflow
    assert "artifact-gate:" in workflow

    gate_job = workflow.split("artifact-gate:", 1)[1].split("\n\n  ", 1)[0]
    assert "needs.classify-tier.outputs.tier == 'main'" in gate_job
    assert "wave_manifest.py" in gate_job
    assert "--check-artifacts" in gate_job


def test_status_check_requires_artifact_gate_on_main_not_ai_review() -> None:
    workflow = _workflow()

    status_job = workflow.split("status-check:", 1)[1]
    assert "ai-review" not in status_job
    assert 'require "artifact-gate"' in status_job


def test_main_tier_lint_typecheck_frontend_demo_skip_when_reached_via_wave() -> None:
    """Folded audit AC: no CI double-run of lint/typecheck/frontend/demo-frontend."""
    workflow = _workflow()

    assert "main_via_wave" in workflow

    status_job = workflow.split("status-check:", 1)[1]
    main_block = status_job.split('"$tier" == "main"', 1)[1]
    assert 'require "lint" "$lint" "true"' in main_block
    assert 'require "typecheck" "$typecheck" "true"' in main_block
    assert 'require "frontend" "$fe" "true"' in main_block
    assert 'require "demo-frontend" "$demo" "true"' in main_block


def test_gitleaks_stays_always_on_across_tiers() -> None:
    workflow = _workflow()

    gitleaks_job = workflow.split("gitleaks:", 1)[1].split("\n\n  ", 1)[0]
    assert "needs.classify-tier" not in gitleaks_job
    assert "if:" not in gitleaks_job
    status_job = workflow.split("status-check:", 1)[1]
    assert 'require "gitleaks" "$gitleaks" "false"' in status_job


def test_issue_policy_accepts_repository_feature_branch_convention() -> None:
    workflow = _workflow()

    assert '[[ "$HEAD_REF" == feature/* ]]' in workflow
    assert "Issue-tier PR branch must contain issue-N" in workflow


def test_performance_smoke_is_bounded_and_excludes_migration_heavy() -> None:
    workflow = _workflow()

    assert "timeout 5m python -m pytest" in workflow
    assert "test_material_deployed_webhook_handoff.py" in workflow
    assert '"not live and not migration_heavy"' in workflow


def test_full_regression_isolates_unit_and_integration_processes() -> None:
    workflow = _workflow()

    assert "-m pytest tests/unit -v" in workflow
    assert "-m pytest tests/integration -v" in workflow
    assert "--cov-append" in workflow


def test_pr_workflow_never_deploys() -> None:
    workflow = _workflow()
    release = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "appleboy/ssh-action" not in workflow
    assert "deploy-release.sh" not in workflow
    assert "appleboy/ssh-action" in release
    assert "deploy-release.sh" in release


def test_release_evidence_plan_is_complete() -> None:
    plan = json.loads(EVIDENCE_PLAN.read_text(encoding="utf-8"))
    result = validate_release_evidence_plan(plan)

    assert result["valid"] is True, result
