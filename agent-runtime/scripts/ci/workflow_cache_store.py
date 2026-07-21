"""Shared loader for workflow prompt cache artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common import load_json

DEFAULT_ARTIFACTS_REL = Path("agent-runtime/artifacts/workflow-cache")
CHILD_CACHE_PREFIX = "issue-context-cache"
PARENT_CACHE_PREFIX = "parent-cache-issue"


def artifacts_dir_from_config(config: dict[str, Any] | None, repo_root: Path) -> Path:
    if config:
        rel = (config.get("workflow_prompt_cache") or {}).get("artifactsDir")
        if isinstance(rel, str) and rel.strip():
            return repo_root / rel.strip()
    return repo_root / DEFAULT_ARTIFACTS_REL


def child_cache_path(
    issue: int,
    repo_root: Path,
    *,
    artifacts_dir: Path | None = None,
) -> Path:
    base = artifacts_dir or (repo_root / DEFAULT_ARTIFACTS_REL)
    return base / f"{CHILD_CACHE_PREFIX}-{issue}.json"


def parent_cache_path(
    parent_issue_id: int,
    repo_root: Path,
    *,
    artifacts_dir: Path | None = None,
) -> Path:
    base = artifacts_dir or (repo_root / DEFAULT_ARTIFACTS_REL)
    return base / f"{PARENT_CACHE_PREFIX}-{parent_issue_id}.json"


def scope_alignment_path(issue: int, repo_root: Path, *, artifacts_dir: Path | None = None) -> Path:
    base = artifacts_dir or (repo_root / DEFAULT_ARTIFACTS_REL)
    return base / f"scope-alignment-issue-{issue}.md"


def load_child_cache(
    issue: int,
    repo_root: Path,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, Path, str | None]:
    """Return (child_cache, child_path, error_message)."""
    artifacts_dir = artifacts_dir_from_config(config, repo_root)
    path = child_cache_path(issue, repo_root, artifacts_dir=artifacts_dir)
    if not path.exists():
        rel = path.relative_to(repo_root)
        return None, path, f"Child issue context cache missing: {rel.as_posix()}"

    child_cache = load_json(path)
    if child_cache.get("issueId") != issue:
        return None, path, f"Child cache issueId mismatch: expected {issue}"

    return child_cache, path, None


def load_parent_child_caches(
    issue: int,
    repo_root: Path,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Path, Path, str | None]:
    """Return (child_cache, parent_cache, child_path, parent_path, error_message)."""
    child_cache, child_path, child_error = load_child_cache(issue, repo_root, config=config)
    if child_error:
        return None, None, child_path, child_path, child_error

    parent_issue_id = child_cache.get("parentIssueId")
    if not isinstance(parent_issue_id, int):
        return child_cache, None, child_path, child_path, "Child cache missing parentIssueId"

    artifacts_dir = artifacts_dir_from_config(config, repo_root)
    parent_rel = child_cache.get("parentCachePath")
    if isinstance(parent_rel, str) and parent_rel.strip():
        parent_path = repo_root / parent_rel.strip()
    else:
        parent_path = parent_cache_path(parent_issue_id, repo_root, artifacts_dir=artifacts_dir)

    if not parent_path.exists():
        rel = parent_path.relative_to(repo_root)
        return (
            child_cache,
            None,
            child_path,
            parent_path,
            f"Parent cache missing: {rel.as_posix()}",
        )

    parent_cache = load_json(parent_path)
    if parent_cache.get("parentIssueId") != parent_issue_id:
        return (
            child_cache,
            parent_cache,
            child_path,
            parent_path,
            f"Parent cache parentIssueId mismatch: expected {parent_issue_id}",
        )

    return child_cache, parent_cache, child_path, parent_path, None
