#!/usr/bin/env python3
"""Alert on Demo KPI staleness, not on endpoint health (#853).

`GET /v1/demo/analytics` returns 200 with entirely plausible numbers whether or not
those numbers are current, so uptime checks cannot see a freshness failure. On
2026-08-06 the envelope went un-recomputed for over 25 hours and nothing surfaced it.

This checks two distinct things, because they fail independently:

  envelope age   — how long since gold last ran (`computed_at`). Catches a reconcile
                   that is dead or was never dispatched.
  source age     — how long since the data behind the KPIs last advanced
                   (`source_freshness`). Catches an upstream fetch that is failing
                   while gold keeps recomputing on schedule, which reads as perfectly
                   healthy on `computed_at` alone.

Exit codes are distinct so the caller can say which fault occurred:

  0  fresh
  1  stale            — endpoint healthy, data is not
  2  unreachable/malformed  — a different fault needing a different response
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

# The reconcile runs hourly. Three hours leaves room for a slow run (the slowest
# observed took 2244.9s) without tolerating a dead one. Kept equal to the orders
# entry in SOURCE_STALE_AFTER_SECONDS so the alarm and the envelope cannot disagree
# about what "stale" means.
ENVELOPE_MAX_AGE_SECONDS = 3 * 60 * 60

USER_AGENT = "juli-kpi-freshness-check/1.0"

EXIT_FRESH = 0
EXIT_STALE = 1
EXIT_UNREACHABLE = 2


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def evaluate(payload: dict[str, Any], *, now: datetime) -> tuple[int, list[str]]:
    """Return (exit_code, human-readable reasons)."""
    problems: list[str] = []

    raw_computed_at = payload.get("computed_at")
    if not raw_computed_at:
        return EXIT_UNREACHABLE, ["payload has no computed_at — not a KPI envelope"]

    try:
        computed_at = _parse_iso(raw_computed_at)
    except ValueError:
        return EXIT_UNREACHABLE, [f"computed_at is not a timestamp: {raw_computed_at!r}"]

    envelope_age = int((now - computed_at).total_seconds())
    if envelope_age > ENVELOPE_MAX_AGE_SECONDS:
        problems.append(
            f"envelope is {envelope_age // 60}m old (limit {ENVELOPE_MAX_AGE_SECONDS // 60}m) "
            f"— the reconcile is not completing"
        )

    # source_freshness is absent on envelopes written before this field shipped;
    # treat that as "cannot tell" rather than silently passing.
    freshness = payload.get("source_freshness")
    if freshness is None:
        problems.append("payload has no source_freshness — cannot verify the data behind the KPIs")
        return EXIT_STALE if problems else EXIT_FRESH, problems

    for source, entry in sorted(freshness.items()):
        if entry.get("stale"):
            age = entry.get("age_seconds")
            age_text = f"{age // 3600}h" if isinstance(age, int) else "unknown"
            problems.append(f"{source} has not advanced in {age_text} — upstream fetch is failing")

    stale_kpis = sorted(
        metric_id
        for metric_id, kpi in (payload.get("kpis") or {}).items()
        if kpi.get("stale") and kpi.get("availability") == "available"
    )
    if stale_kpis:
        problems.append(f"serving stale values for: {', '.join(stale_kpis)}")

    return (EXIT_STALE if problems else EXIT_FRESH), problems


def fetch(url: str, timeout: int) -> dict[str, Any]:
    # An explicit User-Agent is required, not cosmetic: the edge rejects the default
    # "Python-urllib/x.y" with 403, which would make this alarm page UNREACHABLE on
    # every run and train everyone to ignore it.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        return json.loads(resp.read().decode())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Demo analytics endpoint to poll")
    parser.add_argument(
        "--from-file",
        help="Read a payload from a file instead of the network (used by the tests)",
    )
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args(argv)

    if not args.url and not args.from_file:
        parser.error("one of --url or --from-file is required")

    try:
        if args.from_file:
            with open(args.from_file) as handle:
                payload = json.load(handle)
        else:
            payload = fetch(args.url, args.timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"UNREACHABLE: {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    except json.JSONDecodeError as exc:
        print(f"UNREACHABLE: response was not JSON — {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE

    code, problems = evaluate(payload, now=datetime.now(tz=UTC))
    if code == EXIT_FRESH:
        print("FRESH: envelope and all sources are within their thresholds")
    else:
        label = "STALE" if code == EXIT_STALE else "UNREACHABLE"
        for problem in problems:
            print(f"{label}: {problem}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
