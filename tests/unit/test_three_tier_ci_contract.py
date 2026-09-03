"""Contract tests for the three-tier CI workflow."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterator
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


# --- HE-A/P-EVAL-2 (#1437): frontend jobs must be checked at wave tier ----
#
# The three frontend jobs (frontend, demo-frontend, landing-frontend) admitted
# only tier == 'issue' or (tier == 'main' && main_via_wave != 'true'). A wave
# assembled by local merges therefore reached main having run zero eslint, tsc
# or jest: nothing ran on the wave push, the wave->main run skipped them, and
# main-tier status-check accepted "skipped". #809 (936fa57c) fixed exactly this
# for lint/typecheck; the frontend jobs were not included.

FRONTEND_JOBS = ("frontend", "demo-frontend", "landing-frontend")

FRONTEND_JOB_DOMAIN = {
    "frontend": "dashboard",
    "demo-frontend": "demo",
    "landing-frontend": "landing",
}

_CONTEXT_REF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.(?:outputs\.([A-Za-z0-9_]+)|result)")
_EXPR_SUBSTITUTION = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


def _parsed_workflow() -> dict:
    return yaml.safe_load(_workflow())


def _eval_job_if(condition: str, *, tier: str, main_via_wave: str, changes: dict) -> bool:
    """Evaluate a job's GitHub `if:` expression for a concrete tier context.

    The frontend job conditions are pure boolean expressions over string
    comparisons of `needs.*.outputs.*`, so they translate 1:1 to Python. This
    asserts on what the condition *decides*, not on the text it is written in.
    """

    def resolve(match: re.Match[str]) -> str:
        job, key = match.group(1), match.group(2)
        if job == "classify-tier":
            return repr({"tier": tier, "main_via_wave": main_via_wave}[key])
        if job == "changes":
            return repr(changes.get(key, "false"))
        raise AssertionError(f"unhandled context reference: {match.group(0)}")

    # A folded `>-` scalar keeps real newlines for more-indented continuation
    # lines, which Python would read as unexpected indentation.
    expr = " ".join(condition.split())
    expr = _CONTEXT_REF.sub(resolve, expr)
    expr = expr.replace("&&", " and ").replace("||", " or ")
    return bool(eval(expr, {"__builtins__": {}}, {}))


def _status_check_script() -> str:
    workflow = _parsed_workflow()
    for step in workflow["jobs"]["status-check"]["steps"]:
        if step.get("name") == "Require tier jobs":
            return step["run"]
    raise AssertionError("status-check step 'Require tier jobs' not found")


def _run_status_check(
    *,
    tier: str,
    main_via_wave: str = "false",
    results: dict | None = None,
    changes: dict | None = None,
    event_name: str = "pull_request",
) -> subprocess.CompletedProcess[str]:
    """Run the real status-check bash script with substituted job results."""
    results = results or {}
    changes = changes or {}

    def resolve(match: re.Match[str]) -> str:
        ref = match.group(1)
        if ref == "github.event_name":
            return event_name
        if ref == "needs.classify-tier.outputs.tier":
            return tier
        if ref == "needs.classify-tier.outputs.main_via_wave":
            return main_via_wave
        if ref.startswith("needs.changes.outputs."):
            return changes.get(ref.rsplit(".", 1)[1], "true")
        result_ref = re.fullmatch(r"needs\.([A-Za-z0-9_-]+)\.result", ref)
        if result_ref:
            return results.get(result_ref.group(1), "success")
        raise AssertionError(f"unhandled status-check reference: {ref}")

    script = _EXPR_SUBSTITUTION.sub(resolve, _status_check_script())
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def _needs_violations(jobs: dict) -> list[str]:
    """Duplicate and dangling `needs:` entries, per job."""
    violations: list[str] = []
    for name, body in jobs.items():
        needs = (body or {}).get("needs")
        if needs is None:
            continue
        if isinstance(needs, str):
            needs = [needs]
        for dep in sorted({d for d in needs if needs.count(d) > 1}):
            violations.append(f"{name}: duplicate needs entry {dep!r}")
        for dep in needs:
            if dep not in jobs:
                violations.append(f"{name}: needs unknown job {dep!r}")
    return violations


def test_frontend_jobs_run_at_wave_tier() -> None:
    """AC1: a push to feature/*-wave touching a frontend domain runs that
    domain's frontend job instead of skipping it — and wave->main can no
    longer assume an issue-tier run happened, so it must run there too."""
    jobs = _parsed_workflow()["jobs"]

    for job in FRONTEND_JOBS:
        condition = jobs[job]["if"]
        changed = {FRONTEND_JOB_DOMAIN[job]: "true"}

        assert (
            _eval_job_if(condition, tier="wave", main_via_wave="false", changes=changed) is True
        ), f"{job} does not run on a wave push that changed its sources"

        # A wave assembled by local merges never saw issue tier, so the
        # wave->main checkpoint must run them rather than dedup them away.
        assert (
            _eval_job_if(condition, tier="main", main_via_wave="true", changes=changed) is True
        ), f"{job} skips on wave->main, leaving the wave unchecked"

        # Domain gating is preserved: an untouched domain still skips.
        assert _eval_job_if(condition, tier="wave", main_via_wave="false", changes={}) is False, (
            f"{job} runs at wave tier for a domain that did not change"
        )

        # Issue tier is unchanged.
        assert (
            _eval_job_if(condition, tier="issue", main_via_wave="false", changes=changed) is True
        ), f"{job} no longer runs at issue tier"


def test_main_via_wave_rejects_skipped_frontend() -> None:
    """AC2: on the main-tier wave->main path, a `skipped` frontend result
    must fail status-check rather than satisfy it."""
    baseline = _run_status_check(tier="main", main_via_wave="true")
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr

    for job in FRONTEND_JOBS:
        # Plant the lie: the job never ran, but its sources changed.
        planted = _run_status_check(tier="main", main_via_wave="true", results={job: "skipped"})
        assert planted.returncode != 0, (
            f"{job}: 'skipped' accepted on the wave->main path\n{planted.stdout}"
        )
        assert job in planted.stdout, planted.stdout

    # Not reached via a wave: the #658 dedup allowance is unchanged.
    for job in FRONTEND_JOBS:
        allowed = _run_status_check(tier="main", main_via_wave="false", results={job: "skipped"})
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr

    # Reached via a wave but the domain genuinely did not change: skipping is
    # correct and must not fail.
    untouched = _run_status_check(
        tier="main",
        main_via_wave="true",
        results={"frontend": "skipped"},
        changes={"dashboard": "false"},
    )
    assert untouched.returncode == 0, untouched.stdout + untouched.stderr


def test_needs_graph_has_no_duplicate_or_dangling_entries() -> None:
    """AC3: every job's `needs:` list is duplicate-free and names only jobs
    that exist. Duplicate `- <job>` entries make a string-replace edit land on
    the wrong job, with an empty `needs.X.result` as the only symptom."""
    jobs = _parsed_workflow()["jobs"]

    assert _needs_violations(jobs) == []

    # The checker itself must catch a planted duplicate and a planted dangling
    # entry, so a green above means "clean", never "did not look".
    planted_duplicate = {
        "a": {},
        "b": {"needs": ["a", "a"]},
    }
    assert _needs_violations(planted_duplicate) == ["b: duplicate needs entry 'a'"]

    planted_dangling = {"a": {}, "b": {"needs": ["a", "ghost"]}}
    assert _needs_violations(planted_dangling) == ["b: needs unknown job 'ghost'"]


# --- HE-A/P-EVAL-3 (#1440): the code-reading validate gates run in CI --------
#
# `grep -rn "scripts/validate" .github/workflows/` returned zero. The 29 gates in
# agent-runtime/scripts/validate/ executed only locally, invoked by an agent,
# against artifacts that same agent wrote. The `validate-gates` job runs the
# subset whose inputs are code, git or `gh` — never one of the five gitignored
# artifact body directories, which are absent from any CI checkout.

VALIDATE_GATES_JOB = "validate-gates"
VALIDATE_GATES_STEP = "Run code-reading validate gates"

EXPECTED_BLOCKING_GATES = [
    "check_module_boundaries",
    "check_module_drift",
    "check_adr",
    "check_done_md",
]
# check_differential_tdd keeps the advisory status and promotion criterion
# documented at agent-runtime/scripts/ci/generate_validation_artifact.py:65-75.
# check_unpushed_issue_work infers intent from repo-wide branch/worktree state
# that no PR author controls — advisory per Architect lock 5 (#1434).
EXPECTED_ADVISORY_GATES = [
    "check_differential_tdd",
    "check_unpushed_issue_work",
]

# check_acceptance_mapping was named in #1440's list but is NOT wired. The
# criterion below is measured, not grepped: an earlier draft of this test
# scanned each gate's source for `load_review_artifact` and friends, and that
# proxy is wrong — check_adr *calls* `load_review_artifact(issue) or {}` and
# carries on without it, while check_acceptance_mapping returns
# `False, "Review artifact missing"` on the very next line. Source mentions do
# not separate the two; behaviour on an artifact-free checkout does.
#
# An issue number with no artifact body anywhere: exactly the state of any CI
# checkout, where the five body directories are gitignored and never pushed.
ARTIFACT_FREE_ISSUE = "999999"
ARTIFACT_MISSING_MARKER = "artifact missing"

VALIDATE_DIR = ROOT / "agent-runtime" / "scripts" / "validate"

_BASH_ARRAY = re.compile(r"^([A-Z_]+)=\(([^)]*)\)$", re.MULTILINE)


def _validate_gates_step_run() -> str:
    job = _parsed_workflow()["jobs"][VALIDATE_GATES_JOB]
    for step in job["steps"]:
        if step.get("name") == VALIDATE_GATES_STEP:
            return step["run"]
    raise AssertionError(f"step {VALIDATE_GATES_STEP!r} not found in {VALIDATE_GATES_JOB}")


def _wired_gate_lists() -> dict[str, list[str]]:
    arrays = dict(_BASH_ARRAY.findall(_validate_gates_step_run()))
    return {name: value.split() for name, value in arrays.items()}


def _run_real_gate(gate: str, issue: str) -> subprocess.CompletedProcess[str]:
    """Run a real gate script the way the pr.yml job does: `--issue <n>`, and
    with GITHUB_BASE_REF absent so git_changed_files() takes its working-tree
    fallback instead of the shallow-fetch branch the job deliberately avoids."""
    env = {key: value for key, value in os.environ.items() if key != "GITHUB_BASE_REF"}
    return subprocess.run(
        [sys.executable, str(VALIDATE_DIR / f"{gate}.py"), "--issue", issue],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _stub_gate_tree(tmp: Path, bodies: dict[str, str]) -> Path:
    """A checkout-shaped temp tree holding stub gate scripts."""
    gates_dir = tmp / "agent-runtime" / "scripts" / "validate"
    gates_dir.mkdir(parents=True)
    for gate, body in bodies.items():
        (gates_dir / f"{gate}.py").write_text(body, encoding="utf-8")
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    return bin_dir


def _passing_stub(gate: str) -> str:
    return f'print("{gate.removeprefix("check_")}: PASS")\n'


def _failing_stub(gate: str) -> str:
    return f'import sys\nprint("{gate.removeprefix("check_")}: FAIL — planted")\nsys.exit(1)\n'


CRASHING_STUB = 'raise RuntimeError("gate could not read its input")\n'


def _run_validate_gates(
    *,
    bodies: dict[str, str],
    issue_number: str = "1440",
) -> subprocess.CompletedProcess[str]:
    """Execute the real `run:` bash from pr.yml against stub gate scripts."""
    script = _validate_gates_step_run()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        bin_dir = _stub_gate_tree(tmp, bodies)
        return subprocess.run(
            ["bash", "-c", script],
            cwd=tmp,
            env={
                "ISSUE_NUMBER": issue_number,
                "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/local/bin",
            },
            capture_output=True,
            text=True,
        )


def test_validate_gates_job_enumerates_code_reading_gates() -> None:
    """AC1: an issue-tier PR runs a job that executes the code-reading gates
    and reports each gate's name and result.

    The wired list is asserted against the gates' own source, not against a
    copy of #1440's prose: any gate reaching into one of the five gitignored
    artifact body directories must not be a blocking entry, because a CI
    checkout never contains those files.
    """
    jobs = _parsed_workflow()["jobs"]
    assert VALIDATE_GATES_JOB in jobs, "no job runs agent-runtime/scripts/validate/ in CI"

    condition = jobs[VALIDATE_GATES_JOB]["if"]
    assert _eval_job_if(condition, tier="issue", main_via_wave="false", changes={}) is True
    assert _eval_job_if(condition, tier="wave", main_via_wave="false", changes={}) is False
    assert _eval_job_if(condition, tier="main", main_via_wave="false", changes={}) is False

    wired = _wired_gate_lists()
    assert wired.get("BLOCKING_GATES") == EXPECTED_BLOCKING_GATES
    assert wired.get("ADVISORY_GATES") == EXPECTED_ADVISORY_GATES

    for gate in EXPECTED_BLOCKING_GATES + EXPECTED_ADVISORY_GATES:
        assert (VALIDATE_DIR / f"{gate}.py").exists(), f"{gate} is wired but has no script"

    # Teeth, measured: every blocking gate must reach a verdict on a checkout
    # that holds no artifact body. Asserting on "reached a verdict, and not
    # because an artifact was missing" keeps this independent of whether the
    # working tree happens to contain a real boundary violation today.
    for gate in EXPECTED_BLOCKING_GATES:
        measured = _run_real_gate(gate, ARTIFACT_FREE_ISSUE)
        assert re.search(r"^[a-z_]+: (PASS|FAIL)", measured.stdout, re.MULTILINE), (
            f"{gate} reached no verdict without artifact input\n{measured.stdout}{measured.stderr}"
        )
        assert ARTIFACT_MISSING_MARKER not in measured.stdout.lower(), (
            f"{gate} is wired blocking but cannot answer without a gitignored"
            f" artifact body\n{measured.stdout}"
        )

    # The same measurement on the gate #1440 listed and this slice dropped: it
    # has no tolerant path, so in CI it can only ever fail — the universally
    # failing job #1440 explicitly rules out.
    dropped = _run_real_gate("check_acceptance_mapping", ARTIFACT_FREE_ISSUE)
    assert dropped.returncode != 0, dropped.stdout
    assert 'return False, "Review artifact missing"' in (
        VALIDATE_DIR / "check_acceptance_mapping.py"
    ).read_text(encoding="utf-8")
    assert "check_acceptance_mapping" not in _validate_gates_step_run()

    # check_differential_tdd fails the same measurement, and is wired advisory
    # rather than dropped because #1440 says so and keeps its promotion
    # criterion. Advisory is what makes that honest: it runs and reports, and
    # cannot block on an input CI does not have until #1438 supplies one.
    difftdd = _run_real_gate("check_differential_tdd", ARTIFACT_FREE_ISSUE)
    assert difftdd.returncode != 0, difftdd.stdout
    assert ARTIFACT_MISSING_MARKER in difftdd.stdout.lower(), difftdd.stdout
    assert "check_differential_tdd" in _wired_gate_lists()["ADVISORY_GATES"]

    # status-check must require it at issue tier, and must not accept "skipped".
    status_job = _workflow().split("status-check:", 1)[1]
    assert 'require "validate-gates" "$validate_gates" "false"' in status_job

    planted = _run_status_check(tier="issue", results={VALIDATE_GATES_JOB: "failure"})
    assert planted.returncode != 0, planted.stdout
    assert VALIDATE_GATES_JOB in planted.stdout


def test_validate_gates_job_fails_closed_on_gate_error() -> None:
    """AC3: a gate that raises, or cannot read its input, fails the job rather
    than passing it — proven by executing pr.yml's real bash against stub gates,
    not by asserting the workflow text mentions the word "fail"."""
    all_gates = EXPECTED_BLOCKING_GATES + EXPECTED_ADVISORY_GATES
    green = {gate: _passing_stub(gate) for gate in all_gates}

    baseline = _run_validate_gates(bodies=green)
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    # "reports each gate's name and result"
    for gate in all_gates:
        assert gate in baseline.stdout, f"{gate} not reported\n{baseline.stdout}"

    # A gate that raises prints no PASS/FAIL verdict. Python exits 1 either way,
    # so the job must key off the missing verdict line, not the exit code alone.
    for gate in all_gates:
        crashed = _run_validate_gates(bodies={**green, gate: CRASHING_STUB})
        assert crashed.returncode != 0, (
            f"{gate} raised and the job still passed\n{crashed.stdout}{crashed.stderr}"
        )
        assert gate in crashed.stdout

    # A gate script that is not there at all fails the job.
    for gate in all_gates:
        missing = {name: body for name, body in green.items() if name != gate}
        absent = _run_validate_gates(bodies=missing)
        assert absent.returncode != 0, f"{gate} missing and the job still passed\n{absent.stdout}"
        assert gate in absent.stdout

    # A blocking gate reporting FAIL blocks; an advisory one is reported and does not.
    for gate in EXPECTED_BLOCKING_GATES:
        blocked = _run_validate_gates(bodies={**green, gate: _failing_stub(gate)})
        assert blocked.returncode != 0, f"blocking {gate} FAIL did not block\n{blocked.stdout}"

    for gate in EXPECTED_ADVISORY_GATES:
        advised = _run_validate_gates(bodies={**green, gate: _failing_stub(gate)})
        assert advised.returncode == 0, (
            f"advisory {gate} FAIL blocked the job\n{advised.stdout}{advised.stderr}"
        )
        assert "advisory" in advised.stdout.lower()

    # No issue number: a documented SKIP, never a silent claim that gates ran.
    skipped = _run_validate_gates(bodies=green, issue_number="")
    assert skipped.returncode == 0, skipped.stdout + skipped.stderr
    assert "SKIP" in skipped.stdout
    for gate in all_gates:
        assert f"{gate}: PASS" not in skipped.stdout


# --- CI-WAVE-1 (#1528): agent-runtime/scripts is inside the lint perimeter ---
#
# pr.yml's Ruff step listed `backend/src/juli_backend tests scripts` and the
# pre-commit `files:` regex listed `^(backend/|tests/|scripts/)`. Neither named
# `agent-runtime/`, so ~89 Python files holding every harness gate, generator
# and schema validator were linted by nothing. The drift is not theoretical:
# agent-runtime/scripts/ci/json_schema_validate.py had diverged from
# `ruff format` and was only re-canonicalised because #1509's executor (PR
# #1524) happened to be editing that file for an unrelated reason.
#
# These tests plant a real violation in the real tree and run the real command,
# because asserting that "agent-runtime/scripts" appears in the YAML would prove
# the path is configured, not that anything enforces it.

PROBE_SOURCE = "import json\n"  # unused import -> F401, selected by every profile


def _ci_ruff_command() -> list[str]:
    """The Ruff step's command, verbatim from pr.yml's lint job."""
    lint_job = _parsed_workflow()["jobs"]["lint"]
    for step in lint_job["steps"]:
        if step.get("name") == "Ruff":
            return shlex.split(step["run"].strip())
    raise AssertionError("no step named 'Ruff' in the lint job")


@contextlib.contextmanager
def _planted_violation(directory: Path) -> Iterator[Path]:
    """Write a file with a genuine lint violation, and always remove it."""
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / f"_lint_perimeter_probe_{os.getpid()}.py"
    probe.write_text(PROBE_SOURCE, encoding="utf-8")
    try:
        yield probe
    finally:
        probe.unlink(missing_ok=True)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=300
    )


def test_ci_ruff_command_catches_a_violation_planted_in_agent_runtime_scripts() -> None:
    """AC1: the command CI actually runs must fail on a violation introduced
    anywhere under agent-runtime/scripts/."""
    command = _ci_ruff_command()
    agent_scripts = ROOT / "agent-runtime" / "scripts"

    # The tree is clean before the plant, so a failure below is the plant.
    clean = _run(command)
    assert clean.returncode == 0, (
        f"lint perimeter is dirty before the probe was planted\n{clean.stdout}{clean.stderr}"
    )

    with _planted_violation(agent_scripts) as probe:
        caught = _run(command)

    assert caught.returncode != 0, (
        "a violation planted in agent-runtime/scripts/ was not caught by "
        f"{shlex.join(command)}\n{caught.stdout}{caught.stderr}"
    )
    assert probe.name in caught.stdout, caught.stdout + caught.stderr
    assert "F401" in caught.stdout, caught.stdout


def test_ci_ruff_command_covers_every_first_party_python_root() -> None:
    """AC1: no first-party Python root may sit outside the Ruff step's targets.
    A root that holds .py files and is named by no target is unlinted."""
    targets = set(_ci_ruff_command()[2:])
    for root in ("backend/src/juli_backend", "tests", "scripts", "agent-runtime/scripts"):
        assert root in targets, f"{root} is outside the Ruff step's targets: {sorted(targets)}"


def _precommit_ruff_hooks(hook_id: str) -> list[dict]:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    return [hook for repo in config["repos"] for hook in repo["hooks"] if hook["id"] == hook_id]


def _hook_matching(hook_id: str, path: str) -> dict:
    matches = [h for h in _precommit_ruff_hooks(hook_id) if re.search(h["files"], path)]
    assert matches, (
        f"no {hook_id} pre-commit hook has a `files:` pattern matching {path}; "
        "staged harness code would be committed unlinted"
    )
    return matches[0]


def test_precommit_ruff_check_enforces_agent_runtime_scripts() -> None:
    """AC2: a staged agent-runtime/scripts file reaches ruff-check, and the
    config that hook passes actually reports the violation."""
    hook = _hook_matching("ruff-check", "agent-runtime/scripts/harness_optimizer.py")

    args = hook.get("args", [])
    config = args[args.index("--config") + 1] if "--config" in args else None

    with _planted_violation(ROOT / "agent-runtime" / "scripts") as probe:
        command = ["ruff", "check", "--no-fix"]
        if config is not None:
            command += ["--config", config]
        command.append(str(probe.relative_to(ROOT)))
        result = _run(command)

    assert result.returncode != 0, (
        f"the ruff-check hook's config ({config}) does not flag an unused import"
        f"\n{result.stdout}{result.stderr}"
    )
    assert "F401" in result.stdout, result.stdout


def test_precommit_ruff_format_enforces_agent_runtime_scripts() -> None:
    """AC2: format drift in a staged agent-runtime/scripts file is caught —
    this is the exact defect json_schema_validate.py hit (silent drift)."""
    hook = _hook_matching("ruff-format", "agent-runtime/scripts/ci/json_schema_validate.py")

    args = hook.get("args", [])
    config = args[args.index("--config") + 1] if "--config" in args else None

    directory = ROOT / "agent-runtime" / "scripts"
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / f"_format_perimeter_probe_{os.getpid()}.py"
    probe.write_text("x = {  'a':1,\n  'b':2 }\n", encoding="utf-8")
    try:
        command = ["ruff", "format", "--check"]
        if config is not None:
            command += ["--config", config]
        command.append(str(probe.relative_to(ROOT)))
        result = _run(command)
    finally:
        probe.unlink(missing_ok=True)

    assert result.returncode != 0, (
        f"the ruff-format hook's config ({config}) accepts unformatted source"
        f"\n{result.stdout}{result.stderr}"
    )


def test_agent_runtime_scripts_changes_trigger_the_lint_job() -> None:
    """AC3: widening the Ruff targets is inert unless the domain filter that
    gates the lint job also fires for agent-runtime/scripts changes. The lint
    job runs only when `changes.outputs.backend == 'true'`."""
    workflow = _parsed_workflow()

    lint_if = workflow["jobs"]["lint"]["if"]
    assert "needs.changes.outputs.backend == 'true'" in lint_if, lint_if

    changes_job = _job_block(_workflow(), "changes:")
    filters = changes_job.split("filters: &domain-path-filters", 1)[1]
    backend_filter = filters.split("backend:", 1)[1].split("migrations:", 1)[0]
    assert "'agent-runtime/scripts/**'" in backend_filter, (
        "agent-runtime/scripts is linted by the Ruff step but no backend-domain "
        f"path filter fires for it, so the lint job is skipped:\n{backend_filter}"
    )

    # Docs- and config-only harness changes must stay in the cheap `agent`
    # domain — widening the perimeter must not drag markdown into the backend
    # test suite (see test_wave_push_agent_docs_only_stays_cheap_...).
    assert "'.cursor/**'" not in backend_filter
    assert "'agent-runtime/**'" not in backend_filter
