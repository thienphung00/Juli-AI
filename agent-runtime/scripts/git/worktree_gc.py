#!/usr/bin/env python3
"""Safe worktree/branch garbage collection for the parallel-implementation topology.

Governs the *close* half of the worktree lifecycle in
``.cursor/rules/git-baseline.mdc`` and ``docs/handoffs/worktree-branch-topology.md``.
The agent opens one ``feature/<short-desc>`` worktree per parallel task; this script
closes it once its PR merges, without leaving stale branches or gone-upstream refs.

Autonomy boundary (enforced here, not just documented):

* ``--close``/``--sweep`` only remove a worktree + branch when it is **merged AND clean**
  (no uncommitted changes, no unpushed commits). Squash-merges are detected via ``gh``,
  which ``git branch -d`` cannot see.
* Anything human-created, dirty, unpushed, or backed by a closed-not-merged PR is
  reported and left in place — the agent must surface it and ask before deleting.
* Persistent slots (``agent/runtime``, ``scratch/debug``, ``local/adhoc``) and ``main``
  are never touched.

Every mode runs ``git fetch --prune`` first, so gone-upstream refs never accumulate.

Examples::

    python agent-runtime/scripts/git/worktree_gc.py --report          # classify, delete nothing
    python agent-runtime/scripts/git/worktree_gc.py --close cdp-a1     # close one merged task
    python agent-runtime/scripts/git/worktree_gc.py --sweep            # close all merged+clean

Exit codes: ``0`` success / nothing to do; ``1`` a requested close was refused (needs a
human); ``2`` usage or environment error (e.g. ``gh`` unavailable).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Never removed, regardless of merge/clean state — see git-baseline.mdc.
PROTECTED_BRANCHES = frozenset({"main", "master", "agent/runtime", "scratch/debug", "local/adhoc"})


class GitError(RuntimeError):
    """A git/gh invocation failed in a way the caller should surface."""


def _run(args: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    """Run a command and return stripped stdout. Raise GitError on failure when checked."""
    proc = subprocess.run(
        args,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise GitError(f"{' '.join(args)} -> exit {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()


@dataclass
class WorktreeInfo:
    """One product worktree and everything needed to decide whether it is safe to close."""

    path: Path
    branch: str
    is_protected: bool
    is_dirty: bool
    unpushed: int
    has_upstream: bool
    pr_merged: bool
    pr_closed_unmerged: bool

    @property
    def safe_to_close(self) -> bool:
        """Merged-and-clean: the only state the agent may auto-close without asking."""
        return (
            not self.is_protected
            and self.pr_merged
            and not self.is_dirty
            and self.unpushed == 0
        )

    @property
    def status(self) -> str:
        if self.is_protected:
            return "keep (protected slot)"
        if self.is_dirty:
            return "NEEDS-CONFIRM (uncommitted changes)"
        if self.unpushed:
            return f"NEEDS-CONFIRM ({self.unpushed} unpushed commit(s))"
        if self.pr_merged:
            return "safe-to-close (PR merged, clean)"
        if self.pr_closed_unmerged:
            return "NEEDS-CONFIRM (PR closed, not merged)"
        return "keep (open / no merged PR)"


def _gh_available() -> bool:
    try:
        _run(["gh", "auth", "status"])
        return True
    except (GitError, FileNotFoundError):
        return False


def _pr_state(branch: str) -> tuple[bool, bool]:
    """Return (merged, closed_unmerged) for a branch's PRs, using gh (catches squash)."""
    try:
        out = _run(
            ["gh", "pr", "list", "--state", "all", "--head", branch,
             "--json", "state", "--jq", ".[].state"],
        )
    except (GitError, FileNotFoundError):
        return (False, False)
    states = {line.strip() for line in out.splitlines() if line.strip()}
    return ("MERGED" in states, bool(states) and "MERGED" not in states and "CLOSED" in states)


def _iter_worktrees() -> list[tuple[Path, str]]:
    """Yield (path, branch) for every worktree that has a branch checked out."""
    out = _run(["git", "worktree", "list", "--porcelain"])
    results: list[tuple[Path, str]] = []
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch ") and path is not None:
            branch = line[len("branch "):].removeprefix("refs/heads/")
            results.append((path, branch))
            path = None
    return results


