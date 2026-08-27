#!/usr/bin/env python3
"""Pre-commit backstop for the executor cache gate (#1384).

`executor_cache_gate.py` is a `PreToolUse` hook on the file-editing tools, so
a shell write — `sed -i`, a heredoc, `cat >`, `tee`, a script — never triggers
it. This checks the staged diff instead, which no write mechanism can route
around, and so is the half of the pair that actually holds.

Exits non-zero (blocking the commit) when the branch resolves to an issue,
staged files touch guarded product paths, and no valid workflow cache exists.
"""

from __future__ import annotations

import subprocess
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


def main() -> int:
    repo = Path(
        git(Path.cwd(), "rev-parse", "--show-toplevel") or Path.cwd()
    )
    issue = resolve_issue(repo)
    if issue is None:
        return 0

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    guarded = sorted(p for p in staged if is_guarded(p))
    if not guarded:
        return 0

    problem = cache_problem(repo, issue)
    if problem is None:
        return 0

    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    shown = "\n".join(f"    {p}" for p in guarded[:10])
    more = f"\n    ... and {len(guarded) - 10} more" if len(guarded) > 10 else ""
    print(
        f"Executor gate (pre-commit): {len(guarded)} staged product file(s) on "
        f"branch {branch}, but {problem}.\n\n"
        f"{shown}{more}\n\n"
        f"{remediation(issue)}\n\n"
        "This is the backstop for the PreToolUse gate, which only sees the "
        "file-editing tools and is bypassed by shell writes (#1384).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
