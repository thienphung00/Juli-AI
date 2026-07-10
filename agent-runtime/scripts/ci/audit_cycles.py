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
    args = parser.parse_args()

    modules = parse_architecture_map()
    graph = collect_import_graph(modules)
    cycles: list[list[str]] = []
    for component in tarjan_scc(graph):
        if len(component) > 1:
            cycles.append(sorted(component))
        elif component[0] in graph.get(component[0], set()) and component[0] in graph[component[0]]:
            cycles.append(component)

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
