"""Harness reproducibility pinning for sibling workflow-cache runs."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_SUFFIX = "/SKILL.md"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_rev_parse(ref: str, repo_root: Path) -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", ref],
            cwd=repo_root,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        raise RuntimeError(f"git rev-parse {ref!r} failed: {detail}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("git CLI not found; required for bootstrap pinning") from exc
    return output.strip()


def git_path_exists_at_commit(commit_sha: str, relative_path: str, repo_root: Path) -> bool:
    try:
        subprocess.check_output(
            ["git", "cat-file", "-e", f"{commit_sha}:{relative_path}"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def list_repo_paths_at_commit(
    commit_sha: str,
    source_paths: list[str],
    repo_root: Path,
) -> list[str]:
    paths: set[str] = set()
    for source_path in source_paths:
        normalized = source_path.strip("/")
        if not normalized:
            continue
        try:
            output = subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", commit_sha, "--", normalized],
                cwd=repo_root,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or str(exc)).strip()
            raise RuntimeError(
                f"git ls-tree at {commit_sha} for {normalized!r} failed: {detail}"
            ) from exc
        for line in output.splitlines():
            entry = line.strip()
            if entry:
                paths.add(entry)
    return sorted(paths)


def enumerate_bootstrap_skill_paths(
    commit_sha: str,
    source_paths: list[str],
    repo_root: Path,
) -> list[str]:
    """Skill paths available from bootstrap source dirs at a pinned commit."""
    skill_paths = [
        path
        for path in list_repo_paths_at_commit(commit_sha, source_paths, repo_root)
        if path.endswith("SKILL.md")
    ]
    return sorted(skill_paths)


def extract_harness_skill_paths(child_cache: dict[str, Any]) -> list[str]:
    harness = child_cache.get("harnessUtility") or {}
    skills = harness.get("skills") or []
    paths: list[str] = []
    for entry in skills:
        if isinstance(entry, dict):
            path = entry.get("path")
            if isinstance(path, str) and path.strip():
                paths.append(path.strip())
    return sorted(paths)


def normalize_skill_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def skill_path_exists_at_commit(
    commit_sha: str,
    skill_path: str,
    repo_root: Path,
) -> bool:
    relative = normalize_skill_path(skill_path)
    return git_path_exists_at_commit(commit_sha, relative, repo_root)


def bootstrap_ref_from_git(
    branch: str,
    repo_root: Path,
    *,
    copied_at: str | None = None,
) -> dict[str, str]:
    commit_sha = git_rev_parse(branch, repo_root)
    return {
        "branch": branch,
        "commitSha": commit_sha,
        "copiedAt": copied_at or utc_now_iso(),
    }


def validate_bootstrap_ref(
    parent_cache: dict[str, Any],
    child_cache: dict[str, Any],
    *,
    bootstrap_config: dict[str, Any],
    repo_root: Path,
) -> tuple[bool, str, dict[str, Any]]:
    bootstrap_ref = parent_cache.get("bootstrapRef")
    details: dict[str, Any] = {
        "bootstrapRef": bootstrap_ref,
        "harnessSkillPaths": extract_harness_skill_paths(child_cache),
    }

    if not isinstance(bootstrap_ref, dict):
        return False, "Parent cache missing bootstrapRef", details

    branch = bootstrap_ref.get("branch")
    commit_sha = bootstrap_ref.get("commitSha")
    copied_at = bootstrap_ref.get("copiedAt")
    missing = [
        field
        for field, value in (
            ("branch", branch),
            ("commitSha", commit_sha),
            ("copiedAt", copied_at),
        )
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        return False, f"bootstrapRef missing fields: {', '.join(missing)}", details

    branch = branch.strip()
    commit_sha = commit_sha.strip()
    source_paths = bootstrap_config.get("sourcePaths") or []
    if not source_paths:
        return False, "workflow_prompt_cache.bootstrap.sourcePaths is empty in config", details

    try:
        branch_head = git_rev_parse(branch, repo_root)
    except RuntimeError as exc:
        return False, str(exc), details

    details["branchHeadSha"] = branch_head
    details["pinnedCommitSha"] = commit_sha

    if branch_head != commit_sha:
        return (
            False,
            (
                f"Bootstrap branch {branch!r} HEAD ({branch_head[:12]}) "
                f"advanced past pinned bootstrapRef.commitSha ({commit_sha[:12]}). "
                "Cherry-pick/copy from the pinned SHA or bump bootstrapRef with Architect note."
            ),
            details,
        )

    harness_paths = extract_harness_skill_paths(child_cache)
    details["harnessSkillPaths"] = harness_paths

    missing_at_pin: list[str] = []
    for skill_path in harness_paths:
        if not skill_path_exists_at_commit(commit_sha, skill_path, repo_root):
            missing_at_pin.append(skill_path)

    if missing_at_pin:
        return (
            False,
            (
                "harnessUtility skill paths missing at pinned bootstrapRef.commitSha: "
                + ", ".join(missing_at_pin)
            ),
            details,
        )

    try:
        bootstrap_index = enumerate_bootstrap_skill_paths(commit_sha, source_paths, repo_root)
    except RuntimeError as exc:
        return False, str(exc), details

    details["bootstrapSkillIndex"] = bootstrap_index
    details["bootstrapSkillIndexSha"] = commit_sha

    return (
        True,
        (
            f"Bootstrap pinned to {commit_sha[:12]} on {branch}; "
            f"{len(harness_paths)} harnessUtility skill path(s) verified"
        ),
        details,
    )
