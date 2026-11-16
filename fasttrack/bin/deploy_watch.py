#!/usr/bin/env python3
"""fasttrack/bin/deploy_watch.py <tag> [--interval 60] [--once]

Read-only: polls the Fast-track deploy run for <tag> until it concludes, records the
result in the shared state (fasttrack/state.py), and on failure prints every failing
job + step, so nobody has to ask "did the deploy pass?". Agents may run this (e.g.
under Monitor); it never tags, merges or pushes.
"""

from __future__ import annotations

import argparse
import sys
import time
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "state", Path(__file__).resolve().parent.parent / "state.py"
)
assert _spec and _spec.loader
state = importlib.util.module_from_spec(_spec)
sys.modules["state"] = state
_spec.loader.exec_module(state)


def failing_steps(run_id: int) -> list[str]:
    jobs = state.github_get(f"/repos/{state.REPO}/actions/runs/{run_id}/jobs?per_page=100").get(
        "jobs", []
    )
    out = []
    for j in jobs:
        if j.get("conclusion") not in ("success", "skipped", None):
            steps = [s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"]
            out.append(f"{j['name']}: {' / '.join(steps) or j.get('conclusion')}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("tag")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    while True:
        run = state.deploy_run_for_tag(a.tag)
        if run is None:
            print(f"{a.tag}: no deploy run yet")
        else:
            concl = run.get("conclusion")
            print(
                f"{a.tag}: run {run['id']} status={run.get('status')} conclusion={concl} {run.get('html_url')}"
            )
            if concl:
                with state.locked_state() as st:
                    for t in st["tags"]:
                        if t["tag"] == a.tag:
                            t.update(conclusion=concl, run_id=run["id"])
                state.event("tag-result", tag=a.tag, conclusion=concl, run_id=run["id"])
                if concl != "success":
                    for line in failing_steps(run["id"]):
                        print(f"  FAILED {line}")
                    return 1
                return 0
        if a.once:
            return 2
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
