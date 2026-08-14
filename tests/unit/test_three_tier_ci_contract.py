"""Contract tests for the three-tier CI workflow."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_DIR = ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from release_evidence_plan import validate_release_evidence_plan  # noqa: E402

PR_WORKFLOW = ROOT / ".github" / "workflows" / "pr.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
EVIDENCE_PLAN = ROOT / "docs" / "handoffs" / "ci-three-tier-release-evidence-plan.json"

ZERO_SHA = "0" * 40


def _workflow() -> str:
    return PR_WORKFLOW.read_text(encoding="utf-8")


def _job_block(workflow: str, job_header: str) -> str:
    """Return the body of a top-level job, from its header to the next
    top-level (2-space indented) key."""
    return workflow.split(f"\n  {job_header}", 1)[1].split("\n\n  ", 1)[0]


def _changes_step_run(step_name: str) -> str:
    """Extract the `run:` script of a named step inside the `changes` job,
    by parsing pr.yml as YAML (not text-splitting), so the extracted bash
    can actually be executed to verify behavior."""
    workflow = yaml.safe_load(_workflow())
    changes_job = workflow["jobs"]["changes"]
    for step in changes_job["steps"]:
        if step.get("name") == step_name:
            return step["run"]
    raise AssertionError(f"step {step_name!r} not found in changes job")


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


def test_base_only_skip_is_retired_as_unreachable() -> None:
    """AC2 (narrowed): base-only-skip is retired — GitHub only fires
    `synchronize` when the head SHA moves, so before == after never occurs
    and a base-only advance fires no PR event at all. Issue-tier heavy jobs
    (lint/typecheck/test/policy-checks) are no longer gated on a
    head-unchanged signal; sibling base-reruns are instead prevented by
    ADR-052's removal of "up-to-date-with-base" on feature/*-wave.
    """
    workflow = _workflow()

    assert "skip_unchanged_head" not in workflow
    assert "needs.classify-tier.outputs.skip_unchanged_head" not in workflow
    for job in ("lint", "typecheck", "test", "policy-checks"):
        job_block = workflow.split(f"\n  {job}:", 1)[1].split("\n\n  ", 1)[0]
        assert "skip_unchanged_head" not in job_block


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
    """AC6 (narrowed to pull_request): no CI double-run of
    lint/typecheck/frontend/demo-frontend when main tier is reached via a
    wave->main pull_request (head_ref matches feature/*-wave). The
    merge_group branch of this dedup is out of #658 scope — merge_group's
    head_ref is a synthetic `gh-readonly-queue/...` ref that never matches
    feature/*-wave, so those four jobs may safely re-run on merge_group
    (acceptable over-run, tracked in #671)."""
    workflow = _workflow()

    assert "main_via_wave" in workflow
    classify_job = workflow.split("classify-tier:", 1)[1].split("\n\n  ", 1)[0]
    assert "MERGE_GROUP_HEAD_REF" not in classify_job
    wave_head_block = classify_job.split("wave_head=", 1)[1]
    assert "merge_group" not in wave_head_block

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
    assert "deploy-release.sh" not in workflow  # retired (#844)
    assert "appleboy/ssh-action" in release
    assert "deploy.sh" in release


def test_release_evidence_plan_is_complete() -> None:
    plan = json.loads(EVIDENCE_PLAN.read_text(encoding="utf-8"))
    result = validate_release_evidence_plan(plan)

    assert result["valid"] is True, result


# --- CI-WAVE-3 (#661): domain-matched wave-push checks -------------------
#
# Wave-tier pushes must diff github.event.before -> github.event.after
# instead of forcing every `changes` job domain output true, while
# main-tier (wave->main, merge_group) stays the full, path-aware checkpoint.


def test_changes_job_no_longer_force_true_for_every_non_issue_tier() -> None:
    """The old #660 branch ('anything but issue tier' -> force every domain
    true) must be narrowed: only main tier (and the documented wave-push
    before-SHA fallback) may force every domain true. Wave tier gets its own
    real path-filter run."""
    workflow = _workflow()
    changes_job = _job_block(workflow, "changes:")

    set_outputs_block = changes_job.split("Set path-filter outputs", 1)[1]
    assert '!= "issue"' not in set_outputs_block
    assert '== "main"' in set_outputs_block or "== 'main'" in set_outputs_block


def test_wave_push_backend_domain_diffs_before_after_sha() -> None:
    """AC: on push to feature/*-wave, path filtering uses github.event.before
    and github.event.after — a backend-only push must resolve backend
    domain-gated jobs from a real diff, not a forced true."""
    workflow = _workflow()
    changes_job = _job_block(workflow, "changes:")

    assert "github.event.before" in changes_job
    assert "github.event.after" in changes_job
    # A dedicated wave-tier paths-filter run must exist, gated on tier ==
    # 'wave', and reuse the same domain filter definitions as issue tier
    # (backend/** etc.) so backend-only wave pushes match backend=true.
    assert "id: filter-wave" in changes_job
    filter_wave_block = changes_job.split("id: filter-wave", 1)[1]
    assert "backend" in filter_wave_block
    assert "'backend/**'" in changes_job  # shared filters definition

    integration_block = _job_block(workflow, "integration-tests:")
    assert "needs.changes.outputs.backend == 'true'" in integration_block
    architecture_block = _job_block(workflow, "architecture-gates:")
    assert "needs.changes.outputs.backend == 'true'" in architecture_block
    cross_module_block = _job_block(workflow, "cross-module-contracts:")
    assert "needs.changes.outputs.backend == 'true'" in cross_module_block


def test_wave_push_frontend_demo_domain_uses_real_filter_not_forced_true() -> None:
    """AC: a frontend/demo-only wave push must not force backend integration/
    architecture jobs to run — the dashboard/demo filter categories must be
    reachable from the wave-tier filter run."""
    workflow = _workflow()
    changes_job = _job_block(workflow, "changes:")

    assert "'apps/dashboard/**'" in changes_job
    assert "'apps/demo/**'" in changes_job

    frontend_block = _job_block(workflow, "frontend:")
    assert "needs.changes.outputs.dashboard == 'true'" in frontend_block
    demo_block = _job_block(workflow, "demo-frontend:")
    assert "needs.changes.outputs.demo == 'true'" in demo_block


def test_wave_push_agent_docs_only_stays_cheap_without_bypassing_gitleaks() -> None:
    """AC: agent/docs-only wave pushes stay cheap (agent domain only, no
    backend/dashboard/demo jobs) without bypassing gitleaks or tier-aware
    status classification, which both stay unconditional."""
    workflow = _workflow()
    changes_job = _job_block(workflow, "changes:")

    assert "'agent-runtime/**'" in changes_job
    assert "'.cursor/**'" in changes_job

    gitleaks_job = _job_block(workflow, "gitleaks:")
    assert "needs.classify-tier" not in gitleaks_job
    assert "if:" not in gitleaks_job

    status_job = workflow.split("status-check:", 1)[1]
    assert 'require "gitleaks" "$gitleaks" "false"' in status_job
    wave_block = status_job.split('"$tier" == "wave"', 1)[1]
    assert 'require "integration-tests"' in wave_block


def test_wave_push_before_sha_edge_fails_safe_with_documented_fallback() -> None:
    """AC: a zero/missing/unresolvable before SHA (new or force-pushed wave
    branch) must not silently skip everything — it must take a documented
    bounded fallback (running every domain) rather than emit all-false."""
    workflow = _workflow()
    changes_job = _job_block(workflow, "changes:")

    assert ZERO_SHA in changes_job
    assert "fallback" in changes_job.lower()
    # The fallback direction must be to run everything, not skip everything.
    fallback_context = changes_job.lower()
    assert "all-domain fallback" in fallback_context or "run every domain" in fallback_context


def test_wave_push_before_sha_resolution_script_behaves_correctly() -> None:
    """Execute the actual 'Resolve wave-push diff range' bash step extracted
    from pr.yml (not a re-implementation) against real git repos to verify
    the fallback=true/false decision for each before-SHA edge case."""
    script = _changes_step_run("Resolve wave-push diff range")

    def run_with_before_sha(repo: Path, before_sha: str) -> str:
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=repo,
            env={
                "BEFORE_SHA": before_sha,
                "GITHUB_OUTPUT": str(repo / "github_output.txt"),
                "PATH": "/usr/bin:/bin:/usr/local/bin",
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return (repo / "github_output.txt").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "ci"], cwd=repo, check=True)
        (repo / "f.txt").write_text("1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
        good_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

        assert "fallback=true" in run_with_before_sha(repo, ZERO_SHA)
        assert "fallback=true" in run_with_before_sha(repo, "")
        assert "fallback=true" in run_with_before_sha(repo, "f" * 40)
        assert "fallback=false" in run_with_before_sha(repo, good_sha)


def test_dependency_validation_is_domain_matched_on_wave_tier_not_main() -> None:
    """AC2 names dependency-validation among the jobs that must run only for
    affected domains on wave-tier pushes (docs/agent-only pushes stay
    cheap), while main tier stays the full, unconditional checkpoint (#658).
    status-check must allow "skipped" for dependency-validation at wave
    tier (it is domain-gated there) but still require "success" at main
    tier (never skippable)."""
    workflow = _workflow()
    dep_block = _job_block(workflow, "dependency-validation:")

    assert "needs.changes.outputs.backend == 'true'" in dep_block
    assert "needs.changes.outputs.dashboard == 'true'" in dep_block
    assert "needs.changes.outputs.demo == 'true'" in dep_block
    assert "needs.classify-tier.outputs.tier == 'main'" in dep_block

    status_job = workflow.split("status-check:", 1)[1]
    wave_block = status_job.split('"$tier" == "wave"', 1)[1].split('"$tier" == "main"', 1)[0]
    assert 'require "dependency-validation" "$deps" "true"' in wave_block
    main_block = status_job.split('"$tier" == "main"', 1)[1]
    assert 'require "dependency-validation" "$deps" "false"' in main_block


def test_main_tier_wave_to_main_checkpoint_unchanged() -> None:
    """AC: wave->main remains the full, path-aware checkpoint — main tier
    (pull_request into main/staging, and merge_group) still forces every
    domain true, untouched by wave-push domain matching."""
    workflow = _workflow()
    changes_job = _job_block(workflow, "changes:")
    set_outputs_block = changes_job.split("Set path-filter outputs", 1)[1]

    assert ('"$TIER" == "main"' in set_outputs_block) or ("== 'main'" in set_outputs_block)

    # merge_group Partner-policy job is untouched by this slice.
    assert "merge_group" in workflow
    live_sandbox_block = _job_block(workflow, "test-live-sandbox:")
    assert "github.event_name == 'merge_group'" in live_sandbox_block


def test_artifact_retention_guard_runs_only_on_issue_tier() -> None:
    """#1064: existence + PASS check of agent-runtime/artifacts/status/issue-<N>.json,
    scoped to the issue tier only, reusing classify-tier / resolve-issue rather than
    inventing a new branch-name convention."""
    workflow = _workflow()

    assert "artifact-retention-guard:" in workflow
    guard_job = _job_block(workflow, "artifact-retention-guard:")
    assert "needs.classify-tier.outputs.tier == 'issue'" in guard_job
    assert "classify-tier" in guard_job
    assert "resolve-issue" in guard_job
    assert "check_artifact_retention_guard.py" in guard_job


def test_status_check_requires_artifact_retention_guard_without_allowing_skip() -> None:
    """#1064: a skipped or cancelled artifact-retention-guard must never read green.
    Pins allow_skip == "false" inside the issue-tier require block specifically, so a
    future edit loosening that to "true" is caught here instead of silently reopening
    the hole this guard exists to close."""
    workflow = _workflow()

    status_job = workflow.split("status-check:", 1)[1]
    needs_block = status_job.split("needs:", 1)[1].split("if: always()", 1)[0]
    assert "- artifact-retention-guard" in needs_block
    assert 'artifact_retention_guard="${{ needs.artifact-retention-guard.result }}"' in status_job

    issue_block = status_job.split('"$tier" == "issue"', 1)[1].split("elif", 1)[0]
    assert 'require "artifact-retention-guard" "$artifact_retention_guard" "false"' in issue_block
