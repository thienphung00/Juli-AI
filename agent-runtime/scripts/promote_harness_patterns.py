#!/usr/bin/env python3
"""Scan harness optimization artifacts and emit promotion candidates.

Promotion moves recurring harness patterns from "recorded" to "reusable" by
proposing diffs to prompt-caching templates, issue context cache schemas, and
issueLoadProfile logic. All proposals require Architect approval — never
auto-edit skills or rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))

from build_runtime import load_simple_yaml, nested_get  # noqa: E402
from common import (  # noqa: E402
    OPTIMIZATION_DIR,
    REPO_ROOT,
    RUNTIME_SCHEMA_VERSION,
    load_json,
    utc_now_iso,
    write_json,
)


DEFAULT_CONFIG = REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml"
WORKFLOW_CACHE_DIR = REPO_ROOT / "agent-runtime" / "artifacts" / "workflow-cache"
PROMPT_CACHING_SKILL = REPO_ROOT / ".cursor/skills/standalone/prompt-caching/SKILL.md"
ISSUE_CONTEXT_CACHE_TEMPLATE = (
    REPO_ROOT / "agent-runtime/templates/issue-context-cache-template.json"
)
PARENT_CACHE_TEMPLATE = REPO_ROOT / "agent-runtime/templates/parent-cache-template.json"


@dataclass
class PromotionCandidate:
    trigger_type: str
    candidate_id: str
    source_issue_ids: list[int]
    detected_pattern: str
    root_cause_category: str | None
    proposed_changes: list[dict[str, Any]] = field(default_factory=list)
    evidence_artifacts: list[str] = field(default_factory=list)
    product_development_candidate: dict[str, Any] | None = None


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def artifact_rel_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def promotion_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("optimization", {}).get("promotion", {})


def context_deviation_threshold_pct(config: dict[str, Any]) -> float:
    return float(promotion_config(config).get("context_deviation_threshold_pct", 20))


def min_issues_for_recurring_root_cause(config: dict[str, Any]) -> int:
    return as_int(promotion_config(config).get("min_issues_for_recurring_root_cause"), 2)


def min_siblings_for_harness_utility(config: dict[str, Any]) -> int:
    return as_int(promotion_config(config).get("min_siblings_for_harness_utility"), 2)


def load_harness_artifacts(directory: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if not directory.exists():
        return artifacts
    for path in sorted(directory.glob("harness-issue-*.json")):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("artifactType") != "harness_optimization":
            continue
        payload["_sourcePath"] = artifact_rel_path(path)
        artifacts.append(payload)
    return artifacts


def load_issue_context_cache(issue_id: int) -> dict[str, Any] | None:
    path = WORKFLOW_CACHE_DIR / f"issue-context-cache-{issue_id}.json"
    if not path.exists():
        return None
    try:
        return load_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def expected_context_paths(issue_context_cache: dict[str, Any]) -> set[str]:
    profile = issue_context_cache.get("issueLoadProfile") or {}
    docs = profile.get("requiredDocs") or []
    modules = profile.get("requiredModules") or []
    return {str(item) for item in docs + modules}


def context_deviation_pct(actual: set[str], expected: set[str]) -> float:
    if not expected:
        return 100.0 if actual else 0.0
    symmetric_diff = len(actual.symmetric_difference(expected))
    return round((symmetric_diff / len(expected)) * 100, 2)


def harness_skill_paths(issue_context_cache: dict[str, Any]) -> set[str]:
    utility = issue_context_cache.get("harnessUtility") or {}
    skills = utility.get("skills") or []
    return {str(item.get("path", item)) for item in skills if item}


def build_context_budget_proposal(
    root_cause: str,
    issue_ids: list[int],
    config: dict[str, Any],
) -> dict[str, Any]:
    max_files = nested_get(config, "context.max_files", 25)
    if root_cause == "context_overloaded":
        proposed_value = max(5, int(max_files * 0.8))
        summary = f"Reduce context.max_files after repeated overload across issues {issue_ids}."
    else:
        proposed_value = min(50, max_files + 5)
        summary = f"Increase context.max_files after repeated underload across issues {issue_ids}."
    return {
        "targetId": "agent_runtime_context",
        "targetFile": "agent-runtime/config/agent-runtime.config.yml",
        "field": "context.max_files",
        "changeType": "context_budget",
        "summary": summary,
        "proposedValue": proposed_value,
        "autoApplyEligible": True,
        "humanApprovalRequired": True,
    }


def build_prompt_caching_proposal(summary: str, section_hint: str) -> dict[str, Any]:
    return {
        "targetId": "prompt_caching_skill",
        "targetFile": artifact_rel_path(PROMPT_CACHING_SKILL),
        "changeType": "documentation",
        "summary": summary,
        "sectionHint": section_hint,
        "proposedDiff": (
            f"--- a/{PROMPT_CACHING_SKILL.name}\n"
            f"+++ b/{PROMPT_CACHING_SKILL.name}\n"
            f"@@ Promotion candidate @@\n"
            f"+ {summary}\n"
        ),
        "autoApplyEligible": False,
        "humanApprovalRequired": True,
    }


def build_issue_context_cache_template_proposal(summary: str, fields: list[str]) -> dict[str, Any]:
    return {
        "targetId": "issue_context_cache_template",
        "targetFile": artifact_rel_path(ISSUE_CONTEXT_CACHE_TEMPLATE),
        "changeType": "template",
        "summary": summary,
        "proposedFields": fields,
        "proposedDiff": (
            f"--- a/{ISSUE_CONTEXT_CACHE_TEMPLATE.name}\n"
            f"+++ b/{ISSUE_CONTEXT_CACHE_TEMPLATE.name}\n"
            f"@@ issueLoadProfile @@\n"
            f"+ Update template fields: {', '.join(fields)}\n"
        ),
        "autoApplyEligible": False,
        "humanApprovalRequired": True,
    }


def build_parent_cache_template_proposal(summary: str) -> dict[str, Any]:
    return {
        "targetId": "parent_cache_template",
        "targetFile": artifact_rel_path(PARENT_CACHE_TEMPLATE),
        "changeType": "template",
        "summary": summary,
        "proposedDiff": (
            f"--- a/{PARENT_CACHE_TEMPLATE.name}\n"
            f"+++ b/{PARENT_CACHE_TEMPLATE.name}\n"
            f"@@ parentScopeBlock @@\n"
            f"+ {summary}\n"
        ),
        "autoApplyEligible": False,
        "humanApprovalRequired": True,
    }


def build_product_development_candidate(
    root_cause: str,
    issue_ids: list[int],
    evidence: list[str],
    detected_pattern: str,
) -> dict[str, Any]:
    slug = root_cause.replace("_", "-")
    candidate_id = f"product-development-recurring-{slug}-promotion"
    return {
        "emit": True,
        "id": candidate_id,
        "sourceIssueIds": issue_ids,
        "detectedPattern": detected_pattern,
        "rootCauseCategory": root_cause,
        "planningSignal": f"{len(issue_ids)} issues share rootCauseCategory={root_cause}.",
        "architectureSignal": "Repeated harness optimization signal — review context routing.",
        "decompositionSignal": "Consider tightening issueLoadProfile in issue context cache for affected siblings.",
        "reviewSignal": f"Evidence from harness artifacts: {', '.join(evidence[:3])}",
        "recommendedBacklogItem": {
            "title": f"Address recurring harness pattern: {root_cause}",
            "description": detected_pattern,
            "suggestedLabels": ["harness", "meta-agent", "prompt-caching"],
            "affectedModules": [
                ".cursor/skills/standalone/prompt-caching/SKILL.md",
                "agent-runtime/config/agent-runtime.config.yml",
                "agent-runtime/templates/issue-context-cache-template.json",
            ],
        },
        "requiresADR": False,
        "requiresPRDUpdate": False,
        "requiresIssueTemplateUpdate": False,
        "priority": "medium",
        "evidenceArtifacts": evidence,
        "acceptedByArchitect": "pending",
    }


def detect_context_deviation_candidates(
    harness_artifacts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[PromotionCandidate]:
    threshold = context_deviation_threshold_pct(config)
    candidates: list[PromotionCandidate] = []

    for artifact in harness_artifacts:
        issue_id = as_int(artifact.get("issueId"))
        if issue_id <= 0:
            continue
        issue_context_cache = load_issue_context_cache(issue_id)
        if issue_context_cache is None:
            continue

        expected = expected_context_paths(issue_context_cache)
        actual = {str(item) for item in artifact.get("contextFilesLoaded") or []}
        deviation = context_deviation_pct(actual, expected)
        if deviation <= threshold:
            continue

        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        pattern = (
            f"Issue #{issue_id} context plan deviates {deviation}% from issue context cache "
            f"issueLoadProfile (threshold {threshold}%). "
            f"Missing {len(missing)} expected paths; loaded {len(extra)} unexpected paths."
        )
        root_cause = str(artifact.get("rootCauseCategory") or "context_overloaded")
        changes = [
            build_issue_context_cache_template_proposal(
                f"Align issueLoadProfile for #{issue_id} with observed contextFilesLoaded.",
                ["requiredDocs", "requiredModules"],
            ),
            build_prompt_caching_proposal(
                f"Document context deviation gate (>={threshold}%) for issueLoadProfile alignment.",
                "Injection order (cache hit)",
            ),
        ]
        if root_cause in {"context_overloaded", "context_underloaded"}:
            changes.append(build_context_budget_proposal(root_cause, [issue_id], config))

        candidates.append(
            PromotionCandidate(
                trigger_type="context_deviation",
                candidate_id=f"promotion-candidate-context-deviation-issue-{issue_id}",
                source_issue_ids=[issue_id],
                detected_pattern=pattern,
                root_cause_category=root_cause,
                proposed_changes=changes,
                evidence_artifacts=[artifact["_sourcePath"]],
            )
        )
    return candidates


def detect_recurring_root_cause_candidates(
    harness_artifacts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[PromotionCandidate]:
    min_issues = min_issues_for_recurring_root_cause(config)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for artifact in harness_artifacts:
        root_cause = str(artifact.get("rootCauseCategory") or "")
        if not root_cause or root_cause == "none":
            continue
        grouped[root_cause].append(artifact)

    candidates: list[PromotionCandidate] = []
    for root_cause, group in grouped.items():
        issue_ids = sorted({as_int(item.get("issueId")) for item in group if as_int(item.get("issueId")) > 0})
        if len(issue_ids) < min_issues:
            continue

        evidence = [item["_sourcePath"] for item in group]
        pattern = (
            f"{len(issue_ids)} issues detected rootCauseCategory={root_cause} "
            f"in harness optimization artifacts."
        )
        changes: list[dict[str, Any]] = [
            build_prompt_caching_proposal(
                f"Add promotion guidance for recurring {root_cause} across sibling issues.",
                "Meta Agent — Harness Optimization (post-validation)",
            ),
        ]
        if root_cause in {"context_overloaded", "context_underloaded"}:
            changes.append(build_context_budget_proposal(root_cause, issue_ids, config))
        if root_cause == "wrong_executor_domain":
            changes.append(
                {
                    "targetId": "agent_runtime_routing",
                    "targetFile": "agent-runtime/config/agent-runtime.config.yml",
                    "field": "routing.backend_threshold",
                    "changeType": "routing_hint",
                    "summary": "Review executor routing thresholds after repeated wrong_executor_domain.",
                    "autoApplyEligible": True,
                    "humanApprovalRequired": True,
                }
            )

        slug = root_cause.replace("_", "-")
        candidates.append(
            PromotionCandidate(
                trigger_type="recurring_root_cause",
                candidate_id=f"promotion-candidate-recurring-{slug}",
                source_issue_ids=issue_ids,
                detected_pattern=pattern,
                root_cause_category=root_cause,
                proposed_changes=changes,
                evidence_artifacts=evidence,
                product_development_candidate=build_product_development_candidate(
                    root_cause,
                    issue_ids,
                    evidence,
                    pattern,
                ),
            )
        )
    return candidates


def detect_recurring_harness_utility_candidates(
    harness_artifacts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[PromotionCandidate]:
    min_siblings = min_siblings_for_harness_utility(config)
    by_parent: dict[int, list[tuple[int, set[str]]]] = defaultdict(list)

    for artifact in harness_artifacts:
        issue_id = as_int(artifact.get("issueId"))
        if issue_id <= 0:
            continue
        issue_context_cache = load_issue_context_cache(issue_id)
        if issue_context_cache is None:
            continue
        parent_id = as_int(issue_context_cache.get("parentIssueId"))
        if parent_id <= 0:
            continue
        skills = harness_skill_paths(issue_context_cache)
        if skills:
            by_parent[parent_id].append((issue_id, skills))

    candidates: list[PromotionCandidate] = []
    for parent_id, entries in by_parent.items():
        if len(entries) < min_siblings:
            continue
        shared_skills = set.intersection(*(skills for _, skills in entries))
        if not shared_skills:
            continue

        issue_ids = sorted(issue_id for issue_id, _ in entries)
        skill_list = sorted(shared_skills)
        pattern = (
            f"Parent #{parent_id} siblings {issue_ids} share harnessUtility skills: "
            f"{', '.join(skill_list)}."
        )
        changes = [
            build_issue_context_cache_template_proposal(
                f"Promote shared harnessUtility.skills for parent #{parent_id} siblings.",
                ["harnessUtility.skills"],
            ),
            build_parent_cache_template_proposal(
                f"Document shared harnessUtility baseline for parent #{parent_id} child issues.",
            ),
        ]
        evidence = [
            artifact["_sourcePath"]
            for artifact in harness_artifacts
            if as_int(artifact.get("issueId")) in issue_ids
        ]
        candidates.append(
            PromotionCandidate(
                trigger_type="recurring_harness_utility",
                candidate_id=f"promotion-candidate-harness-utility-parent-{parent_id}",
                source_issue_ids=issue_ids,
                detected_pattern=pattern,
                root_cause_category=None,
                proposed_changes=changes,
                evidence_artifacts=evidence,
            )
        )
    return candidates


def candidate_to_artifact(candidate: PromotionCandidate) -> dict[str, Any]:
    return {
        "schemaVersion": RUNTIME_SCHEMA_VERSION,
        "artifactType": "harness_promotion_candidate",
        "id": candidate.candidate_id,
        "triggerType": candidate.trigger_type,
        "sourceIssueIds": candidate.source_issue_ids,
        "detectedPattern": candidate.detected_pattern,
        "rootCauseCategory": candidate.root_cause_category,
        "proposedChanges": candidate.proposed_changes,
        "productDevelopmentCandidate": candidate.product_development_candidate,
        "evidenceArtifacts": candidate.evidence_artifacts,
        "appliedStatus": "proposed",
        "humanApprovalRequired": True,
        "createdAt": utc_now_iso(),
        "notes": (
            "Promotion proposals require Architect approval. "
            "Use harness_config.py apply with --approval-artifact for auto-apply-eligible YAML fields only."
        ),
    }


def scan_promotion_candidates(
    *,
    config: dict[str, Any],
    harness_dir: Path,
    issue_filter: int | None = None,
) -> list[PromotionCandidate]:
    artifacts = load_harness_artifacts(harness_dir)
    if issue_filter is not None:
        artifacts = [item for item in artifacts if as_int(item.get("issueId")) == issue_filter]

    candidates: list[PromotionCandidate] = []
    seen_ids: set[str] = set()

    for detector in (
        detect_recurring_root_cause_candidates,
        detect_context_deviation_candidates,
        detect_recurring_harness_utility_candidates,
    ):
        for candidate in detector(artifacts, config):
            if candidate.candidate_id in seen_ids:
                continue
            seen_ids.add(candidate.candidate_id)
            candidates.append(candidate)
    return candidates


def write_product_development_artifact(
    payload: dict[str, Any],
    *,
    output_dir: Path,
) -> Path | None:
    if not payload.get("emit"):
        return None
    product_payload = {
        "schemaVersion": RUNTIME_SCHEMA_VERSION,
        "artifactType": "product_development_optimization",
        **{key: value for key, value in payload.items() if key != "emit"},
        "createdAt": utc_now_iso(),
    }
    output = output_dir / f"{product_payload['id']}.json"
    write_json(output, product_payload)
    return output


def scan(args: argparse.Namespace) -> int:
    config = load_simple_yaml(args.config)
    harness_dir = args.harness_dir or OPTIMIZATION_DIR
    output_dir = args.output_dir or OPTIMIZATION_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = scan_promotion_candidates(
        config=config,
        harness_dir=harness_dir,
        issue_filter=args.issue,
    )
    if not candidates:
        print("no promotion candidates detected")
        return 0

    written: list[Path] = []
    for candidate in candidates:
        artifact = candidate_to_artifact(candidate)
        output = output_dir / f"{candidate.candidate_id}.json"
        write_json(output, artifact)
        written.append(output)
        print(f"wrote {output}")

        product = candidate.product_development_candidate
        if product and args.emit_product_dev:
            product_path = write_product_development_artifact(product, output_dir=output_dir)
            if product_path:
                print(f"wrote {product_path}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser("scan", help="scan harness artifacts for promotion candidates")
    scan_parser.add_argument("--harness-dir", type=Path, help="directory containing harness-issue-*.json")
    scan_parser.add_argument("--output-dir", type=Path, help="where to write promotion-candidate-*.json")
    scan_parser.add_argument("--issue", type=int, help="limit scan to artifacts for one issue")
    scan_parser.add_argument(
        "--emit-product-dev",
        action="store_true",
        help="also write product-development-optimization candidates when recurring root cause detected",
    )
    scan_parser.set_defaults(func=scan)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
