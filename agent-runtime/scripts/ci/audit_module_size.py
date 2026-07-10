#!/usr/bin/env python3
"""Nightly audit: lines of code per module."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    REPO_ROOT,
    VALIDATION_DIR,
    parse_architecture_map,
    utc_now_iso,
    write_json,
)

LOC_WARN = 5000
LOC_CRITICAL = 10000


def count_loc(module_path: str) -> int:
    root = REPO_ROOT / module_path
    if not root.exists():
        return 0
    total = 0
    for py_file in root.rglob("*.py"):
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        total += sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    modules = parse_architecture_map()
    entries: list[dict] = []
    critical = 0
    for module_path, info in modules.items():
        loc = count_loc(module_path)
        severity = "OK"
        if loc >= LOC_CRITICAL:
            severity = "CRITICAL"
            critical += 1
        elif loc >= LOC_WARN:
            severity = "WARNING"
        entries.append({"module": module_path, "tier": info.tier, "loc": loc, "severity": severity})

    payload = {
        "id": f"audit-size-{args.date}",
        "timestamp": utc_now_iso(),
        "entries": entries,
        "criticalCount": critical,
        "severity": "CRITICAL" if critical else "OK",
    }
    out = VALIDATION_DIR / f"audit-size-{args.date}.json"
    write_json(out, payload)
    print(f"wrote {out}")
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
