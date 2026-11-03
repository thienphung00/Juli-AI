"""Convert a shopeeanalytics.com browser capture into the keyword collection format (ADR-119).

The owner looks keywords up on shopeeanalytics.com in their own browser (logged in to a free
account; anonymous visitors get 5 lookups a day). Juli never fetches the site. This script
turns the capture into the upload file for Juli Ops › shop › Shopee › Từ khóa ("Tải lên kết
quả tra cứu"); nothing is sent anywhere.

    # Raw capture -> collection file (date from the folder name YYYY-MM-DD, or --collected-on).
    python scripts/shopeeanalytics_keywords.py RAW.jsonl -o shopeeanalytics.jsonl

    # A seed the site really answered with nothing: mark it, or it is recorded as blocked.
    python scripts/shopeeanalytics_keywords.py RAW.jsonl --no-match "cọ rửa tre" -o OUT.jsonl

    # Check a collection file written by hand.
    python scripts/shopeeanalytics_keywords.py --check OUT.jsonl

Raw capture, one line per looked-up keyword::

    {"kw": "...", "sum": "1.250", "n": "8",
     "rows": ["keyword | volume | trend | min CPC | max CPC | difficulty | competition |
               opportunity"]}

Collection format (one line per seed; numbers are plain JSON numbers)::

    {"source": "shopeeanalytics", "collected_on": "YYYY-MM-DD", "seed": "...",
     "status": "ok" | "blocked" | "no_match", "total_volume": int | null,
     "rows": [{"keyword", "volume", "cpc_min", "cpc_max", "difficulty", "competition",
               "opportunity"}]}

An empty result (no rows, or the table's "Không có từ khóa khớp bộ lọc") becomes ``blocked``
unless the seed is passed with ``--no-match``: it is never zero demand. The summary prints
counts per status, never keywords.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from juli_backend.services.shop_keywords.collection import (
    CollectionError,
    dump_jsonl,
    from_raw,
    normalize_keyword,
    parse_jsonl,
)

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def collected_on_for(raw_path: Path, given: str | None) -> date:
    """``--collected-on``, else the capture folder's own ``YYYY-MM-DD`` name."""
    if given:
        return date.fromisoformat(given)
    folder = raw_path.resolve().parent.name
    if _DAY.match(folder):
        return date.fromisoformat(folder)
    raise SystemExit("no --collected-on and the folder name is not YYYY-MM-DD")


def convert(text: str, collected_on: date, no_match: frozenset[str]) -> str:
    records = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"line {n}: not JSON ({exc.msg})") from None
        records.append(from_raw(raw, collected_on=collected_on, no_match=no_match))
    return dump_jsonl(records)


def _summary(text: str) -> str:
    counts = Counter(r.status for r in parse_jsonl(text))
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no records"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw", nargs="?", type=Path, help="raw capture (JSON Lines)")
    parser.add_argument("--collected-on", help="YYYY-MM-DD (default: the folder name)")
    parser.add_argument("--no-match", action="append", default=[], help="seed with no result")
    parser.add_argument("-o", "--output", type=Path, help="write here (default: stdout)")
    parser.add_argument("--check", type=Path, help="validate a collection file and stop")
    args = parser.parse_args(argv)

    if args.check:
        try:
            print(_summary(args.check.read_text("utf-8")), file=sys.stderr)
        except CollectionError as exc:
            print("\n".join(exc.errors), file=sys.stderr)
            return 1
        return 0
    if args.raw is None:
        parser.error("a raw capture file is required (or --check FILE)")
    no_match = frozenset(normalize_keyword(s) for s in args.no_match)
    out = convert(
        args.raw.read_text("utf-8"), collected_on_for(args.raw, args.collected_on), no_match
    )
    if args.output:
        args.output.write_text(out, "utf-8")
    else:
        sys.stdout.write(out)
    print(_summary(out), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
