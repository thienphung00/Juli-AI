#!/usr/bin/env python3
"""Gate: catch #736-pattern issue work — done locally but never landed.

Issue #736 was a live security hole. The fix existed as four commits on a local
branch with a worktree, but the branch had no remote tracking ref and no PR, so
nothing surfaced it. This gate makes that state loud instead of silent.

It reports, without mutating anything:

1. Local branches with commits not on ``origin/main`` and no matching branch on
   ``origin`` (never pushed, or pushed then the remote branch vanished).
2. Local branches that *are* pushed to ``origin`` but have no open or merged PR.
3. Worktrees under ``.worktrees/`` whose branch is in either state above.
4. (Optional, best-effort) Open issues labelled ``in-progress`` with no branch,
   no PR, and no commit referencing them anywhere in local history — the #795
   pattern. Requires ``gh``; skipped (not failed) when ``gh`` is unavailable or
   unauthenticated.

Only genuinely stale work fails the gate — a branch's newest commit must be
older than ``--max-age-hours`` (default 24) to be reported. Fresh local work in
progress is normal and must not trip the gate.

Read-only: the only network call is a plain ``git fetch`` (no ``--prune``) plus
``git ls-remote`` and, optionally, ``gh`` reads. Nothing is pushed, deleted, or
rewritten.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import REPO_ROOT, print_check_result, utc_now_iso  # noqa: E402

DEFAULT_MAX_AGE_HOURS = 24.0

# Persistent helper slots and the default branch are never flagged — see
# .cursor/rules/git-baseline.mdc.
PROTECTED_BRANCHES = frozenset({"main", "master", "agent/runtime", "scratch/debug", "local/adhoc"})

ISSUE_NUM_RE = re.compile(r"issue-(\d+)", re.IGNORECASE)
ISSUE_REF_RE = re.compile(r"(?<!\d)#(\d+)(?!\d)")

GIT_TIMEOUT = 20
GH_TIMEOUT = 20


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    check: bool = False,
    timeout: int = GIT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} -> exit {proc.returncode}: {proc.stderr.strip()}")
    return proc


def _lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def issue_from_branch(branch: str) -> int | None:
    match = ISSUE_NUM_RE.search(branch)
    return int(match.group(1)) if match else None


@dataclass
class BranchFinding:
    branch: str
    category: str  # "unpushed_no_tracking" | "pushed_no_pr"
    issue: int | None
    ahead_of_main: int | None
    newest_commit_sha: str
    newest_commit_age_hours: float
    worktree_path: str | None = None
    pr_states: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "category": self.category,
            "issue": self.issue,
            "aheadOfMain": self.ahead_of_main,
            "newestCommitSha": self.newest_commit_sha,
            "newestCommitAgeHours": round(self.newest_commit_age_hours, 2),
            "worktreePath": self.worktree_path,
            "prStates": self.pr_states,
        }


def _repo_has_remote(repo_root: Path, remote: str = "origin") -> bool:
    proc = _run(["git", "remote", "get-url", remote], cwd=repo_root)
    return proc.returncode == 0


def _fetch_main(repo_root: Path, remote: str = "origin", ref: str = "main") -> bool:
    """Plain fetch of one ref — updates only origin/<ref>, never prunes or rewrites."""
    proc = _run(["git", "fetch", remote, ref], cwd=repo_root, timeout=60)
    return proc.returncode == 0


def _main_ref_available(repo_root: Path, remote: str = "origin", ref: str = "main") -> bool:
    proc = _run(["git", "rev-parse", "--verify", f"{remote}/{ref}"], cwd=repo_root)
    return proc.returncode == 0


def local_branches(repo_root: Path) -> list[str]:
    proc = _run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=repo_root,
    )
    return _lines(proc)


def remote_branch_names(repo_root: Path, remote: str = "origin") -> set[str] | None:
    """Authoritative, read-only list of branches that exist on ``remote`` right now.

    Uses ``ls-remote`` — never touches local refs. Returns ``None`` if the remote
    is unreachable (offline, no remote, etc.) so callers can degrade gracefully.
    """
    proc = _run(["git", "ls-remote", "--heads", remote], cwd=repo_root, timeout=30)
    if proc.returncode != 0:
        return None
    names: set[str] = set()
    for line in _lines(proc):
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            names.add(parts[1][len("refs/heads/") :])
    return names


def ahead_of_main(
    repo_root: Path, branch: str, remote: str = "origin", ref: str = "main"
) -> int | None:
    proc = _run(["git", "rev-list", "--count", f"{remote}/{ref}..{branch}"], cwd=repo_root)
    if proc.returncode != 0 or not proc.stdout.strip().isdigit():
        return None
    return int(proc.stdout.strip())


def newest_commit(repo_root: Path, branch: str) -> tuple[str, float] | None:
    """Return (short sha, age in hours) of the branch tip commit, by wall clock."""
    proc = _run(["git", "log", "-1", "--format=%h %ct", branch], cwd=repo_root)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    parts = proc.stdout.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    sha, epoch = parts[0], int(parts[1])
    age_hours = max(0.0, (time.time() - epoch) / 3600.0)
    return sha, age_hours


def worktrees_under(repo_root: Path) -> dict[str, str]:
    """Map branch name -> worktree path, restricted to paths under .worktrees/."""
    proc = _run(["git", "worktree", "list", "--porcelain"], cwd=repo_root)
    result: dict[str, str] = {}
    path: str | None = None
    worktrees_root = (repo_root / ".worktrees").resolve()
    for line in _lines(proc):
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
        elif line.startswith("branch ") and path is not None:
            branch = line[len("branch ") :].removeprefix("refs/heads/")
            try:
                is_under = (
                    worktrees_root in Path(path).resolve().parents
                    or Path(path).resolve() == worktrees_root
                )
            except OSError:
                is_under = False
            if is_under:
                result[branch] = path
            path = None
    return result


def gh_available(repo_root: Path) -> bool:
    if shutil.which("gh") is None:
        return False
    proc = _run(["gh", "auth", "status"], cwd=repo_root, timeout=GH_TIMEOUT)
    return proc.returncode == 0


def pr_states_for_branch(repo_root: Path, branch: str) -> list[str]:
    proc = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--head",
            branch,
            "--json",
            "state",
            "--jq",
            ".[].state",
        ],
        cwd=repo_root,
        timeout=GH_TIMEOUT,
    )
    return _lines(proc)


def in_progress_issues(repo_root: Path) -> list[dict[str, Any]]:
    proc = _run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "in-progress",
            "--json",
            "number,title,url",
            "--limit",
            "200",
        ],
        cwd=repo_root,
        timeout=GH_TIMEOUT,
    )
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return []


def all_commit_subjects(repo_root: Path) -> str:
    proc = _run(["git", "log", "--all", "--format=%s"], cwd=repo_root, timeout=60)
    return proc.stdout if proc.returncode == 0 else ""


def issue_referenced_in_commits(subjects: str, issue: int) -> bool:
    for match in ISSUE_REF_RE.finditer(subjects):
        if int(match.group(1)) == issue:
            return True
    needle = f"issue-{issue}"
    return needle.lower() in subjects.lower()


def run_check(
    issue: int | None = None,  # noqa: ARG001
    *,
    repo_root: Path = REPO_ROOT,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    check_gh: bool = True,
) -> tuple[bool, str, dict[str, Any]]:
    """Repo-wide gate — the ``issue`` argument exists only to match the shared
    validate-gate signature used by generate_validation_artifact.py; this gate
    reports on every branch/worktree in the repo, not just the issue under review.
    """
    details: dict[str, Any] = {
        "maxAgeHours": max_age_hours,
        "generatedAt": utc_now_iso(),
        "remoteAvailable": False,
        "ghAvailable": False,
        "staleUnpushedBranches": [],
        "pushedNoPrBranches": [],
        "freshUnpushedBranchCount": 0,
        "inProgressIssuesNoWork": [],
        "notes": [],
    }

    has_remote = _repo_has_remote(repo_root)
    remote_names: set[str] | None = None
    main_available = False
    if has_remote:
        _fetch_main(repo_root)
        main_available = _main_ref_available(repo_root)
        remote_names = remote_branch_names(repo_root)

    details["remoteAvailable"] = bool(has_remote and main_available and remote_names is not None)
    if not details["remoteAvailable"]:
        details["notes"].append("no reachable origin/main — branch-vs-main checks skipped")

    findings: list[BranchFinding] = []

    if details["remoteAvailable"]:
        assert remote_names is not None
        worktree_map = worktrees_under(repo_root)
        branches = [b for b in local_branches(repo_root) if b not in PROTECTED_BRANCHES]

        use_gh = check_gh and gh_available(repo_root)
        details["ghAvailable"] = use_gh

        for branch in branches:
            ahead = ahead_of_main(repo_root, branch)
            if not ahead:
                continue
            tip = newest_commit(repo_root, branch)
            if tip is None:
                continue
            sha, age_hours = tip
            pushed = branch in remote_names
            issue_num = issue_from_branch(branch)
            worktree_path = worktree_map.get(branch)

            if not pushed:
                if age_hours >= max_age_hours:
                    findings.append(
                        BranchFinding(
                            branch=branch,
                            category="unpushed_no_tracking",
                            issue=issue_num,
                            ahead_of_main=ahead,
                            newest_commit_sha=sha,
                            newest_commit_age_hours=age_hours,
                            worktree_path=worktree_path,
                        )
                    )
                else:
                    details["freshUnpushedBranchCount"] += 1
                continue

            # Pushed: check for an open or merged PR.
            if not use_gh:
                details["notes"].append(
                    f"{branch}: pushed but PR status unknown (gh unavailable) — not flagged"
                )
                continue
            states = pr_states_for_branch(repo_root, branch)
            has_landed_or_open = any(s in ("OPEN", "MERGED") for s in states)
            if not has_landed_or_open and age_hours >= max_age_hours:
                findings.append(
                    BranchFinding(
                        branch=branch,
                        category="pushed_no_pr",
                        issue=issue_num,
                        ahead_of_main=ahead,
                        newest_commit_sha=sha,
                        newest_commit_age_hours=age_hours,
                        worktree_path=worktree_path,
                        pr_states=states,
                    )
                )
            elif not has_landed_or_open:
                details["freshUnpushedBranchCount"] += 1
    else:
        details["ghAvailable"] = check_gh and gh_available(repo_root)

    details["staleUnpushedBranches"] = [
        f.to_dict() for f in findings if f.category == "unpushed_no_tracking"
    ]
    details["pushedNoPrBranches"] = [f.to_dict() for f in findings if f.category == "pushed_no_pr"]

    # Optional #795-shaped check: in-progress issues with no trace anywhere.
    if details["ghAvailable"]:
        issues = in_progress_issues(repo_root)
        if issues:
            local_names = set(local_branches(repo_root))
            remote_set = remote_names or set()
            subjects = all_commit_subjects(repo_root)
            pr_branch_names: set[str] = set()
            pr_proc = _run(
                ["gh", "pr", "list", "--state", "all", "--json", "headRefName", "--limit", "500"],
                cwd=repo_root,
                timeout=GH_TIMEOUT,
            )
            if pr_proc.returncode == 0:
                try:
                    for row in json.loads(pr_proc.stdout):
                        pr_branch_names.add(row.get("headRefName", ""))
                except (json.JSONDecodeError, ValueError):
                    pass

            for item in issues:
                num = item.get("number")
                if not isinstance(num, int):
                    continue
                has_branch = any(issue_from_branch(b) == num for b in local_names | remote_set)
                has_pr_branch = any(issue_from_branch(b) == num for b in pr_branch_names)
                has_commit = issue_referenced_in_commits(subjects, num)
                if not (has_branch or has_pr_branch or has_commit):
                    details["inProgressIssuesNoWork"].append(
                        {"issue": num, "title": item.get("title"), "url": item.get("url")}
                    )

    stale_count = len(details["staleUnpushedBranches"])
    no_pr_count = len(details["pushedNoPrBranches"])
    orphan_count = len(details["inProgressIssuesNoWork"])
    total = stale_count + no_pr_count + orphan_count

    if total == 0:
        return True, "No stale unpushed issue work detected", details

    parts = []
    if stale_count:
        parts.append(f"{stale_count} unpushed branch(es) with no remote and no PR")
    if no_pr_count:
        parts.append(f"{no_pr_count} pushed branch(es) with no open/merged PR")
    if orphan_count:
        parts.append(f"{orphan_count} in-progress issue(s) with no trace of work")
    return False, "; ".join(parts), details


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate no stale unpushed issue work exists")
    parser.add_argument("--issue", type=int, default=None, help="unused — repo-wide gate")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help="age (hours) a branch's newest commit must exceed to be flagged (default: 24)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--no-gh", action="store_true", help="skip gh-backed checks even if gh is available"
    )
    args = parser.parse_args()

    passed, description, details = run_check(
        args.issue,
        repo_root=args.repo_root,
        max_age_hours=args.max_age_hours,
        check_gh=not args.no_gh,
    )

    if args.json:
        payload = {
            "check": "unpushed_issue_work",
            "status": "PASS" if passed else "FAIL",
            "description": "" if passed else description,
            "details": details,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if passed else 1

    for entry in details["staleUnpushedBranches"]:
        print(
            f"  STALE UNPUSHED: {entry['branch']} "
            f"(issue={entry['issue']}, ahead={entry['aheadOfMain']}, "
            f"age={entry['newestCommitAgeHours']}h, worktree={entry['worktreePath']})"
        )
    for entry in details["pushedNoPrBranches"]:
        print(
            f"  PUSHED, NO PR: {entry['branch']} "
            f"(issue={entry['issue']}, age={entry['newestCommitAgeHours']}h, "
            f"worktree={entry['worktreePath']})"
        )
    for entry in details["inProgressIssuesNoWork"]:
        print(f"  IN-PROGRESS, NO WORK: #{entry['issue']} {entry['title']} ({entry['url']})")

    return print_check_result("unpushed_issue_work", passed, "" if passed else description)


if __name__ == "__main__":
    raise SystemExit(main())
