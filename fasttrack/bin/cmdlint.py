#!/usr/bin/env python3
"""fasttrack/bin/cmdlint.py — lint a command BEFORE handing it to the owner to run.

  echo "$CMD" | fasttrack/bin/cmdlint.py        # or: cmdlint.py "<command>"

Exit 1 with reasons when the command would likely fail or mislead. Every rule is a
failure seen in the 2026-11-09..16 sessions (~30 % of owner-run commands failed):
placeholders left in, truncated text, `cd` without a guard, zsh mangling `$X:refs`,
multi-line `gh pr create --body`, `--tags` pushes, relative paths with no `cd`.
"""

from __future__ import annotations

import re
import shlex
import sys

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("placeholder ellipsis", re.compile(r"…|(?<![.\w])\.\.\.(?![.\w/])")),
    ("angle-bracket placeholder", re.compile(r"<(?:[a-z][a-z0-9_-]*|[A-Z][A-Z0-9_]*)>")),
    (
        "date/id placeholder",
        re.compile(r"\b(?:YYYY[-/]?MM[-/]?DD|YYYYMMDD|HHMM|XXXX+|TODO|FIXME|CHANGEME)\b"),
    ),
    ("zsh colon modifier ($VAR:refs)", re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*:(?:refs|[a-z])")),
    ("pushes every tag", re.compile(r"git push\b[^\n]*--tags")),
    ("force push", re.compile(r"git push\b[^\n]*(?:--force\b|-f\b)")),
]


def lint(cmd: str) -> list[str]:
    problems = [name for name, rx in RULES if rx.search(cmd)]
    try:
        shlex.split(cmd, comments=True)
    except ValueError as e:
        problems.append(f"unbalanced quoting / truncated ({e})")
    for m in re.finditer(r"(?:^|&&|;|\|\|)\s*cd\s+[^\n;&|]+", cmd):
        tail = cmd[m.end() : m.end() + 12]
        if not tail.lstrip().startswith(("||", "&&")) and cmd.strip() != m.group(0).strip():
            problems.append(
                "`cd` not followed by && or || exit (runs in the wrong dir if cd fails)"
            )
            break
    if re.search(r"gh pr create\b", cmd) and re.search(r"--body\s+[\"'][^\"']*\n", cmd):
        problems.append("multi-line gh --body; use --body-file or fasttrack/bin/open_pr.py")
    if re.search(r"(?:^|\s)\./", cmd) and not re.search(r"\bcd\s+/", cmd):
        problems.append("relative ./path with no absolute `cd` first")
    return problems


def main(argv: list[str]) -> int:
    cmd = " ".join(argv) if argv else sys.stdin.read()
    probs = lint(cmd)
    for p in probs:
        print(f"CMDLINT {p}")
    print("cmdlint: FAIL" if probs else "cmdlint: OK")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
