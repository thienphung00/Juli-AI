#!/usr/bin/env python3
"""Generate Meta Agent harness optimization proposals from runtime artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))

from build_runtime import ConfigError, load_simple_yaml, nested_get, validate_config
from harness_config import allowed_auto_apply_fields, apply_change, preview_change
from common import (
    IMPLEMENTATIONS_DIR,
    OPTIMIZATION_DIR,
    REPO_ROOT,
    REVIEWS_DIR,
    RUNTIME_SCHEMA_VERSION,
    VALIDATION_DIR,
    load_json,
    resolve_issue_number,
    utc_now_iso,
    write_json,
)


DEFAULT_CONFIG = REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml"
ROOT_CAUSE_ORDER = [
    "artifact_incomplete",
    "validation_failure",
    "review_gap",
    "wrong_executor_domain",
    "context_overloaded",
    "context_underloaded",
    "tool_overuse",
    "phase_loop",
]
ALLOWED_AUTO_APPLY_TARGETS = allowed_auto_apply_fields()


@dataclass(frozen=True)
class ProposedFix:
    summary: str
    change_type: str
    details: str
    config_target: str
    expected_impact: str
    metric_impacts: list[dict[str, str]]
    harness_config_targets: list[str]
    auto_apply_eligible: bool
    value: Any | None = None


@dataclass(frozen=True)
class OptimizationRule:
    name: str
    detection_rule: Callable[[dict[str, Any]], bool]
    proposed_fix: Callable[[dict[str, Any]], ProposedFix]


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def artifact_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def load_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return load_json(path)


def review_failure_count(review: dict[str, Any] | None) -> int:
    if not review:
        return 0
    if "reviewFailures" in review:
        return as_int(review["reviewFailures"])
    findings = review.get("criticalFindings", [])
    return sum(
        1
        for finding in findings
        if finding.get("severity") == "CRITICAL" or finding.get("actionRequired")
    )


def validation_failure_count(validation: dict[str, Any] | None) -> int:
    if not validation:
        return 0
    if "validationFailures" in validation:
        return as_int(validation["validationFailures"])
    if "failedChecks" in validation:
        return as_int(validation["failedChecks"])
    return sum(1 for check in validation.get("checks", []) if check.get("status") == "FAIL")


def token_usage(implementation: dict[str, Any] | None) -> dict[str, int]:
    usage = (implementation or {}).get("tokenUsage") or {}
    input_tokens = as_int(usage.get("input"))
    output_tokens = as_int(usage.get("output"))
    total = as_int(usage.get("total"), input_tokens + output_tokens)
    return {"input": input_tokens, "output": output_tokens, "total": total}


def test_pass_rate(validation: dict[str, Any] | None, review: dict[str, Any] | None) -> float:
    passed = as_int((validation or {}).get("testsPassed"))
    failed = as_int((validation or {}).get("testsFailed"))
    if passed == 0 and failed == 0:
        unit = (review or {}).get("testCoverage", {}).get("unit", {})
        passed = as_int(unit.get("passed"))
        failed = as_int(unit.get("failed"))
    total = passed + failed
    if total == 0:
        return 1.0
    return round(passed / total, 4)


def coverage_percentage(validation: dict[str, Any] | None, review: dict[str, Any] | None) -> float:
    if validation and "coveragePercentage" in validation:
        return as_float(validation["coveragePercentage"])
    acceptance = (review or {}).get("testCoverage", {}).get("acceptance", {})
    total = as_int(acceptance.get("total"))
    mapped = as_int(acceptance.get("mapped"))
    if total == 0:
        return 0.0
    return round((mapped / total) * 100, 2)


def expected_executor_from_paths(
    paths: list[str],
    *,
    domain_mappings: dict[str, Any],
) -> str | None:
    """Score path prefixes from routing.domain_mappings (longest match wins)."""
    scores: dict[str, int] = {}
    for domain, prefixes in (domain_mappings or {}).items():
        if not isinstance(prefixes, list):
            continue
        for path in paths:
            normalized = str(path).replace("\\", "/")
            for prefix in prefixes:
                pref = str(prefix).replace("\\", "/").rstrip("/")
                if not pref:
                    continue
                if normalized == pref or normalized.startswith(pref + "/"):
                    scores[domain] = scores.get(domain, 0) + max(1, len(pref) // 8)
    if not scores:
        return None
    return max(scores.items(), key=lambda item: item[1])[0]


def expected_executor_from_review(
    review: dict[str, Any] | None,
    *,
    implementation: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Prefer filesModified path scoring; fall back to modulesTouched tokens."""
    cfg = config or {}
    routing = cfg.get("routing") or {}
    files_modified = list((implementation or {}).get("filesModified") or [])
    if files_modified:
        from_paths = expected_executor_from_paths(
            [str(p) for p in files_modified],
            domain_mappings=routing.get("domain_mappings") or {},
        )
        if from_paths:
            return from_paths

    modules = set(str(item) for item in (review or {}).get("modulesTouched", []))
    # Path-like module tokens (packages/ui, apps/demo) — never default bare lists to backend.
    module_paths = [m for m in modules if "/" in m]
    if module_paths:
        from_modules = expected_executor_from_paths(
            module_paths,
            domain_mappings=routing.get("domain_mappings") or {},
        )
        if from_modules:
            return from_modules
    if modules & {"web", "ios", "ui", "frontend", "apps/demo", "packages/ui"}:
        return "ui-ux"
    if modules & {"data", "database", "migrations", "alembic"}:
        return "data-platform"
    if modules & {"ml", "machine-learning", "intelligence"}:
        return "machine-learning"
    if modules & {"api", "services", "workers", "integrations", "infra"}:
        return "backend"
    return None


