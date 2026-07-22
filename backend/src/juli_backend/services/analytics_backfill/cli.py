"""CLI entrypoint: backfill-analytics-history (#470) + coverage report (#471)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.analytics_backfill.coverage import (
    coverage_report_to_json,
    coverage_report_to_markdown,
    generate_coverage_report,
)
from juli_backend.services.analytics_backfill.live_runner import (
    BackfillPartitionFailed,
    execute_live_backfill,
    orchestrator_result_to_exit_code,
    summary_to_text,
)
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate env, credential, and shop-id match without Partner calls",
    )
    return parser


def _parse_date(value: str, *, arg_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        msg = f"Invalid {arg_name} date {value!r}; expected YYYY-MM-DD"
        raise SystemExit(msg) from exc


def build_coverage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analytics-coverage-report",
        description="Phase 2.9 analytics backfill coverage + exit gate report (#471).",
    )
    parser.add_argument(
        "--shop-id",
        required=True,
        help="Shop UUID to report on",
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
        "--output",
        help="Optional path to write JSON artifact (gitignored if large)",
    )
    return parser


async def _run_coverage_report(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    start_date: date,
    end_date: date,
    output_path: Path | None,
) -> int:
    report = await generate_coverage_report(
        session,
        shop_id=shop_id,
        start_date=start_date,
        end_date=end_date,
    )
    print(coverage_report_to_json(report))
    print()
    print(coverage_report_to_markdown(report))
    if output_path is not None:
        output_path.write_text(coverage_report_to_json(report), encoding="utf-8")
    return 0 if report.exit_ready else 1


def coverage_main(argv: list[str] | None = None) -> int:
    """Run coverage report against DATABASE_URL."""
    args = build_coverage_parser().parse_args(argv)
    try:
        shop_id = uuid.UUID(args.shop_id)
    except ValueError as exc:
        raise SystemExit(f"Invalid --shop-id UUID: {args.shop_id!r}") from exc

    start_date = _parse_date(args.start, arg_name="--start")
    end_date = _parse_date(args.end, arg_name="--end")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required for coverage report")

    output_path = Path(args.output) if args.output else None

    async def _main() -> int:
        engine = create_async_engine(async_database_url(database_url))
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                return await _run_coverage_report(
                    session,
                    shop_id=shop_id,
                    start_date=start_date,
                    end_date=end_date,
                    output_path=output_path,
                )
        finally:
            await engine.dispose()

    return asyncio.run(_main())


async def _run_live_backfill_session(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    start_date: date,
    end_date: date,
    buckets: tuple[str, ...],
    dry_run: bool,
):
    return await execute_live_backfill(
        session,
        shop_id=shop_id,
        start_date=start_date,
        end_date=end_date,
        buckets=buckets,
        dry_run=dry_run,
    )


def backfill_main(argv: list[str] | None = None) -> int:
    """Run live Fujiwa analytics backfill via DATABASE_URL and TikTok env vars."""
    args = build_parser().parse_args(argv)
    try:
        shop_id = uuid.UUID(args.shop_id)
    except ValueError as exc:
        raise SystemExit(f"Invalid --shop-id UUID: {args.shop_id!r}") from exc

    start_date = _parse_date(args.start, arg_name="--start")
    end_date = _parse_date(args.end, arg_name="--end")
    try:
        buckets = validate_buckets([b.strip() for b in args.buckets.split(",") if b.strip()])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required for analytics backfill")

    async def _main() -> int:
        engine = create_async_engine(async_database_url(database_url))
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                try:
                    summary = await _run_live_backfill_session(
                        session,
                        shop_id=shop_id,
                        start_date=start_date,
                        end_date=end_date,
                        buckets=buckets,
                        dry_run=args.dry_run,
                    )
                except BackfillPartitionFailed as exc:
                    await session.rollback()
                    print(f"analytics_backfill_error stopped_reason=error error={exc}")
                    return 1
                except Exception as exc:
                    await session.rollback()
                    print(f"analytics_backfill_error stopped_reason=error error={exc}")
                    return 1

                print(summary_to_text(summary))
                return orchestrator_result_to_exit_code(summary.result)
        finally:
            await engine.dispose()

    return asyncio.run(_main())


def main(argv: list[str] | None = None) -> int:
    """Dispatch legacy backfill args or ``coverage`` subcommand."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "coverage":
        return coverage_main(argv[1:])
    return backfill_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
