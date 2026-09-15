#!/usr/bin/env python3
"""Nightly audit: module import cycles via Tarjan SCC."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    KNOWN_CYCLE_EDGES,
    VALIDATION_DIR,
    collect_import_graph,
    graph_without_allowlisted_edges,
    parse_architecture_map,
    tarjan_scc,
    utc_now_iso,
    write_json,
)


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    for component in tarjan_scc(graph):
        if len(component) > 1:
            cycles.append(sorted(component))
        elif component[0] in graph.get(component[0], set()):
            cycles.append(component)
    return cycles


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
    full_graph = collect_import_graph(modules)
    # Same allowlist the `module_boundaries` validate gate applies, imported
    # from `common` rather than restated -- when #1859 taught the parser to
    # read the real tree, this script and that gate disagreed about the one
    # pre-existing TikTok/auth cycle, and only a shared definition keeps them
    # from drifting again.
    graph = graph_without_allowlisted_edges(full_graph, KNOWN_CYCLE_EDGES)
    cycles = _find_cycles(graph)
    known_cycles = [c for c in _find_cycles(full_graph) if c not in cycles]

    # Printed on both paths: an excused cycle stays visible in the log rather
    # than vanishing because it is allowlisted.
    for idx, cycle in enumerate(known_cycles, start=1):
        print(f"known-cycle={idx} modules={' -> '.join(cycle)}", file=sys.stderr)

    if args.ci:
        if cycles:
            for idx, cycle in enumerate(cycles, start=1):
                modules_in_cycle = " -> ".join(cycle)
                print(f"cycle={idx} modules={modules_in_cycle}", file=sys.stderr)
            print(f"dependency_cycles: FAIL — {len(cycles)} cycle(s)", file=sys.stderr)
            return 1
        print(f"dependency_cycles: PASS — no import cycles ({len(known_cycles)} allowlisted)")
        return 0

    payload = {
        "id": f"audit-cycles-{args.date}",
        "timestamp": utc_now_iso(),
        "cycleCount": len(cycles),
        "cycles": cycles,
        # The nightly artifact records the excused cycles too, so the debt is
        # counted somewhere even while the PR gate stays green on it.
        "knownCycleCount": len(known_cycles),
        "knownCycles": known_cycles,
        "severity": "CRITICAL" if cycles else "OK",
    }
    out = VALIDATION_DIR / f"audit-cycles-{args.date}.json"
    write_json(out, payload)
    print(f"wrote {out} ({len(cycles)} cycles)")
    return 1 if cycles else 0


if __name__ == "__main__":
    raise SystemExit(main())
