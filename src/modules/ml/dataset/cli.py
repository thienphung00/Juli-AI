"""CLI entrypoint: assemble-backtest-dataset."""

from __future__ import annotations

import argparse
import sys

from src.modules.ml.dataset.assembler import assemble_backtest_dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assemble-backtest-dataset",
        description="Assemble versioned backtest parquet datasets for Phase 1.5 ML training.",
    )
    parser.add_argument(
        "--output-dir",
        default="backtest/revenue_leakage",
        help="Directory for parquet files and manifest.json",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for synthetic data")
    parser.add_argument("--n-shops", type=int, default=5, help="Number of synthetic shops")
    parser.add_argument(
        "--orders-per-shop",
        type=int,
        default=100,
        help="Synthetic orders per shop",
    )
    parser.add_argument(
        "--return-rate",
        type=float,
        default=0.08,
        help="Fraction of orders that generate a return",
    )
    parser.add_argument(
        "--ads-days",
        type=int,
        default=30,
        help="Days of campaign/day ad history per shop",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = assemble_backtest_dataset(
        args.output_dir,
        seed=args.seed,
        n_shops=args.n_shops,
        orders_per_shop=args.orders_per_shop,
        return_rate=args.return_rate,
        ads_days=args.ads_days,
    )
    counts = result["manifest"]["row_counts"]
    print(f"Assembled dataset at {args.output_dir}")
    print(f"  orders={counts['orders']} returns={counts['returns']} ads={counts['ads']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
