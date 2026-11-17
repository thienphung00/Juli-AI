#!/usr/bin/env python3
"""fasttrack/gate_status.py <tree-or-commit> [--no-ci] — is the deploy gate complete for this tree?

The gate is complete when EITHER source says so (phase 2, owner 2026-11-17):

  ci     a GitHub run of .github/workflows/fasttrack-pr.yml on a PR from this repository
         concluded success and its `gate` job uploaded the artifact fasttrack-gate-<tree>.
         That job runs only when heads, frontend, static, unit (4 shards) and check
         (4 shards, throwaway Postgres) all passed on the PR's merge commit.
  local  <state dir>/predeploy/<tree>/job-<name>.json written by fasttrack/predeploy.sh:
         every gate job PASS, not --fast, from a clean tree that contained the deploy tip.

Keyed by TREE, so a merge commit whose tree equals the tested PR merge commit is covered.
--no-ci skips the GitHub lookup (predeploy.sh uses it for its local verdict).
Exit 0 = valid for a tag, 1 = not.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

GATE_JOBS = ("heads", "frontend", "static", "unit", "check")
PR_WORKFLOW = ".github/workflows/fasttrack-pr.yml"
ARTIFACT_PREFIX = "fasttrack-gate-"


def resolve_tree(ref: str) -> str:
    out = subprocess.run(["git", "rev-parse", f"{ref}^{{tree}}"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ref


def default_state_dir() -> Path:
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True
    ).stdout.strip()
    return Path(common).resolve() / "fasttrack-state"


def _github_get() -> Callable[[str], Any]:
    spec = importlib.util.spec_from_file_location(
        "state", Path(__file__).resolve().parent / "state.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.github_get


def ci_gate(tree: str, get: Callable[[str], Any], repo: str) -> tuple[bool, str]:
    """(valid, detail) from GitHub: a successful PR-workflow run that recorded this tree."""
    arts = get(f"/repos/{repo}/actions/artifacts?name={ARTIFACT_PREFIX}{tree}&per_page=20")
    rejected: list[str] = []
    for art in arts.get("artifacts", []):
        if art.get("expired"):
            rejected.append("artifact expired")
            continue
        wr = art.get("workflow_run") or {}
        if not wr.get("id"):
            continue
        if wr.get("head_repository_id") != wr.get("repository_id"):
            rejected.append(f"run {wr['id']} is from a fork")
            continue
        run = get(f"/repos/{repo}/actions/runs/{wr['id']}")
        if run.get("path") != PR_WORKFLOW or run.get("event") != "pull_request":
            rejected.append(f"run {wr['id']} is not {PR_WORKFLOW} on a pull_request")
            continue
        if run.get("conclusion") != "success":
            rejected.append(f"run {wr['id']} concluded {run.get('conclusion')}")
            continue
        prs = ",".join(f"#{pr.get('number')}" for pr in run.get("pull_requests") or [])
        return True, f"PASS run {run['id']} {prs} {run.get('updated_at')} {run.get('html_url')}"
    if rejected:
        return False, "NOT valid — " + "; ".join(rejected)
    return False, "MISSING — no passing fasttrack-pr.yml run for this tree"


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
    p.add_argument("--no-ci", action="store_true", help="local records only, no GitHub lookup")
    a = p.parse_args(argv)
    tree = resolve_tree(a.ref)
    local_ok, rows = gate(tree, a.state_dir or default_state_dir())
    ci_ok, ci_detail = False, "not checked (--no-ci)"
    if not a.no_ci:
        try:
            ci_ok, ci_detail = ci_gate(tree, _github_get(), "thienphung00/Juli-AI")
        except Exception as exc:  # network / token: the local verdict still stands
            ci_detail = f"could not check GitHub: {str(exc)[:160]}"
    ok = ci_ok or local_ok
    via = "ci" if ci_ok else ("local" if local_ok else None)
    if a.json:
        print(
            json.dumps({"tree": tree, "valid": ok, "via": via, "ci": ci_detail, "jobs": dict(rows)})
        )
    else:
        print(f"gate for tree {tree[:12]}:")
        print(f"  {'ci':9} {ci_detail}")
        print("  local:")
        for job, detail in rows:
            print(f"    {job:9} {detail}")
        print(f"gate: VALID for tag (via {via})" if ok else "gate: NOT valid for tag")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
