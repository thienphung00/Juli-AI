#!/usr/bin/env python3
"""Checkout preflight — prove this checkout is a safe place to work *before* editing.

Why this exists
---------------
An audit on 2026-08-11 found the repository's **primary** working directory parked on
``feature/git-lifecycle-governance``: 90 commits and 9 days behind ``origin/main``, 46
dirty files, two full untracked repo clones sitting at the repo root, 73 registered
worktrees and 61 unmerged local branches. ``main`` itself was checked out in a *side*
worktree, which is precisely what stranded the primary directory — git refuses to check
out a branch that another worktree already holds, so the primary had nowhere to return to.

Nothing was corrupted by a bad write. The damage was subtler and worse: every agent that
started in that directory read a nine-day-old tree and believed it. Work was re-done
against stale source, and fixes that already existed on ``main`` were "discovered" again.

``worktree_gc.py`` already governs the *close* half of the worktree lifecycle. This module
governs the *open* half: before you write, prove the checkout you are standing in is
current, is the branch you think it is, and is not one of N abandoned siblings.

Design notes
------------
* **No network by default.** ``origin/main`` is read from the local ref so this stays fast
  enough to sit in a PreToolUse hook. Pass ``--fetch`` for an authoritative answer; the
  ``ORIGIN_STALE`` check tells you when the local ref has gone off.
* **Severity, not a boolean.** ``FAIL`` means "this checkout will mislead you"; ``WARN``
  means "drift is accumulating, schedule a sweep". Only ``FAIL`` blocks a write.
* **Every finding carries a remedy.** A gate that says "no" without saying "do this
  instead" gets disabled within a week.

Exit codes: ``0`` no FAIL (WARNs allowed) · ``1`` at least one FAIL · ``2`` not a git repo
or git unavailable. ``--strict`` promotes WARN to a non-zero exit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------------------
# Thresholds. Env-overridable so a deliberate long-lived branch can raise the bar for
# itself without editing this file (and without disabling the gate wholesale).
# --------------------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


BEHIND_FAIL = _env_int("JULI_PREFLIGHT_BEHIND_FAIL", 50)
BEHIND_WARN = _env_int("JULI_PREFLIGHT_BEHIND_WARN", 15)
BASE_AGE_DAYS_FAIL = _env_int("JULI_PREFLIGHT_BASE_AGE_DAYS_FAIL", 7)
BASE_AGE_DAYS_WARN = _env_int("JULI_PREFLIGHT_BASE_AGE_DAYS_WARN", 2)
DIRTY_WARN = _env_int("JULI_PREFLIGHT_DIRTY_WARN", 20)
WORKTREE_WARN = _env_int("JULI_PREFLIGHT_WORKTREE_WARN", 12)
ORIGIN_STALE_HOURS = _env_int("JULI_PREFLIGHT_ORIGIN_STALE_HOURS", 12)

PROTECTED_BRANCHES = frozenset({"main", "master", "agent/runtime", "scratch/debug", "local/adhoc"})

# Directories that legitimately contain nested git metadata, or are too big to walk.
NESTED_SCAN_PRUNE = frozenset(
    {
        ".git",
        ".worktrees",
        "node_modules",
        ".next",
        ".turbo",
        "venv",
        ".venv",
        "__pycache__",
    }
)

FAIL, WARN, OK = "FAIL", "WARN", "OK"
_RANK = {OK: 0, WARN: 1, FAIL: 2}


@dataclass
class Finding:
    check: str
    severity: str
    headline: str
    detail: str = ""
    remedy: str = ""
    data: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# git plumbing
# --------------------------------------------------------------------------------------


def git(repo: Path, *args: str, timeout: int = 15) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def git_ok(repo: Path, *args: str, timeout: int = 15) -> str:
    code, out = git(repo, *args, timeout=timeout)
    return out if code == 0 else ""


@dataclass
class Worktree:
    path: Path
    branch: str
    head: str
    detached: bool
    primary: bool


def list_worktrees(repo: Path) -> list[Worktree]:
    """Parse ``git worktree list --porcelain``. The first record is always the primary."""
    out = git_ok(repo, "worktree", "list", "--porcelain")
    trees: list[Worktree] = []
    path = head = branch = ""
    detached = False
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            head = line[len("HEAD ") :]
        elif line.startswith("branch "):
            branch = line[len("branch ") :].removeprefix("refs/heads/")
        elif line == "detached":
            detached = True
        elif line == "" and path:
            trees.append(Worktree(Path(path), branch, head, detached, primary=not trees))
            path = head = branch = ""
            detached = False
    return trees


# --------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------


def check_stale_base(repo: Path, branch: str) -> Finding:
    """How much of ``origin/main`` is this checkout missing, in commits and in days?

    Commit count alone is a poor proxy — a quiet week and a busy afternoon can produce the
    same number. The age of the merge-base is what actually predicts "you are reading code
    that has since been rewritten", so both are measured and the worse one wins.
    """
    origin = git_ok(repo, "rev-parse", "--verify", "origin/main")
    if not origin:
        return Finding(
            "STALE_BASE",
            WARN,
            "origin/main is not available locally",
            "Cannot measure staleness without an origin/main ref.",
            "git fetch origin",
        )

    base = git_ok(repo, "merge-base", "HEAD", "origin/main")
    if not base:
        return Finding("STALE_BASE", WARN, "no merge-base with origin/main")

    behind = int(git_ok(repo, "rev-list", "--count", f"{base}..origin/main") or 0)
    base_ts = int(git_ok(repo, "log", "-1", "--format=%ct", base) or 0)
    tip_ts = int(git_ok(repo, "log", "-1", "--format=%ct", "origin/main") or 0)
    age_days = round(max(0, tip_ts - base_ts) / 86400.0, 1)

    data = {"behind": behind, "baseAgeDays": age_days, "branch": branch}
    remedy = (
        "git fetch origin && git rebase origin/main"
        if branch not in PROTECTED_BRANCHES
        else "git fetch origin && git merge --ff-only origin/main"
    )

    if behind >= BEHIND_FAIL or age_days >= BASE_AGE_DAYS_FAIL:
        return Finding(
            "STALE_BASE",
            FAIL,
            f"this checkout is {behind} commits / {age_days}d behind origin/main",
            "Anything you read here — source, migrations, config — may already have been "
            "changed on main. Fixes rediscovered against a stale tree are the single most "
            "expensive failure mode this gate exists to prevent.",
            remedy,
            data,
        )
    if behind >= BEHIND_WARN or age_days >= BASE_AGE_DAYS_WARN:
        return Finding(
            "STALE_BASE",
            WARN,
            f"{behind} commits / {age_days}d behind origin/main",
            "Still workable, but rebase before you trust a wide grep.",
            remedy,
            data,
        )
    return Finding("STALE_BASE", OK, f"current ({behind} behind, {age_days}d)", data=data)


def check_main_location(repo: Path, trees: list[Worktree]) -> Finding:
    """``main`` belongs in the primary working directory and nowhere else.

    When a side worktree holds ``main``, git refuses to check it out in the primary tree.
    The primary then gets parked on whatever feature branch it last touched and quietly
    rots there — exactly how the 90-commit drift happened.
    """
    holders = [t for t in trees if t.branch == "main" and not t.detached]
    if not holders:
        return Finding(
            "MAIN_LOCATION",
            WARN,
            "no worktree has main checked out",
            "The primary working directory should sit on main between tasks.",
            "git -C <primary> checkout main",
        )
    stray = [t for t in holders if not t.primary]
    if stray:
        paths = ", ".join(str(t.path) for t in stray)
        return Finding(
            "MAIN_LOCATION",
            FAIL,
            "main is checked out in a side worktree",
            f"Held by: {paths}. While this holds, the primary working directory cannot "
            "return to main and will stay stranded on a feature branch.",
            f"git worktree remove {stray[0].path}   # verify it is clean first",
            {"holders": [str(t.path) for t in stray]},
        )
    return Finding("MAIN_LOCATION", OK, "main is in the primary working directory")


def check_primary_tree(repo: Path, trees: list[Worktree]) -> Finding:
    """The primary directory is the tree humans and fresh agents read by default."""
    primary = next((t for t in trees if t.primary), None)
    if primary is None:
        return Finding("PRIMARY_TREE", WARN, "could not identify the primary worktree")

    if primary.detached:
        return Finding(
            "PRIMARY_TREE",
            FAIL,
            "primary working directory is in detached HEAD",
            f"HEAD {primary.head[:8]} belongs to no branch.",
            "git -C <primary> checkout main",
        )
    if primary.branch != "main":
        behind = int(git_ok(primary.path, "rev-list", "--count", "HEAD..origin/main") or 0)
        sev = FAIL if behind >= BEHIND_FAIL else WARN
        return Finding(
            "PRIMARY_TREE",
            sev,
            f"primary working directory is on '{primary.branch}', not main ({behind} behind)",
            "Task work belongs in a worktree under .worktrees/. Leaving the primary tree on "
            "a feature branch makes it the default stale answer for every agent that starts "
            "there.",
            "git -C <primary> checkout main && git -C <primary> pull --ff-only",
            {"branch": primary.branch, "behind": behind},
        )
    return Finding("PRIMARY_TREE", OK, "primary working directory is on main")


def check_dirty(repo: Path) -> Finding:
    out = git_ok(repo, "status", "--porcelain")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    n = len(lines)
    if n > DIRTY_WARN:
        sample = ", ".join(ln[3:] for ln in lines[:5])
        return Finding(
            "DIRTY_TREE",
            WARN,
            f"{n} uncommitted changes in this checkout",
            f"e.g. {sample}. A large unexplained diff usually means a previous task was "
            "abandoned here rather than closed.",
            "git status  # then commit, stash, or reset — do not build on top of it",
            {"dirty": n},
        )
    return Finding("DIRTY_TREE", OK, f"{n} uncommitted changes")


def check_nested_clones(repo: Path, trees: list[Worktree] | None = None) -> Finding:
    """A real ``.git`` *directory* below the repo root is a stray clone, not a worktree.

    Linked worktrees carry a ``.git`` **file** pointing into the parent, so this cannot
    confuse the two. Stray clones are invisible to `git status` (they self-ignore), hold
    their own divergent history, and are how 98 MB of dead code hid at the repo root.
    """
    # Strays land at the *primary* repo root, not in whichever linked worktree is
    # calling, so this check always inspects the primary tree.
    primary = next((t for t in (trees or []) if t.primary), None)
    root = primary.path if primary else repo

    found: list[str] = []
    for dirpath, dirnames, _ in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = [
            d for d in dirnames if d not in NESTED_SCAN_PRUNE and not d.startswith(".claude")
        ]
        if len(rel.parts) >= 3:
            dirnames.clear()
            continue
        for d in list(dirnames):
            if (Path(dirpath) / d / ".git").is_dir():
                found.append(str((Path(dirpath) / d).relative_to(root)))
                dirnames.remove(d)
    if found:
        return Finding(
            "NESTED_CLONE",
            FAIL,
            f"{len(found)} stray git clone(s) inside the repo",
            "Paths: " + ", ".join(found) + ". These are separate repositories with their "
            "own history. Tooling that walks the tree will read them as project source.",
            "Audit each for unique commits, then delete it.",
            {"clones": found},
        )
    return Finding("NESTED_CLONE", OK, "no stray clones inside the repo")


WORKTREE_POOLS = (".worktrees/", ".claude/worktrees/")


def check_worktree_location(repo: Path, trees: list[Worktree]) -> Finding:
    """Linked worktrees belong in a pool directory, never at the repo root.

    A worktree checked out at ``<repo>/rev-issue-722`` is a full source tree sitting where
    every ``find``, ``grep``, ``ruff`` and ``pytest`` collection walk will read it as
    project code. It also self-ignores, so ``git status`` reports one innocuous untracked
    directory rather than 70 MB of a parallel checkout at a different commit.
    """
    primary = next((t for t in trees if t.primary), None)
    if primary is None:
        return Finding("WORKTREE_LOCATION", WARN, "could not identify the primary worktree")
    root = primary.path.resolve()

    misplaced: list[str] = []
    for t in trees:
        if t.primary:
            continue
        try:
            rel = t.path.resolve().relative_to(root).as_posix() + "/"
        except ValueError:
            continue  # outside the repo entirely — not a tree-walk hazard
        if not rel.startswith(WORKTREE_POOLS):
            misplaced.append(rel.rstrip("/"))

    if misplaced:
        return Finding(
            "WORKTREE_LOCATION",
            FAIL,
            f"{len(misplaced)} worktree(s) checked out outside the pool directories",
            "Paths: " + ", ".join(misplaced) + ". A worktree at the repo root is read as "
            "project source by every tree walk, at whatever commit it was abandoned on.",
            "python agent-runtime/scripts/git/worktree_gc.py --report, then "
            "git worktree remove <path> (never rm -rf — that strands .git/worktrees admin data)",
            {"misplaced": misplaced},
        )
    return Finding("WORKTREE_LOCATION", OK, "all worktrees live in the pool directories")


def check_worktree_drift(repo: Path, trees: list[Worktree]) -> Finding:
    n = len(trees)
    if n > WORKTREE_WARN:
        return Finding(
            "WORKTREE_DRIFT",
            WARN,
            f"{n} registered worktrees (soft limit {WORKTREE_WARN})",
            "Abandoned worktrees consume disk and make it easy to edit the wrong tree.",
            "python agent-runtime/scripts/git/worktree_gc.py --report",
            {"worktrees": n},
        )
    return Finding("WORKTREE_DRIFT", OK, f"{n} registered worktrees")


def check_origin_freshness(repo: Path) -> Finding:
    fetch_head = repo / ".git" / "FETCH_HEAD"
    git_dir = git_ok(repo, "rev-parse", "--git-common-dir")
    if git_dir:
        candidate = Path(git_dir)
        if not candidate.is_absolute():
            candidate = repo / candidate
        fetch_head = candidate / "FETCH_HEAD"
    try:
        age_h = (time.time() - fetch_head.stat().st_mtime) / 3600.0
    except OSError:
        return Finding(
            "ORIGIN_STALE",
            WARN,
            "no record of a fetch in this clone",
            remedy="git fetch origin",
        )
    if age_h > ORIGIN_STALE_HOURS:
        return Finding(
            "ORIGIN_STALE",
            WARN,
            f"last fetch was {age_h:.0f}h ago",
            "Staleness measurements below are against a local ref that may itself be old.",
            "git fetch origin",
            {"fetchAgeHours": round(age_h, 1)},
        )
    return Finding("ORIGIN_STALE", OK, f"fetched {age_h:.1f}h ago")


# --------------------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------------------

# Checks a PreToolUse hook is allowed to block a write on. Deliberately narrow: each one
# means "what you are about to read or write is not what you think it is". Drift-style
# findings (dirty tree, worktree count) inform but never block.
BLOCKING_CHECKS = frozenset(
    {"STALE_BASE", "MAIN_LOCATION", "NESTED_CLONE", "PRIMARY_TREE", "WORKTREE_LOCATION"}
)


def run_checks(repo: Path, *, fetch: bool = False, quick: bool = False) -> list[Finding]:
    if fetch:
        git(repo, "fetch", "origin", "--prune", "--quiet", timeout=60)

    branch = git_ok(repo, "rev-parse", "--abbrev-ref", "HEAD")
    trees = list_worktrees(repo)

    findings = [
        check_stale_base(repo, branch),
        check_main_location(repo, trees),
        check_primary_tree(repo, trees),
    ]
    if not quick:
        findings += [
            check_nested_clones(repo, trees),
            check_worktree_location(repo, trees),
            check_dirty(repo),
            check_worktree_drift(repo, trees),
            check_origin_freshness(repo),
        ]
    else:
        # The hook path still needs stray-clone detection; it is cheap (depth-2 walk)
        # and it is the one FAIL a fast check would otherwise miss entirely.
        findings.append(check_nested_clones(repo, trees))
        findings.append(check_worktree_location(repo, trees))
    return findings


def worst(findings: list[Finding]) -> str:
    return max((f.severity for f in findings), key=lambda s: _RANK[s], default=OK)


ICON = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}


def render(findings: list[Finding], repo: Path, branch: str) -> str:
    lines = [f"checkout preflight — {repo}  [{branch}]", ""]
    for f in findings:
        lines.append(f"[{ICON[f.severity]}] {f.check:<16} {f.headline}")
        if f.severity != OK:
            if f.detail:
                lines.append(f"                       {f.detail}")
            if f.remedy:
                lines.append(f"                       -> {f.remedy}")
    lines += ["", f"verdict: {worst(findings)}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--fetch", action="store_true", help="git fetch first (authoritative, slower)")
    ap.add_argument("--quick", action="store_true", help="hook mode: only the blocking checks")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on WARN as well as FAIL")
    ap.add_argument("--repo", default=".", help="path inside the checkout to inspect")
    args = ap.parse_args(argv)

    start = Path(args.repo).resolve()
    top = git_ok(start, "rev-parse", "--show-toplevel")
    if not top:
        print(f"not a git repository: {start}", file=sys.stderr)
        return 2
    repo = Path(top).resolve()

    findings = run_checks(repo, fetch=args.fetch, quick=args.quick)
    branch = git_ok(repo, "rev-parse", "--abbrev-ref", "HEAD")
    verdict = worst(findings)

    if args.json:
        print(
            json.dumps(
                {
                    "repo": str(repo),
                    "branch": branch,
                    "verdict": verdict,
                    "findings": [asdict(f) for f in findings],
                },
                indent=2,
            )
        )
    else:
        print(render(findings, repo, branch))

    if verdict == FAIL:
        return 1
    if verdict == WARN and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
