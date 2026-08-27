"""Shared rules for the executor cache gate (#1384).

Two gates enforce the same policy at different moments, so the policy lives
here once rather than being written twice and drifting:

- `executor_cache_gate.py` — `PreToolUse`, fast feedback, blocks the edit
  before it happens. Only sees the file-editing tools.
- `executor_cache_precommit.py` — pre-commit, inspects the staged diff. Sees
  every change regardless of how it was written.

The second exists because the first is bypassable: it is registered on
`Edit|Write|MultiEdit|NotebookEdit`, so any shell write (`sed -i`, a heredoc,
`cat >`, `tee`, a script) never triggers it. That is the path of least
resistance for mechanical bulk edits, so it gets crossed by accident, not just
deliberately. Checking the *result* instead of the *action* cannot be
sidestepped by the write mechanism.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

DEFAULT_ISSUE_BRANCH_PATTERN = r"issue-([0-9]+)"
CONFIG_REL = Path("agent-runtime/config/agent-runtime.config.yml")
CACHE_REL = Path("agent-runtime/artifacts/workflow-cache")

# Product code. Everything else (docs/, .cursor/, .claude/, agent-runtime/)
# stays editable so Architect and Meta can do their jobs before a cache exists.
GUARDED_ROOTS = ("backend/", "apps/", "packages/", "ios/", "infra/", "tests/", "web/")


def git(repo: Path, *args: str) -> str:
    """Empty string on any failure or hang — a gate that wedges on a slow git
    would block every edit, which is worse than the policy it enforces."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def issue_branch_pattern(repo: Path) -> str:
    cfg = repo / CONFIG_REL
    if cfg.is_file():
        m = re.search(r'^\s*issueBranchPattern:\s*"?([^"\n]+)"?\s*$', cfg.read_text(), re.M)
        if m:
            return m.group(1)
    return DEFAULT_ISSUE_BRANCH_PATTERN


def resolve_issue(repo: Path) -> str | None:
    """The issue this branch is doing work for, or None for scratch/quick-commit
    branches (mirroring `artifact_gates.quickCommitSkip`; CI skips artifact
    gates on those too)."""
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    m = re.search(issue_branch_pattern(repo), branch)
    return m.group(1) if m else None


def is_guarded(rel_posix: str) -> bool:
    return rel_posix.startswith(GUARDED_ROOTS)


def cache_problem(repo: Path, issue: str) -> str | None:
    """None when a valid workflow cache exists; otherwise why not."""
    cache = repo / CACHE_REL / f"issue-context-cache-{issue}.json"
    if not cache.is_file():
        return f"no workflow cache at {cache.relative_to(repo)}"
    try:
        if json.loads(cache.read_text()).get("cacheStatus") == "valid":
            return None
        return f"cacheStatus is not 'valid' in {cache.relative_to(repo)}"
    except (OSError, json.JSONDecodeError) as exc:
        return f"{cache.relative_to(repo)} could not be read ({exc})"


def remediation(issue: str) -> str:
    return (
        "The Meta Agent must prepare the workflow cache before any Executor edits "
        "product code (requireValidCacheBeforeExecutor). Run:\n\n"
        f"    python agent-runtime/scripts/meta_prepare_executor.py --issue {issue}\n\n"
        "and proceed only when it prints readyForExecutor: true. If this is not issue "
        "work, use a branch without an issue-<N> suffix."
    )
