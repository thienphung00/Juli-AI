"""Bootstrap or refresh parent + child workflow prompt caches before Executor.

Meta Agent must call this (via ``check_workflow_cache.py --ensure`` or
``meta_prepare_executor.py``) so parent/child caches exist without a manual
prompt. Artifacts stay under ``agent-runtime/artifacts/workflow-cache/``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Callable

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(_SCRIPTS_DIR / "ci") not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR / "ci"))

from build_runtime import load_simple_yaml  # noqa: E402
from common import REPO_ROOT, utc_now_iso, write_json  # noqa: E402
from harness_bootstrap_pin import bootstrap_ref_from_git  # noqa: E402
from issue_load_profile import derive_issue_load_profile, load_slice_routing_rules  # noqa: E402
from scope_precedence import build_expected_authority_chain  # noqa: E402
from upstream_fingerprints import (  # noqa: E402
    build_child_upstream_fingerprints,
    build_parent_upstream_fingerprints,
    default_fetch_github_issue_body,
    default_fetch_github_issue_labels,
)
from public_release_classification import (  # noqa: E402
    classify_public_release,
    paths_from_issue_load_profile,
)
from workflow_cache_store import (  # noqa: E402
    artifacts_dir_from_config,
    child_cache_path,
    parent_cache_path,
    scope_alignment_path,
)

DEFAULT_CONFIG = REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml"

PARENT_LINE_RE = re.compile(
    r"(?im)^(?:##\s*Parent\s*\n+\s*#?|#?\s*Parent\s*[:#]\s*|Part of\s+#?)(\d+)\b"
)
SLICE_LINE_RE = re.compile(
    r"(?im)^(?:Slice|sliceId|focusSlice|Focus slice)\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*$"
)

DOMAIN_SKILL_PATHS: dict[str, str] = {
    "backend": ".cursor/skills/domain/backend/SKILL.md",
    "ui-ux": ".cursor/skills/domain/ui-ux/SKILL.md",
    "data-platform": ".cursor/skills/domain/data-platform/SKILL.md",
    "machine-learning": ".cursor/skills/domain/machine-learning/SKILL.md",
    "integrations": ".cursor/skills/domain/integrations/SKILL.md",
}

DEFAULT_TOOLS = ["Read", "Grep", "Glob", "Shell", "StrReplace"]


def load_runtime_config(repo_root: Path, config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or (repo_root / "agent-runtime" / "config" / "agent-runtime.config.yml")
    return load_simple_yaml(path)


def fetch_issue_body(issue_id: int, repo_root: Path) -> str:
    return default_fetch_github_issue_body(issue_id, repo_root)


def parse_parent_issue_id(issue_body: str) -> int | None:
    match = PARENT_LINE_RE.search(issue_body or "")
    if not match:
        return None
    return int(match.group(1))


def parse_slice_id(issue_body: str) -> str | None:
    match = SLICE_LINE_RE.search(issue_body or "")
    if not match:
        return None
    return match.group(1).strip()


def _unescape_scope(text: str) -> str:
    return text.replace("\\n", "\n").replace("\\t", "\t")


def epic_registry_entry(config: dict[str, Any], parent_issue_id: int) -> dict[str, Any]:
    registry = (config.get("workflow_prompt_cache") or {}).get("epicRegistry") or {}
    entry = (
        registry.get(parent_issue_id)
        or registry.get(str(parent_issue_id))
        or registry.get(f'"{parent_issue_id}"')
        or {}
    )
    if not isinstance(entry, dict):
        return {}
    out = dict(entry)
    scope = out.get("parentScopeBlock")
    if isinstance(scope, str):
        out["parentScopeBlock"] = _unescape_scope(scope)
    return out


def resolve_linkage(
    *,
    issue_id: int,
    issue_body: str,
    config: dict[str, Any],
    parent_issue_id: int | None = None,
    slice_id: str | None = None,
    handoff_path: str | None = None,
) -> dict[str, Any]:
    resolved_parent = parent_issue_id or parse_parent_issue_id(issue_body)
    if resolved_parent is None:
        raise ValueError(
            f"Cannot resolve parent for issue #{issue_id}. Pass --parent or add "
            "`## Parent\\n#P` / `Parent: #P` to the issue body."
        )

    epic = epic_registry_entry(config, resolved_parent)
    child_slices = epic.get("childSlices") or {}
    registry_child_slice = (
        child_slices.get(issue_id)
        or child_slices.get(str(issue_id))
        or child_slices.get(f'"{issue_id}"')
    )
    resolved_slice = (
        slice_id
        or parse_slice_id(issue_body)
        or registry_child_slice
        or epic.get("sliceId")
        or epic.get("defaultSliceId")
    )
    if not resolved_slice:
        raise ValueError(
            f"Cannot resolve sliceId for issue #{issue_id} (parent #{resolved_parent}). "
            "Pass --slice-id or register the epic in "
            "workflow_prompt_cache.epicRegistry."
        )

    resolved_handoff = (
        handoff_path
        or epic.get("handoffPath")
        or f"docs/handoffs/issue-{resolved_parent}.md"
    )
    parent_scope = epic.get("parentScopeBlock") or (
        f"# Parent #{resolved_parent}\n\n"
        f"## Slice\n- Default slice: {resolved_slice}\n"
        f"## Handoff\n- {resolved_handoff}\n"
    )
    do_not_load = list(epic.get("doNotLoad") or [
        "docs/handoffs/archive/",
        "docs/product/features/",
        "Sibling issue context caches",
    ])
    return {
        "parentIssueId": resolved_parent,
        "sliceId": resolved_slice,
        "handoffPath": resolved_handoff,
        "parentScopeBlock": parent_scope,
        "doNotLoad": do_not_load,
    }


def single_domain_harness_utility(executor_domain: str) -> dict[str, Any]:
    """One primary executor domain skill — never dual backend+data-platform."""
    skill_path = DOMAIN_SKILL_PATHS.get(executor_domain)
    skills: list[dict[str, str]] = []
    if skill_path:
        skills.append(
            {
                "path": skill_path,
                "purpose": f"Primary {executor_domain} Executor TDD",
            }
        )
    return {
        "skills": skills,
        "rulesTier2": [
            ".cursor/rules/code-quality.mdc",
            ".cursor/rules/reliability.mdc",
        ],
        "mcps": [],
        "tools": list(DEFAULT_TOOLS),
    }


def write_scope_alignment_stub(
    *,
    issue_id: int,
    path: Path,
    slice_id: str,
    parent_issue_id: int,
    in_scope: list[str],
    out_of_scope: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        [
            f"# Scope alignment — Issue #{issue_id}",
            "",
            f"- Parent: #{parent_issue_id}",
            f"- Slice: `{slice_id}`",
            f"- EnsuredAt: {utc_now_iso()}",
            "",
            "## In scope",
            *[f"- {item}" for item in (in_scope or ["Derived from slice-routing + issue AC"])],
            "",
            "## Out of scope",
            *[f"- {item}" for item in (out_of_scope or ["Sibling issues", "Unrelated modules"])],
            "",
            "## Notes",
            "- Auto-generated by `ensure_workflow_cache` for Meta → Executor gate.",
            "- Refine via grill-with-docs when Architect rescopes.",
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")


def ensure_parent_cache(
    *,
    linkage: dict[str, Any],
    repo_root: Path,
    config: dict[str, Any],
    issue_body_fetcher: Callable[[int], str],
    force: bool = False,
) -> tuple[dict[str, Any], Path, bool]:
    """Return (parent_cache, path, created_or_refreshed)."""
    parent_id = linkage["parentIssueId"]
    artifacts_dir = artifacts_dir_from_config(config, repo_root)
    path = parent_cache_path(parent_id, repo_root, artifacts_dir=artifacts_dir)
    created = False
    if path.exists() and not force:
        from common import load_json

        parent_cache = load_json(path)
    else:
        created = True
        bootstrap_branch = (
            (config.get("workflow_prompt_cache") or {})
            .get("bootstrap", {})
            .get("pinBranch")
            or "HEAD"
        )
        parent_cache = {
            "schemaVersion": "1.0.0",
            "artifactType": "parent_cache",
            "parentIssueId": parent_id,
            "cacheBlockVersion": 1,
            "parentScopeBlock": linkage["parentScopeBlock"],
            "sliceId": linkage["sliceId"],
            "handoffPath": linkage["handoffPath"],
            "childIssueIds": [],
            "doNotLoad": linkage["doNotLoad"],
            "upstreamFingerprints": [],
            "bootstrapRef": bootstrap_ref_from_git(bootstrap_branch, repo_root),
            "lastValidatedAt": utc_now_iso(),
        }

    # Always refresh fingerprints + bootstrap pin to current HEAD so gates pass.
    bootstrap_branch = (
        (config.get("workflow_prompt_cache") or {})
        .get("bootstrap", {})
        .get("pinBranch")
        or parent_cache.get("bootstrapRef", {}).get("branch")
        or "HEAD"
    )
    parent_cache["bootstrapRef"] = bootstrap_ref_from_git(bootstrap_branch, repo_root)
    # Keep epic defaultSliceId on parent; per-child slices live in child parentLinkage.
    # Only set parent.sliceId when creating or when still empty — do not clobber with
    # a sibling child's unique slice (breaks multi-slice epics like Phase 2.9).
    if created or force or not parent_cache.get("sliceId"):
        parent_cache["sliceId"] = linkage["sliceId"]
    parent_cache["handoffPath"] = linkage["handoffPath"]
    if linkage.get("parentScopeBlock") and (
        created or force or not parent_cache.get("parentScopeBlock")
    ):
        parent_cache["parentScopeBlock"] = linkage["parentScopeBlock"]
    parent_cache["doNotLoad"] = list(
        dict.fromkeys(list(parent_cache.get("doNotLoad") or []) + linkage["doNotLoad"])
    )
    parent_cache["upstreamFingerprints"] = build_parent_upstream_fingerprints(
        parent_issue_id=parent_id,
        handoff_path=linkage["handoffPath"],
        slice_id=linkage["sliceId"],
        repo_root=repo_root,
        issue_body_fetcher=issue_body_fetcher,
    )
    parent_cache["lastValidatedAt"] = utc_now_iso()
    write_json(path, parent_cache)
    return parent_cache, path, created or force


def ensure_child_cache(
    *,
    issue_id: int,
    issue_body: str,
    linkage: dict[str, Any],
    parent_cache: dict[str, Any],
    repo_root: Path,
    config: dict[str, Any],
    issue_body_fetcher: Callable[[int], str],
    issue_labels: list[str] | None = None,
    force: bool = False,
    mark_valid: bool = True,
) -> tuple[dict[str, Any], Path, bool]:
    artifacts_dir = artifacts_dir_from_config(config, repo_root)
    path = child_cache_path(issue_id, repo_root, artifacts_dir=artifacts_dir)
    scope_path = scope_alignment_path(issue_id, repo_root, artifacts_dir=artifacts_dir)
    parent_id = linkage["parentIssueId"]
    parent_rel = parent_cache_path(
        parent_id, repo_root, artifacts_dir=artifacts_dir
    ).relative_to(repo_root).as_posix()

    profile = derive_issue_load_profile(
        slice_id=linkage["sliceId"],
        issue_body=issue_body,
        handoff_path=linkage["handoffPath"],
        rules=load_slice_routing_rules(),
    )
    executor_domain = profile["executorDomain"]
    do_not_load = _dedupe(
        list(profile.get("doNotLoad") or []) + list(parent_cache.get("doNotLoad") or [])
    )

    created = not path.exists()
    if path.exists() and not force:
        from common import load_json

        child_cache = load_json(path)
    else:
        child_cache = {
            "schemaVersion": "1.2.0",
            "artifactType": "issue_context_cache",
            "issueId": issue_id,
            "parentIssueId": parent_id,
            "parentCachePath": parent_rel,
            "phaseRunId": f"{issue_id}-{utc_now_iso().replace(':', '').replace('-', '')[:15]}",
            "workflowPhase": "meta",
            "cacheStatus": "partial",
            "cacheBlockVersion": 1,
            "parentLinkage": {
                "sliceId": linkage["sliceId"],
                "handoffPath": linkage["handoffPath"],
            },
            "issueLoadProfile": {},
            "authorityChain": [],
            "resolvedDecisions": [],
            "inScope": [],
            "outOfScope": [],
            "doNotLoad": do_not_load,
            "promptCacheBlock": "",
            "phaseCacheBlocks": {
                "scope": "",
                "meta": "",
                "executor": "",
                "review": "",
                "validate": "",
            },
            "harnessUtility": single_domain_harness_utility(executor_domain),
            "glossarySnippets": [],
            "openQuestions": [],
            "upstreamFingerprints": [],
            "scopeAlignmentPath": scope_path.relative_to(repo_root).as_posix(),
            "lastValidatedAt": utc_now_iso(),
            "lastScopeAlignmentAt": utc_now_iso(),
        }

    # Keep linkage + derived profile authoritative.
    child_cache["parentIssueId"] = parent_id
    child_cache["parentCachePath"] = parent_rel
    child_cache["parentLinkage"] = {
        "sliceId": linkage["sliceId"],
        "handoffPath": linkage["handoffPath"],
    }
    existing_plan = (child_cache.get("issueLoadProfile") or {}).get("releaseEvidencePlan")
    child_cache["issueLoadProfile"] = {
        "executorDomain": executor_domain,
        "requiredDocs": profile.get("requiredDocs") or [],
        "requiredModules": profile.get("requiredModules") or [],
        "acceptanceCriteria": profile.get("acceptanceCriteria") or [],
        "loadWhenNeeded": profile.get("loadWhenNeeded") or [],
    }
    if existing_plan is not None:
        child_cache["issueLoadProfile"]["releaseEvidencePlan"] = existing_plan

    classification = classify_public_release(
        paths=paths_from_issue_load_profile(profile),
        issue_body=issue_body,
        labels=list(issue_labels or []),
    )
    child_cache["publicRelease"] = classification["publicRelease"]
    child_cache["publicReleaseReasons"] = classification["publicReleaseReasons"]
    child_cache["doNotLoad"] = do_not_load
    child_cache["authorityChain"] = build_expected_authority_chain(
        parent_issue_id=parent_id,
        child_issue_id=issue_id,
        handoff_path=linkage["handoffPath"],
        slice_id=linkage["sliceId"],
    )
    # Strip optional sliceId key from authority entries if schema is strict —
    # build_expected includes sliceId; schema allows additional props? authority
    # items only allow rank/source/reason. Normalize.
    child_cache["authorityChain"] = [
        {
            "rank": entry["rank"],
            "source": entry["source"],
            "reason": entry["reason"],
        }
        for entry in child_cache["authorityChain"]
    ]

    in_scope = child_cache.get("inScope") or [
        f"Slice {linkage['sliceId']} acceptance criteria",
        f"Executor domain: {executor_domain}",
    ]
    out_of_scope = child_cache.get("outOfScope") or list(do_not_load[:5])
    child_cache["inScope"] = in_scope
    child_cache["outOfScope"] = out_of_scope

    prompt = (
        f"# Issue #{issue_id} — {linkage['sliceId']}\n\n"
        f"## Parent\n#{parent_id}\n\n"
        f"## Executor domain\n{executor_domain}\n\n"
        f"## Required docs\n"
        + "\n".join(f"- {p}" for p in (profile.get("requiredDocs") or [])[:12])
        + "\n"
    )
    child_cache["promptCacheBlock"] = prompt
    phase_blocks = child_cache.get("phaseCacheBlocks") or {}
    phase_blocks["scope"] = prompt
    phase_blocks["meta"] = (
        f"# Meta — Issue #{issue_id}\n\n"
        f"- sliceId: {linkage['sliceId']}\n"
        f"- executorDomain: {executor_domain} (single primary)\n"
        f"- Ensure: workflow cache auto-bootstrapped; Executor blocked until valid.\n"
        f"- Skills: primary domain only; Review/Validate skills load in their phases.\n"
    )
    phase_blocks.setdefault("executor", f"# Executor — Issue #{issue_id}\n")
    phase_blocks.setdefault("review", f"# Review — Issue #{issue_id}\n")
    phase_blocks.setdefault("validate", f"# Validate — Issue #{issue_id}\n")
    child_cache["phaseCacheBlocks"] = phase_blocks

    # Enforce single primary skill (do not dual-load backend + data-platform).
    existing_harness = child_cache.get("harnessUtility") or {}
    if force or created or not (existing_harness.get("skills") or []):
        child_cache["harnessUtility"] = single_domain_harness_utility(executor_domain)
    else:
        # Keep Meta enrichments but collapse to one domain skill if two domains present.
        skills = existing_harness.get("skills") or []
        domain_skills = [
            s
            for s in skills
            if isinstance(s, dict)
            and any(
                s.get("path", "").endswith(f"/domain/{d}/SKILL.md")
                for d in DOMAIN_SKILL_PATHS
            )
        ]
        if len(domain_skills) > 1:
            child_cache["harnessUtility"] = single_domain_harness_utility(executor_domain)
            child_cache["harnessUtility"]["rulesTier2"] = existing_harness.get(
                "rulesTier2"
            ) or child_cache["harnessUtility"]["rulesTier2"]
            child_cache["harnessUtility"]["tools"] = existing_harness.get("tools") or DEFAULT_TOOLS
        else:
            child_cache["harnessUtility"] = existing_harness

    write_scope_alignment_stub(
        issue_id=issue_id,
        path=scope_path,
        slice_id=linkage["sliceId"],
        parent_issue_id=parent_id,
        in_scope=in_scope,
        out_of_scope=out_of_scope,
    )
    child_cache["scopeAlignmentPath"] = scope_path.relative_to(repo_root).as_posix()
    child_cache["upstreamFingerprints"] = build_child_upstream_fingerprints(
        issue_id=issue_id,
        scope_alignment_path=child_cache["scopeAlignmentPath"],
        repo_root=repo_root,
        issue_body_fetcher=issue_body_fetcher,
    )
    child_cache["workflowPhase"] = "meta"
    child_cache["cacheStatus"] = "valid" if mark_valid else "partial"
    child_cache["lastValidatedAt"] = utc_now_iso()
    child_cache["lastScopeAlignmentAt"] = utc_now_iso()
    write_json(path, child_cache)

    # Append child to parent.childIssueIds
    children = list(parent_cache.get("childIssueIds") or [])
    if issue_id not in children:
        children.append(issue_id)
        parent_cache["childIssueIds"] = children
        write_json(
            parent_cache_path(parent_id, repo_root, artifacts_dir=artifacts_dir),
            parent_cache,
        )

    return child_cache, path, created or force


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def ensure_workflow_caches(
    issue_id: int,
    *,
    repo_root: Path = REPO_ROOT,
    config: dict[str, Any] | None = None,
    parent_issue_id: int | None = None,
    slice_id: str | None = None,
    handoff_path: str | None = None,
    force: bool = False,
    mark_valid: bool = True,
    issue_body_fetcher: Callable[[int], str] | None = None,
    issue_labels_fetcher: Callable[[int], list[str]] | None = None,
) -> dict[str, Any]:
    """Ensure parent + child caches exist and are gate-ready.

    Returns a summary dict for Meta / CLI.
    """
    cfg = config or load_runtime_config(repo_root)
    fetcher = issue_body_fetcher or (lambda iid: fetch_issue_body(iid, repo_root))
    labels_fetcher = issue_labels_fetcher or (
        lambda iid: default_fetch_github_issue_labels(iid, repo_root)
    )
    issue_body = fetcher(issue_id)
    issue_labels = list(labels_fetcher(issue_id) or [])
    linkage = resolve_linkage(
        issue_id=issue_id,
        issue_body=issue_body,
        config=cfg,
        parent_issue_id=parent_issue_id,
        slice_id=slice_id,
        handoff_path=handoff_path,
    )
    parent_cache, parent_path, parent_created = ensure_parent_cache(
        linkage=linkage,
        repo_root=repo_root,
        config=cfg,
        issue_body_fetcher=fetcher,
        force=force,
    )
    child_cache, child_path, child_created = ensure_child_cache(
        issue_id=issue_id,
        issue_body=issue_body,
        linkage=linkage,
        parent_cache=parent_cache,
        repo_root=repo_root,
        config=cfg,
        issue_body_fetcher=fetcher,
        issue_labels=issue_labels,
        force=force,
        mark_valid=mark_valid,
    )
    return {
        "issueId": issue_id,
        "parentIssueId": linkage["parentIssueId"],
        "sliceId": linkage["sliceId"],
        "handoffPath": linkage["handoffPath"],
        "executorDomain": (child_cache.get("issueLoadProfile") or {}).get("executorDomain"),
        "cacheStatus": child_cache.get("cacheStatus"),
        "parentCachePath": parent_path.relative_to(repo_root).as_posix(),
        "childCachePath": child_path.relative_to(repo_root).as_posix(),
        "parentCreatedOrRefreshed": parent_created,
        "childCreatedOrRefreshed": child_created,
        "readyForExecutor": child_cache.get("cacheStatus") == "valid",
    }
