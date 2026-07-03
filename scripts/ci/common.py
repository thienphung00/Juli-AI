"""Shared utilities for CI generators and validate gates (stdlib only)."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_MAP = REPO_ROOT / "docs" / "architecture" / "map.md"
HANDOFFS_DIR = REPO_ROOT / "docs" / "handoffs"
DECISIONS_DIR = REPO_ROOT / "docs" / "decisions"
REVIEWS_DIR = REPO_ROOT / "artifacts" / "reviews"
VALIDATION_DIR = REPO_ROOT / "artifacts" / "validation"
IMPLEMENTATIONS_DIR = REPO_ROOT / "artifacts" / "implementations"
OPTIMIZATION_DIR = REPO_ROOT / "artifacts" / "optimization"
RELEASES_DIR = REPO_ROOT / "artifacts" / "releases"
RUNTIME_SCHEMA_VERSION = "1.0.0"
DONE_MD = REPO_ROOT / "done.md"

ISSUE_BRANCH_RE = re.compile(r"(?:feat|fix)/issue-(\d+)", re.IGNORECASE)
MODULE_ROW_RE = re.compile(
    r"\[`([^`]+)`]([^)]*MODULE\.md)?\s*\|\s*(\d+)\s*\|",
)
BACKTICK_SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
PUBLIC_SECTION_RE = re.compile(
    r"##\s+Public\s+Interface[s]?\s*\n(.*?)(?=\n##\s+|\Z)",
    re.DOTALL | re.IGNORECASE,
)
HANDOFF_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*-\d{2}\.md$", re.IGNORECASE)
ADR_FILE_RE = re.compile(r"^(\d{3})-([a-z0-9-]+)\.md$")
REQUIRED_ADR_SECTIONS = ("## Context", "## Decision", "## Rationale", "## Consequences")
BACKEND_MODULE_PREFIXES = ("backend/", "src/")


def _is_backend_module_path(module_path: str) -> bool:
    return any(module_path.startswith(prefix) for prefix in BACKEND_MODULE_PREFIXES)


@dataclass(frozen=True)
class ModuleInfo:
    path: str  # e.g. src/auth
    tier: int
    name: str  # short label from map, e.g. auth


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def deep_merge_under(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base; overlay values win at every level."""
    result = dict(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge_under(result[key], value)
        else:
            result[key] = value
    return result


def review_artifact_template(issue: int) -> dict[str, Any]:
    """ADR-003 review artifact skeleton with empty placeholders."""
    return {
        "id": f"review-issue-{issue}",
        "issue": issue,
        "timestamp": utc_now_iso(),
        "reviewedBy": "review skill",
        "status": "PASS",
        "summary": "",
        "criticalFindings": [],
        "modulesTouched": [],
        "interfaceChanges": [],
        "moduleDrift": False,
        "driftDetails": [],
        "testCoverage": {
            "acceptance": {
                "total": 0,
                "mapped": 0,
                "unmapped": [],
                "mappings": [],
            },
            "unit": {"passed": 0, "failed": 0},
        },
        "recommendations": [],
        "approvalReady": True,
        "reviewerSignoff": None,
        "ownerSignoff": None,
        "mlGates": None,
        "priorReviewBlockers": [],
    }


def build_review_artifact(
    issue: int,
    *,
    existing: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    fresh: bool = False,
    update_timestamp: bool = True,
) -> dict[str, Any]:
    """Assemble a review artifact without clobbering existing review content."""
    artifact = review_artifact_template(issue)
    if existing and not fresh:
        artifact = deep_merge_under(artifact, existing)
    if overrides:
        artifact = deep_merge_under(artifact, overrides)
    artifact["id"] = f"review-issue-{issue}"
    artifact["issue"] = issue
    if update_timestamp:
        artifact["timestamp"] = utc_now_iso()
    elif existing and existing.get("timestamp"):
        artifact["timestamp"] = existing["timestamp"]
    return finalize_review_artifact(artifact)


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--issue", type=int, help="GitHub issue number")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args()


def resolve_issue_number(explicit: int | None = None) -> int | None:
    if explicit is not None:
        return explicit
    env_issue = os.environ.get("ISSUE_NUMBER") or os.environ.get("GITHUB_ISSUE_NUMBER")
    if env_issue and env_issue.isdigit():
        return int(env_issue)
    branch = os.environ.get("GITHUB_HEAD_REF") or git_current_branch()
    if branch:
        match = ISSUE_BRANCH_RE.search(branch)
        if match:
            return int(match.group(1))
    return None


def git_current_branch() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_changed_files(base_ref: str | None = None) -> list[str]:
    """Return paths changed on this branch vs merge base (or working tree)."""
    try:
        if base_ref:
            cmd = ["git", "diff", "--name-only", f"{base_ref}...HEAD"]
        else:
            base = os.environ.get("GITHUB_BASE_REF")
            if base:
                subprocess.run(
                    ["git", "fetch", "origin", base, "--depth=1"],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                )
                cmd = ["git", "diff", "--name-only", f"origin/{base}...HEAD"]
            else:
                cmd = ["git", "diff", "--name-only", "HEAD"]
        out = subprocess.check_output(cmd, cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def parse_architecture_map(path: Path | None = None) -> dict[str, ModuleInfo]:
    path = path or ARCHITECTURE_MAP
    modules: dict[str, ModuleInfo] = {}
    if not path.exists():
        return modules
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = MODULE_ROW_RE.search(line)
        if not match:
            continue
        module_path, _, tier_str = match.groups()
        module_path = module_path.strip().rstrip("/")
        if not _is_backend_module_path(module_path):
            continue
        short = module_path.removeprefix("backend/").removeprefix("src/").split("/")[0]
        rel = module_path.removeprefix("backend/").removeprefix("src/")
        if "/" in rel:
            short = rel
        modules[module_path] = ModuleInfo(path=module_path, tier=int(tier_str), name=short)
    return modules


def module_for_file(file_path: str, modules: dict[str, ModuleInfo]) -> str | None:
    normalized = file_path.replace("\\", "/")
    if not _is_backend_module_path(normalized):
        return None
    candidates = sorted(modules.keys(), key=len, reverse=True)
    for module_path in candidates:
        if normalized == module_path or normalized.startswith(module_path + "/"):
            return module_path
    return None


def path_to_package(module_path: str) -> str:
    return module_path.replace("/", ".")


def parse_module_md_public_symbols(module_md: Path) -> set[str]:
    if not module_md.exists():
        return set()
    text = module_md.read_text(encoding="utf-8")
    section = PUBLIC_SECTION_RE.search(text)
    body = section.group(1) if section else text
    symbols: set[str] = set()
    for match in BACKTICK_SYMBOL_RE.finditer(body):
        symbols.add(match.group(1))
    return symbols


def ast_public_symbols(py_file: Path) -> set[str]:
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError:
        return set()
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            symbols.add(node.name)
        elif isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_"):
            symbols.add(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    if isinstance(node.value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Call)):
                        symbols.add(target.id)
    return symbols


def module_public_symbols_from_code(module_path: str) -> set[str]:
    root = REPO_ROOT / module_path
    if not root.exists():
        return set()
    symbols: set[str] = set()
    for py_file in root.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        symbols |= ast_public_symbols(py_file)
    return symbols


def normalize_label(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    return lowered.strip("_")


def criterion_matches_test(criterion: str, test_name: str) -> bool:
    c = normalize_label(criterion)
    t = normalize_label(test_name)
    if not c or not t:
        return False
    if c in t or t.endswith(c):
        return True
    tokens = [token for token in c.split("_") if len(token) > 3]
    if not tokens:
        return False
    # Require at least two token hits — blocks cosmetic single-token overlaps
    # (e.g. criterion "No TikTok API calls" vs test_has_no_tiktok).
    return sum(1 for token in tokens if token in t) >= 2


def parse_pytest_node(node_id: str) -> tuple[Path, str]:
    if "::" not in node_id:
        path = REPO_ROOT / node_id
        return path, ""
    file_part, test_name = node_id.rsplit("::", 1)
    return REPO_ROOT / file_part, test_name


JEST_TEST_CALL_RE = re.compile(
    r'\b(?:it|test)\s*\(\s*(["\'])(.+?)\1',
    re.DOTALL,
)


def jest_node_exists(node_id: str) -> bool:
    path, test_name = parse_pytest_node(node_id)
    if not path.exists() or path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        return False
    if not test_name:
        return True
    source = path.read_text(encoding="utf-8")
    return any(match.group(2) == test_name for match in JEST_TEST_CALL_RE.finditer(source))


def pytest_node_exists(node_id: str) -> bool:
    path, test_name = parse_pytest_node(node_id)
    if not path.exists():
        return False
    if path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
        return jest_node_exists(node_id)
    if not test_name:
        return True
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return False

    def _matches(node: ast.AST) -> bool:
        return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == test_name

    for node in tree.body:
        if _matches(node):
            return True
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if _matches(item):
                    return True
    return False


def review_artifact_path(issue: int) -> Path:
    return REVIEWS_DIR / f"review-issue-{issue}.json"


def validation_artifact_path(issue: int) -> Path:
    return VALIDATION_DIR / f"validation-issue-{issue}.json"


def load_review_artifact(issue: int) -> dict[str, Any] | None:
    path = review_artifact_path(issue)
    if not path.exists():
        return None
    return load_json(path)


def load_implementation_artifact(issue: int) -> dict[str, Any] | None:
    path = implementation_artifact_path(issue)
    if not path.exists():
        return None
    return load_json(path)


EXECUTOR_DOMAINS = frozenset({"ui-ux", "backend", "data-platform", "machine-learning"})


def default_phase_run_id() -> str:
    env = os.environ.get("PHASE_RUN_ID")
    if env:
        return env
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H%MZ")


def implementation_artifact_template(
    issue: int,
    executor_domain: str,
    *,
    phase_run_id: str | None = None,
) -> dict[str, Any]:
    """Executor Agent implementation artifact skeleton with empty placeholders."""
    if executor_domain not in EXECUTOR_DOMAINS:
        raise ValueError(f"invalid executorDomain: {executor_domain!r}")
    now = utc_now_iso()
    return {
        "schemaVersion": RUNTIME_SCHEMA_VERSION,
        "artifactType": "implementation",
        "issueId": issue,
        "executorDomain": executor_domain,
        "phaseRunId": phase_run_id or default_phase_run_id(),
        "startedAt": now,
        "completedAt": now,
        "executionDurationMs": 0,
        "tokenUsage": {"input": 0, "output": 0, "total": 0},
        "toolsUsed": [],
        "toolInvocationCount": 0,
        "contextFilesLoaded": [],
        "skillsLoaded": [],
        "filesModified": [],
        "testsAdded": [],
        "testsUpdated": [],
        "redGreenRefactorEvidence": [],
        "implementationSummary": "",
        "assumptions": [],
        "risks": [],
    }


def build_implementation_artifact(
    issue: int,
    executor_domain: str,
    *,
    existing: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    fresh: bool = False,
    phase_run_id: str | None = None,
) -> dict[str, Any]:
    """Assemble an implementation artifact without clobbering existing session evidence."""
    artifact = implementation_artifact_template(
        issue,
        executor_domain,
        phase_run_id=phase_run_id,
    )
    if existing and not fresh:
        artifact = deep_merge_under(artifact, existing)
    if overrides:
        artifact = deep_merge_under(artifact, overrides)
    artifact["issueId"] = issue
    artifact["executorDomain"] = executor_domain
    if phase_run_id:
        artifact["phaseRunId"] = phase_run_id
    elif existing and existing.get("phaseRunId"):
        artifact["phaseRunId"] = existing["phaseRunId"]
    artifact.setdefault("schemaVersion", RUNTIME_SCHEMA_VERSION)
    artifact.setdefault("artifactType", "implementation")
    token_usage = artifact.get("tokenUsage") or {}
    if isinstance(token_usage, dict):
        input_tokens = int(token_usage.get("input", 0))
        output_tokens = int(token_usage.get("output", 0))
        computed_total = input_tokens + output_tokens
        declared_total = token_usage.get("total")
        if declared_total is None or (computed_total > 0 and int(declared_total) < computed_total):
            token_usage["total"] = computed_total
        artifact["tokenUsage"] = token_usage
    return artifact


_LEGACY_WARNING_DOMAIN_TYPES = {
    "observability": "other",
    "reliability": "other",
    "maintainability": "maintainability",
    "security": "security",
    "architecture": "architecture",
    "performance": "other",
}


def legacy_warning_to_finding(warning: dict[str, Any]) -> dict[str, Any]:
    """Convert a legacy top-level ``warnings[]`` entry to ``criticalFindings`` shape."""
    severity = str(warning.get("severity", "WARNING")).upper()
    if severity not in {"CRITICAL", "WARNING", "INFO"}:
        severity = "WARNING"

    domain = str(warning.get("domain") or warning.get("category") or "").lower()
    finding_type = warning.get("type") or _LEGACY_WARNING_DOMAIN_TYPES.get(domain, "other")

    parts: list[str] = []
    if warning.get("location"):
        parts.append(str(warning["location"]))
    for key in ("message", "description"):
        if warning.get(key):
            parts.append(str(warning[key]))
    if warning.get("rationale"):
        parts.append(f"Rationale: {warning['rationale']}")

    finding: dict[str, Any] = {
        "type": finding_type,
        "severity": severity,
        "description": " — ".join(parts) if parts else "Legacy warning migrated from warnings[]",
    }
    if warning.get("module"):
        finding["module"] = warning["module"]
    if warning.get("actionRequired"):
        finding["actionRequired"] = True
    if warning.get("suggestion"):
        finding["suggestion"] = warning["suggestion"]
    return finding


def normalize_review_findings(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge ``criticalFindings`` with legacy ``warnings[]`` into one canonical list."""
    findings: list[dict[str, Any]] = list(artifact.get("criticalFindings") or [])
    legacy = artifact.get("warnings") or []
    if not legacy:
        return findings

    seen = {f.get("description") for f in findings if f.get("description")}
    for warning in legacy:
        converted = legacy_warning_to_finding(warning)
        description = converted.get("description")
        if description and description in seen:
            continue
        findings.append(converted)
        if description:
            seen.add(description)
    return findings


ML_MODULE_PREFIX = "backend/ai/"


def ml_modules_touched(modules: Iterable[str]) -> list[str]:
    """Return module paths under ``backend/ai/`` touched by the change."""
    touched: list[str] = []
    for module in modules:
        normalized = str(module).replace("\\", "/")
        if normalized == "backend/ai" or normalized.startswith(ML_MODULE_PREFIX):
            touched.append(normalized)
    return touched


def warning_findings(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f.get("severity") == "WARNING"]


def finding_is_acknowledged(finding: dict[str, Any]) -> bool:
    """A gating WARNING finding is mergeable only after explicit dual signoff."""
    if not finding.get("acceptanceByReviewer"):
        return False
    if not finding.get("ownerAck"):
        return False
    if finding.get("fixedInCommit"):
        return True
    return bool(finding.get("shipAsIsReason"))


def unacknowledged_findings(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in warning_findings(findings) if not finding_is_acknowledged(f)]


NON_OVERRIDABLE_FAIL_PREFIXES = (
    "CRITICAL security finding",
    "production data exposure",
)


def is_overridable_fail_reason(reason: str) -> bool:
    return not any(reason.startswith(prefix) for prefix in NON_OVERRIDABLE_FAIL_PREFIXES)


def overridden_merge_valid(artifact: dict[str, Any]) -> tuple[bool, str]:
    """Validate audited hotfix override metadata on a review artifact."""
    override = artifact.get("overriddenMerge")
    if not override:
        return False, ""
    required = ("timestamp", "overriddenBy", "reason", "incidentLink")
    missing = [field for field in required if not override.get(field)]
    if missing:
        return False, f"overriddenMerge missing: {', '.join(missing)}"
    return True, ""


def effective_mandatory_fail_reasons(artifact: dict[str, Any]) -> list[str]:
    """Mandatory fails after applying a valid audited override (hotfix path)."""
    reasons = mandatory_fail_reasons(artifact)
    if not overridden_merge_valid(artifact)[0]:
        return reasons
    return [reason for reason in reasons if not is_overridable_fail_reason(reason)]


def merge_override_active(artifact: dict[str, Any]) -> bool:
    """True when a valid override clears all overridable mandatory fail triggers."""
    if not overridden_merge_valid(artifact)[0]:
        return False
    return bool(mandatory_fail_reasons(artifact)) and not effective_mandatory_fail_reasons(artifact)


def ml_gates_satisfied(artifact: dict[str, Any]) -> tuple[bool, list[str]]:
    """ML-touched reviews must document cold-start handling and promotion gate."""
    touched = ml_modules_touched(artifact.get("modulesTouched") or [])
    if not touched:
        return True, []
    ml_gates = artifact.get("mlGates") or {}
    problems: list[str] = []
    if not ml_gates.get("coldStartThresholdDocumented"):
        problems.append("mlGates.coldStartThresholdDocumented required for ML modules")
    if not ml_gates.get("promotionGateDocumented"):
        problems.append("mlGates.promotionGateDocumented required for ML modules")

    from ml_thresholds import verify_ml_gates_threshold_values  # noqa: PLC0415

    scan_ok, scan_problems, _ = verify_ml_gates_threshold_values(touched, ml_gates)
    if not scan_ok:
        problems.extend(scan_problems)
    return len(problems) == 0, problems


def mandatory_fail_reasons(artifact: dict[str, Any]) -> list[str]:
    """Non-overridable FAIL triggers enforced before merge."""
    reasons: list[str] = []
    findings = normalize_review_findings(artifact)

    for finding in findings:
        if finding.get("type") == "security" and finding.get("severity") == "CRITICAL":
            reasons.append(
                "CRITICAL security finding (no override): "
                f"{finding.get('description', '')[:120]}"
            )
        if finding.get("type") in ("production_data_exposure", "data_exposure"):
            reasons.append(
                "production data exposure (no override): "
                f"{finding.get('description', '')[:120]}"
            )

    unit = artifact.get("testCoverage", {}).get("unit", {})
    failed = int(unit.get("failed", 0))
    if failed > 0:
        reasons.append(f"test regression: {failed} unit test(s) failed")

    acceptance = artifact.get("testCoverage", {}).get("acceptance", {})
    total = int(acceptance.get("total", 0))
    mapped = int(acceptance.get("mapped", 0))
    if total != mapped:
        reasons.append(f"incomplete acceptance criteria: mapped {mapped}/{total}")
    unmapped = acceptance.get("unmapped") or []
    if unmapped:
        reasons.append(f"unmapped acceptance criteria: {unmapped}")

    for blocker in artifact.get("priorReviewBlockers") or []:
        if not blocker.get("resolved"):
            label = blocker.get("description") or blocker.get("id") or "unknown"
            reasons.append(f"unresolved prior review blocker: {label}")

    ml_ok, ml_problems = ml_gates_satisfied(artifact)
    if not ml_ok:
        reasons.extend(ml_problems)

    return reasons


def warnings_require_signoff(artifact: dict[str, Any]) -> bool:
    """PASS_WITH_WARNINGS requires reviewer + owner signoff and per-finding ack."""
    return artifact.get("status") == "PASS_WITH_WARNINGS"


def reviewer_signoff_valid(artifact: dict[str, Any]) -> tuple[bool, str]:
    if not warnings_require_signoff(artifact):
        return True, ""
    signoff = artifact.get("reviewerSignoff") or {}
    if not signoff.get("statement"):
        return False, "reviewerSignoff.statement missing"
    if not signoff.get("timestamp"):
        return False, "reviewerSignoff.timestamp missing"
    if signoff.get("acceptedRisks") is not True:
        return False, "reviewerSignoff.acceptedRisks must be true"
    return True, ""


def owner_signoff_valid(artifact: dict[str, Any]) -> tuple[bool, str]:
    if not warnings_require_signoff(artifact):
        return True, ""
    signoff = artifact.get("ownerSignoff") or {}
    if not signoff.get("statement"):
        return False, "ownerSignoff.statement missing"
    if not signoff.get("timestamp"):
        return False, "ownerSignoff.timestamp missing"
    if signoff.get("acknowledged") is not True:
        return False, "ownerSignoff.acknowledged must be true"
    return True, ""


def derive_review_status(
    findings: Iterable[dict[str, Any]],
    artifact: dict[str, Any] | None = None,
) -> str:
    """Compute ADR-003 review status from normalized findings and artifact context."""
    if artifact is not None and mandatory_fail_reasons(artifact):
        return "FAIL"

    findings_list = list(findings)
    if any(f.get("severity") == "CRITICAL" for f in findings_list):
        return "FAIL"
    if any(f.get("actionRequired") for f in findings_list):
        return "FAIL"
    if any(f.get("severity") == "WARNING" for f in findings_list):
        return "PASS_WITH_WARNINGS"
    return "PASS"


def review_status_issues(artifact: dict[str, Any]) -> list[str]:
    """Return human-readable status/findings mismatches without mutating the artifact."""
    issues: list[str] = []
    legacy = artifact.get("warnings") or []
    if legacy:
        issues.append(
            f"legacy warnings[] has {len(legacy)} entr{'y' if len(legacy) == 1 else 'ies'}; "
            "migrate to criticalFindings and set status via generate_review_artifact.py"
        )

    findings = normalize_review_findings(artifact)
    derived = derive_review_status(findings, artifact)
    current = artifact.get("status")
    if current not in {"PASS", "PASS_WITH_WARNINGS", "FAIL"}:
        issues.append(f"invalid status: {current!r}")
    elif current != derived:
        warning_count = sum(1 for f in findings if f.get("severity") == "WARNING")
        critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        issues.append(
            f"status {current!r} does not match derived {derived!r} "
            f"(warnings={warning_count}, critical={critical_count})"
        )
    return issues


def normalize_review_artifact(
    artifact: dict[str, Any],
    *,
    fix_status: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Normalize findings and optionally align status. Returns (artifact, issues)."""
    artifact["criticalFindings"] = normalize_review_findings(artifact)
    if artifact.get("warnings"):
        artifact.pop("warnings", None)

    if fix_status:
        artifact["status"] = derive_review_status(artifact["criticalFindings"], artifact)
        return artifact, []

    return artifact, review_status_issues(artifact)


def finalize_review_artifact(
    artifact: dict[str, Any],
    *,
    phase_run_id: str | None = None,
    source_implementation: str | None = None,
) -> dict[str, Any]:
    """Normalize findings, align status, and add Meta fields."""
    normalize_review_artifact(artifact, fix_status=True)
    return enrich_review_artifact(
        artifact,
        phase_run_id=phase_run_id,
        source_implementation=source_implementation,
    )


def implementation_artifact_path(issue: int) -> Path:
    return IMPLEMENTATIONS_DIR / f"implementation-issue-{issue}.json"


def enrich_review_artifact(
    artifact: dict[str, Any],
    *,
    phase_run_id: str | None = None,
    source_implementation: str | None = None,
) -> dict[str, Any]:
    """Add Agent Runtime Meta fields; preserve ADR-003 CI gate fields."""
    findings = normalize_review_findings(artifact)
    artifact["criticalFindings"] = findings
    review_failures = sum(
        1
        for finding in findings
        if finding.get("severity") == "CRITICAL" or finding.get("actionRequired")
    )
    if any(f.get("severity") == "CRITICAL" for f in findings):
        aggregate_severity = "critical"
    elif any(f.get("severity") == "WARNING" for f in findings):
        aggregate_severity = "medium"
    elif findings:
        aggregate_severity = "low"
    else:
        aggregate_severity = "none"

    artifact["schemaVersion"] = RUNTIME_SCHEMA_VERSION
    artifact["artifactType"] = "review"
    artifact["reviewStatus"] = artifact.get("status")
    artifact["reviewFailures"] = review_failures
    artifact["findings"] = findings
    artifact["severity"] = aggregate_severity
    artifact["securityFindings"] = [
        f for f in findings if f.get("type") == "security"
    ]
    artifact["architectureFindings"] = [
        f
        for f in findings
        if f.get("type") in ("boundary_violation", "interface_change", "drift")
    ]
    artifact["maintainabilityFindings"] = [
        f for f in findings if f.get("type") in ("test_gap", "other", "drift")
    ]
    artifact["suggestedRemediation"] = [
        s for f in findings if (s := f.get("suggestion"))
    ]
    artifact.setdefault("staticAnalysisExecuted", True)
    unit = artifact.get("testCoverage", {}).get("unit", {})
    artifact.setdefault("dynamicTestsExecuted", bool(unit.get("passed") or unit.get("failed")))
    if phase_run_id:
        artifact["phaseRunId"] = phase_run_id
    if source_implementation:
        artifact["sourceImplementationArtifact"] = source_implementation
    impl_path = implementation_artifact_path(artifact.get("issue", 0))
    if source_implementation is None and impl_path.exists():
        artifact["sourceImplementationArtifact"] = impl_path.relative_to(REPO_ROOT).as_posix()
    return artifact


def enrich_validation_artifact(
    artifact: dict[str, Any],
    issue: int,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add Agent Runtime Meta fields; preserve ADR-003 CI gate fields."""
    failed = artifact.get("failedChecks", 0)
    unit = (review or {}).get("testCoverage", {}).get("unit", {})
    tests_passed = int(unit.get("passed", 0))
    tests_failed = int(unit.get("failed", 0))
    tests_executed = tests_passed + tests_failed
    review_status = (review or {}).get("status")
    warning_gated = review_status == "PASS_WITH_WARNINGS"

    artifact["schemaVersion"] = RUNTIME_SCHEMA_VERSION
    artifact["artifactType"] = "validation"
    artifact["sourceReviewArtifact"] = review_artifact_path(issue).relative_to(REPO_ROOT).as_posix()
    artifact["validationFailures"] = failed
    artifact["readyForShip"] = artifact.get("readyForMerge", False)
    artifact["warningGated"] = warning_gated
    artifact["retryCount"] = 0
    artifact["testsExecuted"] = tests_executed
    artifact["testsPassed"] = tests_passed
    artifact["testsFailed"] = tests_failed
    artifact.setdefault("coveragePercentage", 0)
    artifact.setdefault("benchmarkStatus", "not_run")
    artifact.setdefault("executionDurationMs", 0)
    if review and review.get("phaseRunId"):
        artifact["phaseRunId"] = review["phaseRunId"]
    return artifact


def tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])
        if lowlink[node] == indices[node]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == node:
                    break
            sccs.append(component)

    for vertex in graph:
        if vertex not in indices:
            strongconnect(vertex)
    return sccs


def collect_import_graph(modules: dict[str, ModuleInfo]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {m: set() for m in modules}
    for py_file in (REPO_ROOT / "src").rglob("*.py"):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        owner = module_for_file(rel, modules)
        if not owner:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = resolve_import_to_module(node.module, modules)
                if imported and imported != owner:
                    graph[owner].add(imported)
    return graph


def resolve_import_to_module(module_name: str, modules: dict[str, ModuleInfo]) -> str | None:
    dotted = module_name.replace(".", "/")
    candidates = sorted(modules.keys(), key=len, reverse=True)
    for module_path in candidates:
        pkg = path_to_package(module_path)
        if module_name == pkg or module_name.startswith(pkg + "."):
            return module_path
        if dotted.startswith(module_path):
            return module_path
    return None


def handoff_files_on_branch(changed: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for rel in changed:
        if not rel.startswith("docs/handoffs/"):
            continue
        name = Path(rel).name
        if name in {"_bootstrap.md", "parallel-status.md"}:
            continue
        if HANDOFF_FILE_RE.match(name):
            found.append(REPO_ROOT / rel)
    return found


def architectural_change_detected(review: dict[str, Any], changed: Iterable[str]) -> bool:
    for finding in review.get("criticalFindings", []):
        if finding.get("type") == "interface_change":
            return True
    for change in review.get("interfaceChanges", []):
        if change.get("breaking"):
            return True
    if any("docs/architecture/map.md" in c for c in changed):
        return True
    return False


def new_adr_files(changed: Iterable[str]) -> list[str]:
    adrs: list[str] = []
    for rel in changed:
        name = Path(rel).name
        if rel.startswith("docs/decisions/") and ADR_FILE_RE.match(name):
            adrs.append(rel)
    return adrs


def print_check_result(name: str, passed: bool, detail: str = "") -> int:
    status = "PASS" if passed else "FAIL"
    line = f"{name}: {status}"
    if detail:
        line += f" — {detail}"
    print(line)
    return 0 if passed else 1
