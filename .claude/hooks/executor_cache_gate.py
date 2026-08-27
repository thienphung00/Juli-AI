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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gate_rules import (  # noqa: E402
    cache_problem,
    git,
    is_guarded,
    remediation,
    resolve_issue,
)

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# NOTE (#1384): this hook only sees the file-editing tools, so a shell write
# (sed -i, a heredoc, cat >, tee, a script) never reaches it. The rules it
# applies live in `_gate_rules.py`, shared with
# `executor_cache_precommit.py`, which re-checks them against the staged diff
# and is the half that cannot be routed around.


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

    issue = resolve_issue(repo)
    if issue is None:
        # Not issue work — quickCommitSkip territory. CI skips artifact gates here too.
        return 0

    try:
        rel = Path(raw_path).resolve().relative_to(repo).as_posix()
    except ValueError:
        return 0  # outside the repo; not ours to police
    if not is_guarded(rel):
        return 0

    problem = cache_problem(repo, issue)
    if problem is None:
        return 0

    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    print(
        f"Executor gate: blocked edit to {rel} on branch {branch}.\n"
        f"{problem}.\n\n"
        f"{remediation(issue)}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — a broken gate must not block all edits
        sys.exit(0)