def _collect(path: Path, branch: str) -> WorktreeInfo:
    is_protected = branch in PROTECTED_BRANCHES
    dirty = bool(_run(["git", "status", "--porcelain"], cwd=path))
    has_upstream = (
        _run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
             cwd=path, check=False) != ""
    )
    unpushed = 0
    if has_upstream:
        count = _run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=path, check=False)
        unpushed = int(count) if count.isdigit() else 0
    merged, closed_unmerged = (False, False) if is_protected else _pr_state(branch)
    return WorktreeInfo(
        path=path,
        branch=branch,
        is_protected=is_protected,
        is_dirty=dirty,
        unpushed=unpushed,
        has_upstream=has_upstream,
        pr_merged=merged,
        pr_closed_unmerged=closed_unmerged,
    )


def _close(info: WorktreeInfo) -> None:
    """Remove worktree + local branch. Caller must have verified safe_to_close."""
    if info.path != REPO_ROOT:
        _run(["git", "worktree", "remove", str(info.path)])
    _run(["git", "branch", "-D", info.branch])


def _fetch_prune() -> None:
    _run(["git", "fetch", "--prune", "origin"], check=False)


def _match(info: WorktreeInfo, task: str) -> bool:
    return task == info.branch or info.path.name == task or info.branch.endswith(task)


def cmd_report(infos: list[WorktreeInfo]) -> int:
    print(f"{'STATUS':<38} {'BRANCH':<44} PATH")
    print("-" * 100)
    for info in sorted(infos, key=lambda i: i.status):
        print(f"{info.status:<38} {info.branch:<44} {info.path}")
    safe = [i for i in infos if i.safe_to_close]
    confirm = [i for i in infos if not i.safe_to_close and "NEEDS-CONFIRM" in i.status]
    print(f"\n{len(safe)} safe-to-close, {len(confirm)} need confirmation, "
          f"{len(infos) - len(safe) - len(confirm)} keep.")
    if safe:
        print("Auto-closeable: " + ", ".join(i.branch for i in safe))
    return 0


def cmd_close(infos: list[WorktreeInfo], task: str) -> int:
    matches = [i for i in infos if _match(i, task)]
    if not matches:
        print(f"error: no worktree/branch matching '{task}'", file=sys.stderr)
        return 2
    if len(matches) > 1:
        print(f"error: '{task}' is ambiguous: {', '.join(i.branch for i in matches)}",
              file=sys.stderr)
        return 2
    info = matches[0]
    if not info.safe_to_close:
        print(f"REFUSED: {info.branch} is {info.status}.", file=sys.stderr)
        print("Surface this to the user and confirm before deleting.", file=sys.stderr)
        return 1
    _close(info)
    print(f"closed {info.branch} (worktree {info.path.name}); remote-tracking pruned.")
    return 0


def cmd_sweep(infos: list[WorktreeInfo]) -> int:
    safe = [i for i in infos if i.safe_to_close]
    for info in safe:
        _close(info)
        print(f"closed {info.branch} (worktree {info.path.name}).")
    skipped = [i for i in infos if not i.safe_to_close and "NEEDS-CONFIRM" in i.status]
    if skipped:
        print("\nLeft for confirmation (not auto-closed):")
        for info in skipped:
            print(f"  {info.branch}: {info.status}")
    print(f"\nswept {len(safe)} merged+clean worktree(s); {len(skipped)} need confirmation.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--report", action="store_true",
        help="Classify all worktrees; delete nothing (default).",
    )
    group.add_argument("--close", metavar="TASK", help="Close one merged+clean task worktree.")
    group.add_argument("--sweep", action="store_true", help="Close every merged+clean worktree.")
    args = parser.parse_args(argv)

    if not _gh_available():
        print("error: `gh` is required for squash-merge detection and not authenticated.",
              file=sys.stderr)
        print("Run `gh auth login`, or use --report which degrades gracefully.", file=sys.stderr)
        if not args.report:
            return 2

    _fetch_prune()
    infos = [_collect(path, branch) for path, branch in _iter_worktrees()]

    if args.close:
        return cmd_close(infos, args.close)
    if args.sweep:
        return cmd_sweep(infos)
    return cmd_report(infos)


if __name__ == "__main__":
    raise SystemExit(main())
