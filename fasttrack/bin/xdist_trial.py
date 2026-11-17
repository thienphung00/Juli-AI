#!/usr/bin/env python3
"""fasttrack/bin/xdist_trial.py — compare a serial and a pytest-xdist run of the unit suite.

Gate speed-ups phase 1 (owner-approved 2026-11-17): the unit job may move to
``pytest -n 4 --dist loadfile`` only after 3 batches where both runs, on the same tree,
ran the same tests with the same outcomes, no test failed only under xdist, and xdist was
faster. This tool produces that evidence from the two runs' JUnit XML files.

  compare --serial A.xml [B.xml ...] --xdist X.xml [--record trial.jsonl --sha S --tree T --where W]
      Per-test comparison. Several --serial files (CI's 4 shards) are merged. Prints the
      verdict; --record appends one JSON line. Exit 0 whatever the verdict (it is a trial),
      unless --strict, then exit 1 on a mismatch.
  count X.xml --expect N
      Exit 1 unless the run holds exactly N test cases (the xdist gate's no-silent-drop check).
  summary trial.jsonl [--need 3]
      Latest verdict per tree; says whether the trial has its N consecutive OK batches.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import xml.etree.ElementTree as ET  # parses our own pytest output only
from pathlib import Path


def outcomes(paths: list[Path]) -> tuple[dict[str, str], float, float]:
    """(test id -> passed|failed|error|skipped, summed suite seconds, max suite seconds)."""
    res: dict[str, str] = {}
    times: list[float] = []
    for path in paths:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        times.append(sum(float(s.get("time") or 0) for s in suites))
        for case in root.iter("testcase"):
            tid = f"{case.get('classname', '')}::{case.get('name', '')}"
            kind = "passed"
            for child in case:
                if child.tag in ("failure", "error", "skipped"):
                    kind = "failed" if child.tag == "failure" else child.tag
                    break
            res[tid] = kind
    return res, sum(times), max(times, default=0.0)


def compare(serial: dict[str, str], xdist: dict[str, str]) -> dict[str, object]:
    s_ids, x_ids = set(serial), set(xdist)
    bad = {"failed", "error"}
    xdist_only = sorted(t for t in s_ids & x_ids if xdist[t] in bad and serial[t] not in bad)
    serial_only = sorted(t for t in s_ids & x_ids if serial[t] in bad and xdist[t] not in bad)
    changed = sorted(t for t in s_ids & x_ids if serial[t] != xdist[t])

    def count(d: dict[str, str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in d.values():
            out[v] = out.get(v, 0) + 1
        return out

    same_tests = s_ids == x_ids
    ok = same_tests and not changed
    return {
        "ok": ok,
        "serial_counts": count(serial),
        "xdist_counts": count(xdist),
        "missing_in_xdist": sorted(s_ids - x_ids)[:50],
        "extra_in_xdist": sorted(x_ids - s_ids)[:50],
        "xdist_only_failures": xdist_only[:50],
        "serial_only_failures": serial_only[:50],
        "outcome_changes": len(changed),
    }


def cmd_compare(a: argparse.Namespace) -> int:
    serial, s_sum, s_max = outcomes(a.serial)
    xdist, x_sum, _ = outcomes([a.xdist])
    r = compare(serial, xdist)
    s_wall = a.serial_seconds if a.serial_seconds is not None else s_max
    x_wall = a.xdist_seconds if a.xdist_seconds is not None else x_sum
    r.update(
        at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sha=a.sha,
        tree=a.tree,
        where=a.where,
        serial_seconds=round(s_wall, 1),
        serial_runner_seconds=round(s_sum, 1),
        xdist_seconds=round(x_wall, 1),
        faster=bool(x_wall) and x_wall < s_wall,
    )
    r["ok"] = bool(r["ok"]) and bool(r["faster"])
    print(
        f"xdist trial ({a.where}): {'OK' if r['ok'] else 'MISMATCH'} — "
        f"serial {r['serial_counts']} in {r['serial_seconds']}s, "
        f"xdist {r['xdist_counts']} in {r['xdist_seconds']}s"
    )
    for key in (
        "missing_in_xdist",
        "extra_in_xdist",
        "xdist_only_failures",
        "serial_only_failures",
    ):
        listed = r[key]
        for t in listed if isinstance(listed, list) else []:
            print(f"  {key}: {t}")
    if not r["faster"]:
        print("  xdist was not faster")
    if a.record:
        with a.record.open("a") as f:
            f.write(json.dumps(r) + "\n")
    return 1 if (a.strict and not r["ok"]) else 0


def cmd_count(a: argparse.Namespace) -> int:
    got = len(outcomes([a.xml])[0])
    if got != a.expect:
        print(f"FAIL: {a.xml} holds {got} test cases, expected {a.expect}")
        return 1
    print(f"count OK: {got} test cases")
    return 0


def cmd_summary(a: argparse.Namespace) -> int:
    if not a.jsonl.exists():
        print("xdist trial: no runs recorded yet")
        return 1
    latest: dict[str, dict] = {}
    for line in a.jsonl.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            latest[f"{r.get('where')}:{r.get('tree')}"] = r
    runs = sorted(latest.values(), key=lambda r: r.get("at", ""))
    streak = 0
    for r in reversed(runs):
        if not r.get("ok"):
            break
        streak += 1
    for r in runs[-10:]:
        print(
            f"  {r.get('at')} {r.get('where'):5} tree {str(r.get('tree'))[:10]} "
            f"{'OK ' if r.get('ok') else 'BAD'} serial {r.get('serial_seconds')}s "
            f"xdist {r.get('xdist_seconds')}s xdist-only failures {len(r.get('xdist_only_failures', []))}"
        )
    done = streak >= a.need
    print(
        f"xdist trial: {streak} consecutive OK of {a.need} needed — {'COMPLETE' if done else 'running'}"
    )
    return 0 if done else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--serial", type=Path, nargs="+", required=True)
    c.add_argument("--xdist", type=Path, required=True)
    c.add_argument("--serial-seconds", type=float)
    c.add_argument("--xdist-seconds", type=float)
    c.add_argument("--record", type=Path)
    c.add_argument("--sha", default="")
    c.add_argument("--tree", default="")
    c.add_argument("--where", default="local")
    c.add_argument("--strict", action="store_true")
    n = sub.add_parser("count")
    n.add_argument("xml", type=Path)
    n.add_argument("--expect", type=int, required=True)
    s = sub.add_parser("summary")
    s.add_argument("jsonl", type=Path)
    s.add_argument("--need", type=int, default=3)
    a = p.parse_args(argv)
    return {"compare": cmd_compare, "count": cmd_count, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
