#!/usr/bin/env python3
"""fasttrack/gate_status.py <tree-or-commit> — is the local deploy gate complete for this tree?

Reads <state dir>/predeploy/<tree>/job-<name>.json written by fasttrack/predeploy.sh.
Valid when every gate job has a record that is PASS, not --fast, from a clean tree that
contained the deploy tip at the time. Exit 0 = valid for a tag, 1 = not.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

GATE_JOBS = ("heads", "frontend", "static", "unit", "check")


def resolve_tree(ref: str) -> str:
    out = subprocess.run(["git", "rev-parse", f"{ref}^{{tree}}"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ref


def default_state_dir() -> Path:
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True
    ).stdout.strip()
    return Path(common).resolve() / "fasttrack-state"


def gate(tree: str, state_dir: Path) -> tuple[bool, list[tuple[str, str]]]:
    rows: list[tuple[str, str]] = []
    ok = True
    for job in GATE_JOBS:
        f = state_dir / "predeploy" / tree / f"job-{job}.json"
        if not f.exists():
            rows.append((job, "MISSING — not run for this tree"))
            ok = False
            continue
        r = json.loads(f.read_text())
        problems = []
        if r.get("status") != "PASS":
            problems.append(f"status {r.get('status')} (rc {r.get('rc')})")
        if r.get("mode") == "fast":
            problems.append("fast mode")
        if not r.get("clean"):
            problems.append("dirty tree")
        if not r.get("contains_tip"):
            problems.append(f"did not contain tip {str(r.get('tip'))[:8]}")
        tests = r.get("tests")
        detail = (
            f"PASS {r.get('seconds')}s"
            + (f", {tests} tests" if tests is not None else "")
            + (f", {r['runner']}" if r.get("runner") and r.get("runner") != "serial" else "")
            + f", {r.get('finished_at')}"
        )
        if problems:
            ok = False
            rows.append((job, "INVALID — " + "; ".join(problems)))
        else:
            rows.append((job, detail))
    trial = state_dir / "predeploy" / tree / "xdist-trial.txt"
    if trial.exists():
        first = trial.read_text().splitlines()[:1]
        rows.append(("trial", (first[0] if first else "empty") + " (not gating)"))
    return ok, rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("ref", help="tree hash or any commit-ish")
    p.add_argument("--state-dir", type=Path)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    tree = resolve_tree(a.ref)
    ok, rows = gate(tree, a.state_dir or default_state_dir())
    if a.json:
        print(json.dumps({"tree": tree, "valid": ok, "jobs": dict(rows)}))
    else:
        print(f"gate for tree {tree[:12]}:")
        for job, detail in rows:
            print(f"  {job:9} {detail}")
        print("gate: VALID for tag" if ok else "gate: NOT valid for tag")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
