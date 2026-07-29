#!/usr/bin/env python3
"""Nightly audit: module import cycles via Tarjan SCC."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    VALIDATION_DIR,
    collect_import_graph,
    parse_architecture_map,
    tarjan_scc,
    utc_now_iso,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument(
        "--ci",
        action="store_true",
        help="PR gate mode: print cycle edges to stderr and skip artifact write",
    )
    args = parser.parse_args()

    modules = parse_architecture_map()
    graph = collect_import_graph(modules)
    cycles: list[list[str]] = []
    for component in tarjan_scc(graph):
        if len(component) > 1:
            cycles.append(sorted(component))
        elif component[0] in graph.get(component[0], set()) and component[0] in graph[component[0]]:
            cycles.append(component)

    if args.ci:
        if cycles:
            for idx, cycle in enumerate(cycles, start=1):
                modules_in_cycle = " -> ".join(cycle)
                print(f"cycle={idx} modules={modules_in_cycle}", file=sys.stderr)
            print(f"dependency_cycles: FAIL — {len(cycles)} cycle(s)", file=sys.stderr)
            return 1
        print("dependency_cycles: PASS — no import cycles")
        return 0

    payload = {
        "id": f"audit-cycles-{args.date}",
        "timestamp": utc_now_iso(),
        "cycleCount": len(cycles),
        "cycles": cycles,
        "severity": "CRITICAL" if cycles else "OK",
    }
    out = VALIDATION_DIR / f"audit-cycles-{args.date}.json"
    write_json(out, payload)
    print(f"wrote {out} ({len(cycles)} cycles)")
    return 1 if cycles else 0


if __name__ == "__main__":
    raise SystemExit(main())
