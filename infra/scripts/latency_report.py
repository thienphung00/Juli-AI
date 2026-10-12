#!/usr/bin/env python3
"""Per-route server-side latency percentiles from the API's JSON logs (fast track P21).

Reads log lines on stdin, keeps the ``http_request`` events written by
``juli_backend.api.middleware.RequestTimingMiddleware``, groups them by (method, route)
and prints count, p50, p90, p95, p99 and max in milliseconds, slowest p95 first.

On the VPS (see docs/runbooks/ops-console-runbook.md, "Đo latency"):

    journalctl -u 'juli-api-candidate-*' --since '24 hours ago' -o cat \\
      | python3 /root/releases/current/infra/scripts/latency_report.py --prefix /v1/ops

Stdlib only, so it runs with the system python3. Lines that are not JSON (uvicorn
banners, tracebacks) are skipped.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TextIO

EVENT = "http_request"
PERCENTILES = (50, 90, 95, 99)


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile of an ascending, non-empty sequence."""
    if not sorted_values:
        raise ValueError("percentile of an empty sequence")
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def collect(lines: Iterable[str]) -> dict[tuple[str, str], list[float]]:
    """Group ``duration_ms`` by (method, route), ignoring anything else."""
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("event") != EVENT:
            continue
        duration = record.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            continue
        method = str(record.get("method", "?"))
        route = str(record.get("route", "unmatched"))
        groups[(method, route)].append(float(duration))
    return groups


@dataclass(frozen=True)
class Row:
    method: str
    route: str
    count: int
    p50: float
    p90: float
    p95: float
    p99: float
    max: float


def summarise(
    groups: dict[tuple[str, str], list[float]],
    *,
    prefix: str | None = None,
    min_count: int = 1,
) -> list[Row]:
    rows: list[Row] = []
    for (method, route), durations in groups.items():
        # Routes inside the mounted /v1 sub-app may be logged without the mount
        # prefix ("/ops/me"), so "/v1/ops" also matches them.
        if prefix and not (route.startswith(prefix) or ("/v1" + route).startswith(prefix)):
            continue
        if len(durations) < min_count:
            continue
        ordered = sorted(durations)
        p50, p90, p95, p99 = (percentile(ordered, pct) for pct in PERCENTILES)
        rows.append(Row(method, route, len(ordered), p50, p90, p95, p99, ordered[-1]))
    rows.sort(key=lambda r: (-r.p95, r.route, r.method))
    return rows


def render(rows: Sequence[Row], out: TextIO) -> None:
    if not rows:
        out.write("No http_request events matched.\n")
        return
    width = max(len("endpoint"), *(len(f"{r.method} {r.route}") for r in rows))
    columns = ("count", "p50", "p90", "p95", "p99", "max")
    header = "endpoint".ljust(width) + "".join(f"{c:>10}" for c in columns)
    out.write(header + "\n")
    out.write("-" * len(header) + "\n")
    for r in rows:
        numbers = (r.p50, r.p90, r.p95, r.p99, r.max)
        out.write(
            f"{r.method} {r.route}".ljust(width)
            + f"{r.count:>10}"
            + "".join(f"{n:>10.1f}" for n in numbers)
            + "\n"
        )
    out.write("(ms; nearest-rank percentiles; sorted by p95 desc)\n")


def main(
    argv: Sequence[str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--prefix", help="only routes whose template starts with this, e.g. /v1/ops"
    )
    parser.add_argument("--min-count", type=int, default=1, help="hide routes with fewer requests")
    args = parser.parse_args(argv)
    rows = summarise(collect(stdin or sys.stdin), prefix=args.prefix, min_count=args.min_count)
    render(rows, stdout or sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