def collect_metrics(
    implementation: dict[str, Any] | None,
    review: dict[str, Any] | None,
    validation: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    usage = token_usage(implementation)
    review_failures = review_failure_count(review)
    validation_failures = validation_failure_count(validation)
    execution_duration = as_int((implementation or {}).get("executionDurationMs")) + as_int(
        (validation or {}).get("executionDurationMs")
    )
    retry_count = as_int((validation or {}).get("retryCount"))
    tool_count = as_int((implementation or {}).get("toolInvocationCount"))
    context_files = (implementation or {}).get("contextFilesLoaded") or []
    skills = (implementation or {}).get("skillsLoaded") or []

    return {
        "config": config,
        "implementation": implementation,
        "review": review,
        "validation": validation,
        "missingArtifacts": [
            name
            for name, artifact in {
                "implementation": implementation,
                "review": review,
                "validation": validation,
            }.items()
            if artifact is None
        ],
        "issueId": as_int(
            (implementation or {}).get("issueId")
            or (review or {}).get("issue")
            or (validation or {}).get("issue")
        ),
        "phaseRunId": str(
            (implementation or {}).get("phaseRunId")
            or (review or {}).get("phaseRunId")
            or (validation or {}).get("phaseRunId")
            or "unknown"
        ),
        "executorAssigned": str((implementation or {}).get("executorDomain") or "none"),
        "expectedExecutor": expected_executor_from_review(
            review, implementation=implementation, config=config
        ),
        "contextFilesLoaded": context_files,
        "skillsLoaded": skills,
        "tokenUsage": usage,
        "executionDurationMs": execution_duration,
        "reviewFailures": review_failures,
        "validationFailures": validation_failures,
        "retryCount": retry_count,
        "contextTransferCount": as_int((implementation or {}).get("contextTransferCount")),
        "toolInvocationCount": tool_count,
        "baselineMetrics": {
            "executionTimeMs": execution_duration,
            "tokenUsageTotal": usage["total"],
            "testPassRate": test_pass_rate(validation, review),
            "coveragePercentage": coverage_percentage(validation, review),
            "reviewFailureRate": 1.0 if review_failures else 0.0,
            "validationFailureRate": 1.0 if validation_failures else 0.0,
            "retryCount": retry_count,
            "toolInvocationCount": tool_count,
        },
    }


def _context_limit(metrics: dict[str, Any], key: str, default: int) -> int:
    return as_int(metrics["config"].get("context", {}).get(key), default)


def detect_artifact_incomplete(metrics: dict[str, Any]) -> bool:
    required = [
        "issueId",
        "phaseRunId",
        "executorDomain",
        "executionDurationMs",
        "toolInvocationCount",
    ]
    implementation = metrics.get("implementation") or {}
    return bool(metrics["missingArtifacts"]) or any(key not in implementation for key in required)


def fix_artifact_incomplete(metrics: dict[str, Any]) -> ProposedFix:
    missing = ", ".join(metrics["missingArtifacts"]) or "required implementation fields"
    return ProposedFix(
        summary="Complete runtime artifact emission before optimizing harness behavior.",
        change_type="other",
        details=f"Missing or incomplete artifact evidence: {missing}.",
        config_target="artifacts",
        expected_impact="Improves optimization reliability by restoring deterministic evidence.",
        metric_impacts=[{"metric": "validationFailureRate", "direction": "neutral", "magnitude": "low"}],
        harness_config_targets=["agent_runtime_config"],
        auto_apply_eligible=False,
    )


def detect_validation_failure(metrics: dict[str, Any]) -> bool:
    validation = metrics.get("validation") or {}
    return metrics["validationFailures"] > 0 or validation.get("status") == "FAIL"


def fix_validation_failure(metrics: dict[str, Any]) -> ProposedFix:
    return ProposedFix(
        summary="Route future failing validations through a reviewer-backed executor structure.",
        change_type="other",
        details="Validation failed after implementation; require Architect/Meta approval before changing agent structure.",
        config_target="agent_structure.mode",
        expected_impact="Expected to reduce validation failures on similar tasks.",
        metric_impacts=[{"metric": "validationFailureRate", "direction": "decrease", "magnitude": "medium"}],
        harness_config_targets=["agent_runtime_config"],
        auto_apply_eligible=False,
        value="planner_executor_reviewer",
    )


def detect_review_gap(metrics: dict[str, Any]) -> bool:
    review = metrics.get("review") or {}
    return metrics["reviewFailures"] > 0 or review.get("status") == "FAIL"


def fix_review_gap(metrics: dict[str, Any]) -> ProposedFix:
    executor = metrics["executorAssigned"] if metrics["executorAssigned"] != "none" else "backend"
    return ProposedFix(
        summary=f"Load review-oriented guidance earlier for {executor} executions.",
        change_type="other",
        details="Review found blocking issues that earlier executor context did not prevent.",
        config_target=f"skills.{executor}",
        expected_impact="Expected to reduce review failures on similar tasks.",
        metric_impacts=[{"metric": "reviewFailureRate", "direction": "decrease", "magnitude": "medium"}],
        harness_config_targets=["agent_runtime_config"],
        auto_apply_eligible=False,
    )


def detect_wrong_executor_domain(metrics: dict[str, Any]) -> bool:
    expected = metrics.get("expectedExecutor")
    assigned = metrics.get("executorAssigned")
    enabled = set(metrics["config"].get("executors", {}).get("enabled", []))
    return bool((assigned and assigned not in {"none", *enabled}) or (expected and assigned != expected))


def fix_wrong_executor_domain(metrics: dict[str, Any]) -> ProposedFix:
    expected = metrics.get("expectedExecutor") or "backend"
    assigned = metrics.get("executorAssigned")
    # Threshold nudges are disabled until path-prefix detector is measured — propose
    # domain_mappings / slice precedence instead (not auto-apply).
    return ProposedFix(
        summary=(
            f"Prefer slice-routing executorDomain and path-prefix scoring "
            f"(assigned {assigned}, path evidence → {expected})."
        ),
        change_type="routing_hint",
        details=(
            f"Assigned {assigned} but filesModified/domain_mappings score {expected}. "
            "Do not auto-lower routing thresholds; extend domain_mappings and prefer "
            "workflow_prompt_cache / slice-routing.yml executorDomain at Meta assignment."
        ),
        config_target="routing.prefer_slice_executor_domain",
        expected_impact="Expected to reduce false wrong_executor_domain flags and true misroutes.",
        metric_impacts=[
            {"metric": "retryCount", "direction": "decrease", "magnitude": "medium"},
            {"metric": "reviewFailureRate", "direction": "decrease", "magnitude": "low"},
        ],
        harness_config_targets=["agent_runtime_config", "executor_domain_hints"],
        auto_apply_eligible=False,
        # Advisory only — not in harness-editable.yml; Meta/Architect update slice-routing.
        value=None,
    )


def detect_context_overloaded(metrics: dict[str, Any]) -> bool:
    max_files = _context_limit(metrics, "max_files", 25)
    budget_tokens = _context_limit(metrics, "budget_tokens", 50000)
    return len(metrics["contextFilesLoaded"]) > max_files or metrics["tokenUsage"]["total"] > budget_tokens


def fix_context_overloaded(metrics: dict[str, Any]) -> ProposedFix:
    max_files = _context_limit(metrics, "max_files", 25)
    new_value = max(5, int(max_files * 0.8))
    return ProposedFix(
        summary="Reduce maximum context files for similar runs.",
        change_type="context_budget",
        details=f"Loaded {len(metrics['contextFilesLoaded'])} files against a max_files budget of {max_files}.",
        config_target="context.max_files",
        expected_impact="Expected to reduce token usage and execution time.",
        metric_impacts=[
            {"metric": "tokenUsageTotal", "direction": "decrease", "magnitude": "medium"},
            {"metric": "executionTimeMs", "direction": "decrease", "magnitude": "low"},
        ],
        harness_config_targets=["agent_runtime_config"],
        auto_apply_eligible=True,
        value=new_value,
    )


def detect_context_underloaded(metrics: dict[str, Any]) -> bool:
    review = metrics.get("review") or {}
    acceptance = review.get("testCoverage", {}).get("acceptance", {})
    unmapped = acceptance.get("unmapped") or []
    return bool(unmapped and len(metrics["contextFilesLoaded"]) < 5)


def fix_context_underloaded(metrics: dict[str, Any]) -> ProposedFix:
    max_files = _context_limit(metrics, "max_files", 25)
    new_value = min(50, max_files + 5)
    return ProposedFix(
        summary="Increase context file budget so acceptance criteria and module context can be loaded together.",
        change_type="context_budget",
        details="Review artifact shows unmapped acceptance criteria with very few context files loaded.",
        config_target="context.max_files",
        expected_impact="Expected to increase coverage and reduce review gaps.",
        metric_impacts=[
            {"metric": "coveragePercentage", "direction": "increase", "magnitude": "medium"},
            {"metric": "reviewFailureRate", "direction": "decrease", "magnitude": "low"},
        ],
        harness_config_targets=["agent_runtime_config"],
        auto_apply_eligible=True,
        value=new_value,
    )


def detect_tool_overuse(metrics: dict[str, Any]) -> bool:
    limit = as_int(metrics["config"].get("tools", {}).get("max_invocations_per_run"), 80)
    return metrics["toolInvocationCount"] > limit


def fix_tool_overuse(metrics: dict[str, Any]) -> ProposedFix:
    limit = as_int(metrics["config"].get("tools", {}).get("max_invocations_per_run"), 80)
    new_value = max(limit, metrics["toolInvocationCount"])
    return ProposedFix(
        summary="Raise a benchmark threshold for tool use before changing tool availability.",
        change_type="benchmark_threshold",
        details=f"Observed {metrics['toolInvocationCount']} tool invocations above configured limit {limit}.",
        config_target="benchmark.thresholds.tool_invocation_regression_count",
        expected_impact="Expected to make tool overuse measurable before disabling tools.",
        metric_impacts=[{"metric": "toolInvocationCount", "direction": "decrease", "magnitude": "low"}],
        harness_config_targets=["benchmark_tasks"],
        auto_apply_eligible=False,
        value=new_value,
    )


def detect_phase_loop(metrics: dict[str, Any]) -> bool:
    return metrics["retryCount"] > 1 or metrics["contextTransferCount"] > 1


def fix_phase_loop(metrics: dict[str, Any]) -> ProposedFix:
    return ProposedFix(
        summary="Add a stricter retry regression threshold for benchmark reruns.",
        change_type="benchmark_threshold",
        details="Retries or context transfers indicate a phase loop.",
        config_target="benchmark.thresholds.failure_regression_count",
        expected_impact="Expected to surface phase loops as measurable benchmark regressions.",
        metric_impacts=[{"metric": "retryCount", "direction": "decrease", "magnitude": "medium"}],
        harness_config_targets=["benchmark_tasks"],
        auto_apply_eligible=True,
        value=0,
    )


ROOT_CAUSE_RULES = {
    "artifact_incomplete": OptimizationRule(
        "artifact_incomplete",
        detect_artifact_incomplete,
        fix_artifact_incomplete,
    ),
    "validation_failure": OptimizationRule(
        "validation_failure",
        detect_validation_failure,
        fix_validation_failure,
    ),
    "review_gap": OptimizationRule("review_gap", detect_review_gap, fix_review_gap),
    "wrong_executor_domain": OptimizationRule(
        "wrong_executor_domain",
        detect_wrong_executor_domain,
        fix_wrong_executor_domain,
    ),
    "context_overloaded": OptimizationRule(
        "context_overloaded",
        detect_context_overloaded,
        fix_context_overloaded,
    ),
    "context_underloaded": OptimizationRule(
        "context_underloaded",
        detect_context_underloaded,
        fix_context_underloaded,
    ),
    "tool_overuse": OptimizationRule("tool_overuse", detect_tool_overuse, fix_tool_overuse),
    "phase_loop": OptimizationRule("phase_loop", detect_phase_loop, fix_phase_loop),
}


def detect_root_cause(metrics: dict[str, Any]) -> tuple[str, ProposedFix]:
    for name in ROOT_CAUSE_ORDER:
        rule = ROOT_CAUSE_RULES[name]
        if rule.detection_rule(metrics):
            return name, rule.proposed_fix(metrics)
    return "none", ProposedFix(
        summary="No harness change proposed; current artifact metrics are within configured thresholds.",
        change_type="other",
        details="Meta did not detect a deterministic optimization opportunity.",
        config_target="agent-runtime.config.yml",
        expected_impact="No expected metric change.",
        metric_impacts=[{"metric": "executionTimeMs", "direction": "neutral", "magnitude": "low"}],
        harness_config_targets=["agent_runtime_config"],
        auto_apply_eligible=False,
    )


def apply_fix(config_path: Path, fix: ProposedFix, *, confirm: bool = False) -> tuple[bool, dict[str, Any] | None]:
    if not fix.auto_apply_eligible or fix.config_target not in ALLOWED_AUTO_APPLY_TARGETS:
        return False, None
    if fix.value is None:
        return False, None
    try:
        result = apply_change(fix.config_target, fix.value, config_path=config_path, confirm=confirm)
    except Exception:
        return False, None
    return bool(result.get("applied")), result


def build_optimization_artifact(
    metrics: dict[str, Any],
    root_cause: str,
    fix: ProposedFix,
    *,
    source_paths: dict[str, Path],
    applied: bool = False,
    dry_run: bool = True,
    config_diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auto_apply = fix.auto_apply_eligible and fix.config_target in ALLOWED_AUTO_APPLY_TARGETS
    if applied:
        applied_status = "applied"
    elif dry_run:
        applied_status = "proposed"
    else:
        applied_status = "proposed"
    artifact: dict[str, Any] = {
        "schemaVersion": RUNTIME_SCHEMA_VERSION,
        "artifactType": "harness_optimization",
        "issueId": metrics["issueId"],
        "phaseRunId": metrics["phaseRunId"],
        "phasePath": ["implementation", "review", "validation", "harness_optimization"],
        "executorAssigned": metrics["executorAssigned"],
        "contextFilesLoaded": metrics["contextFilesLoaded"],
        "skillsLoaded": metrics["skillsLoaded"],
        "tokenUsage": metrics["tokenUsage"],
        "executionDurationMs": metrics["executionDurationMs"],
        "reviewFailures": metrics["reviewFailures"],
        "validationFailures": metrics["validationFailures"],
        "retryCount": metrics["retryCount"],
        "contextTransferCount": metrics["contextTransferCount"],
        "toolInvocationCount": metrics["toolInvocationCount"],
        "baselineMetrics": metrics["baselineMetrics"],
        "rootCauseCategory": root_cause,
        "rootCause": root_cause,
        "proposedOptimization": {
            "summary": fix.summary,
            "changeType": fix.change_type,
            "details": fix.details,
        },
        "configTarget": fix.config_target,
        "expectedMetricImpact": fix.metric_impacts,
        "predictedImpact": {
            "summary": fix.expected_impact,
            "metrics": fix.metric_impacts,
        },
        "expectedImpact": fix.expected_impact,
        "harnessConfigTargets": fix.harness_config_targets,
        "autoApplyEligible": auto_apply,
        "dryRun": dry_run and not applied,
        "humanApprovalRequired": auto_apply and not applied,
        "appliedStatus": applied_status,
        "sourceArtifacts": {
            name: artifact_path(path)
            for name, path in source_paths.items()
            if path.exists()
        },
        "notes": "Meta Agent optimization is limited to declarative harness configuration.",
    }
    if config_diff is not None:
        artifact["configDiff"] = config_diff
    return artifact


def evaluate_before_after(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_metrics = before.get("baselineMetrics", before)
    after_metrics = after.get("baselineMetrics", after)
    comparisons = {}
    metric_map = {
        "executionTimeMs": "execution time",
        "tokenUsageTotal": "token usage",
        "reviewFailureRate": "review failures",
        "validationFailureRate": "validation failures",
        "retryCount": "retry count",
    }
    improved = 0
    regressed = 0
    for key, label in metric_map.items():
        before_value = as_float(before_metrics.get(key))
        after_value = as_float(after_metrics.get(key))
        delta = after_value - before_value
        status = "unchanged"
        if delta < 0:
            status = "improved"
            improved += 1
        elif delta > 0:
            status = "regressed"
            regressed += 1
        comparisons[key] = {
            "label": label,
            "before": before_value,
            "after": after_value,
            "delta": delta,
            "status": status,
        }
    return {
        "status": "regressed" if regressed else "improved" if improved else "unchanged",
        "improvedMetrics": improved,
        "regressedMetrics": regressed,
        "comparisons": comparisons,
    }


def propose(args: argparse.Namespace) -> int:
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: could not resolve issue number (use --issue or feat/issue-N branch)", file=sys.stderr)
        return 1

    config = load_simple_yaml(args.config)
    validate_config(config)
    source_paths = {
        "implementation": args.implementation
        or IMPLEMENTATIONS_DIR
        / f"implementation-issue-{issue}.json",
        "review": args.review or REVIEWS_DIR / f"review-issue-{issue}.json",
        "validation": args.validation or VALIDATION_DIR / f"validation-issue-{issue}.json",
    }
    implementation = load_artifact(source_paths["implementation"])
    review = load_artifact(source_paths["review"])
    validation = load_artifact(source_paths["validation"])

    metrics = collect_metrics(implementation, review, validation, config)
    root_cause, fix = detect_root_cause(metrics)

    dry_run = not args.apply
    config_diff: dict[str, Any] | None = None
    applied = False
    if (
        fix.auto_apply_eligible
        and fix.config_target in ALLOWED_AUTO_APPLY_TARGETS
        and fix.value is not None
    ):
        try:
            if args.apply:
                applied, config_diff = apply_fix(args.config, fix, confirm=True)
            else:
                config_diff = preview_change(fix.config_target, fix.value, config_path=args.config)
        except Exception:
            applied = False

    artifact = build_optimization_artifact(
        metrics,
        root_cause,
        fix,
        source_paths=source_paths,
        applied=applied,
        dry_run=dry_run,
        config_diff=config_diff,
    )
    phase_run_id = metrics["phaseRunId"] if metrics["phaseRunId"] != "unknown" else utc_now_iso()
    safe_phase_run_id = str(phase_run_id).replace(":", "").replace("+", "").replace("Z", "")
    output = args.output or OPTIMIZATION_DIR / f"harness-issue-{issue}-{safe_phase_run_id}.json"
    write_json(output, artifact)
    print(f"wrote {output}")
    return 0


def evaluate(args: argparse.Namespace) -> int:
    before = load_json(args.before)
    after = load_json(args.after)
    result = evaluate_before_after(before, after)
    payload = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    propose_parser = subparsers.add_parser("propose", help="generate a harness optimization artifact")
    propose_parser.add_argument("--issue", type=int, required=False)
    propose_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    propose_parser.add_argument("--implementation", type=Path)
    propose_parser.add_argument("--review", type=Path)
    propose_parser.add_argument("--validation", type=Path)
    propose_parser.add_argument("--output", type=Path)
    propose_parser.add_argument(
        "--apply",
        action="store_true",
        help="apply eligible change via harness_config.py (default is dry-run preview only)",
    )
    propose_parser.set_defaults(func=propose)

    evaluate_parser = subparsers.add_parser("evaluate", help="compare before/after optimization artifacts")
    evaluate_parser.add_argument("--before", type=Path, required=True)
    evaluate_parser.add_argument("--after", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path)
    evaluate_parser.set_defaults(func=evaluate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except (OSError, ConfigError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
