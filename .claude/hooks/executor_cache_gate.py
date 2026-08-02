#!/usr/bin/env python3
"""PreToolUse gate: no product-code edits on an issue branch without a valid workflow cache.

Mirrors `workflow_prompt_cache.requireValidCacheBeforeExecutor` from
`agent-runtime/config/agent-runtime.config.yml`, so the Executor contract is enforced by the
harness rather than by prompt discipline alone.

Allows the edit when any of these hold:
  * the branch does not match `issue-<N>` (quick-commit / scratch path, mirroring
    `artifact_gates.quickCommitSkip` and the CI behaviour in .github/workflows/pr.yml)
  * the target is outside the guarded product-code roots (docs, ADRs, agent-runtime config,
    .cursor, .claude are all editable by Architect/Meta without a cache)
  * `agent-runtime/artifacts/workflow-cache/issue-context-cache-<N>.json` has
    `cacheStatus == "valid"`

Fails open on any unexpected error — a broken hook must not brick the edit loop.

Protocol: PreToolUse JSON on stdin; exit 0 to allow, exit 2 to block with the stderr
message fed back to the agent.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_ISSUE_BRANCH_PATTERN = r"issue-([0-9]+)"
CONFIG_REL = Path("agent-runtime/config/agent-runtime.config.yml")
CACHE_REL = Path("agent-runtime/artifacts/workflow-cache")

# Product code. Everything else (docs/, .cursor/, .claude/, agent-runtime/) stays editable
# so Architect and Meta can do their jobs before a cache exists.
GUARDED_ROOTS = ("backend/", "apps/", "packages/", "ios/", "infra/", "tests/", "web/")

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=5
    )
    return out.stdout.strip() if out.returncode == 0 else ""


def issue_branch_pattern(repo: Path) -> str:
    """Read the pattern from harness config; fall back to the documented default."""
    cfg = repo / CONFIG_REL
    try:
        m = re.search(
            r'^\s*issueBranchPattern:\s*"?([^"\n]+)"?\s*$', cfg.read_text(), re.M
        )
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return DEFAULT_ISSUE_BRANCH_PATTERN


def main() -> int:
    payload = json.load(sys.stdin)

    if payload.get("tool_name") not in WRITE_TOOLS:
        return 0

    raw_path = (payload.get("tool_input") or {}).get("file_path")
    if not raw_path:
        return 0

    cwd = Path(payload.get("cwd") or ".").resolve()
    repo_str = git(cwd, "rev-parse", "--show-toplevel")
    if not repo_str:
        return 0
    repo = Path(repo_str).resolve()

    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    m = re.search(issue_branch_pattern(repo), branch)
    if not m:
        # Not issue work — quickCommitSkip territory. CI skips artifact gates here too.
        return 0
    issue = m.group(1)

    try:
        rel = Path(raw_path).resolve().relative_to(repo).as_posix()
    except ValueError:
        return 0  # outside the repo; not ours to police
    if not rel.startswith(GUARDED_ROOTS):
        return 0

    cache = repo / CACHE_REL / f"issue-context-cache-{issue}.json"
    if cache.is_file():
        try:
            if json.loads(cache.read_text()).get("cacheStatus") == "valid":
                return 0
            reason = f"cacheStatus is not 'valid' in {cache.relative_to(repo)}"
        except (OSError, json.JSONDecodeError) as exc:
            reason = f"{cache.relative_to(repo)} could not be read ({exc})"
    else:
        reason = f"no workflow cache at {cache.relative_to(repo)}"

    print(
        f"Executor gate: blocked edit to {rel} on branch {branch}.\n"
        f"{reason}.\n\n"
        f"The Meta Agent must prepare the workflow cache before any Executor edits product "
        f"code (requireValidCacheBeforeExecutor). Run:\n\n"
        f"    python agent-runtime/scripts/meta_prepare_executor.py --issue {issue}\n\n"
        f"and proceed only when it prints readyForExecutor: true. If this is not issue "
        f"work, use a branch without an issue-<N> suffix.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — a broken gate must not block all edits
        sys.exit(0)
