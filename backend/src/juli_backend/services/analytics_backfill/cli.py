"""CLI entrypoint: backfill-analytics-history (#470)."""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date

from juli_backend.services.analytics_backfill.orchestrator import (
    BACKFILL_WINDOW_START,
    DEFAULT_BUCKET_ORDER,
    validate_buckets,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill-analytics-history",
        description=(
            "Operator-invoked analytics historical backfill across "
            "revenue/live/product/catalog partitions."
        ),
    )
    parser.add_argument(
        "--shop-id",
        required=True,
        help="Shop UUID to backfill",
    )
    parser.add_argument(
        "--start",
        default=BACKFILL_WINDOW_START.isoformat(),
        help=f"Inclusive start date (default {BACKFILL_WINDOW_START.isoformat()})",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Inclusive end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--buckets",
        default=",".join(DEFAULT_BUCKET_ORDER),
        help="Comma-separated bucket allowlist (default: revenue,live,product,catalog)",
    )
    return parser


def _parse_date(value: str, *, arg_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        msg = f"Invalid {arg_name} date {value!r}; expected YYYY-MM-DD"
        raise SystemExit(msg) from exc


def main(argv: list[str] | None = None) -> int:
    """Validate operator args; partition wiring invokes ``backfill_analytics_history``."""
    args = build_parser().parse_args(argv)
    try:
        shop_id = uuid.UUID(args.shop_id)
    except ValueError as exc:
        raise SystemExit(f"Invalid --shop-id UUID: {args.shop_id!r}") from exc

    start_date = _parse_date(args.start, arg_name="--start")
    end_date = _parse_date(args.end, arg_name="--end")
    buckets = validate_buckets([b.strip() for b in args.buckets.split(",") if b.strip()])

    print(
        f"Validated analytics backfill: shop_id={shop_id} "
        f"start={start_date} end={end_date} buckets={','.join(buckets)}"
    )
    print(
        "Run programmatically via backfill_analytics_history() with a DB session "
        "and partition runner wiring (see MODULE.md)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
