"""CLI entrypoint: train-ad."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.modules.ml.ad_performance.train import train_ad_performance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train-ad",
        description="Train ad performance analyzer on backtest campaign metrics.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to backtest manifest.json from assemble-backtest-dataset",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/training/ad_performance",
        help="Directory for metrics.json and training_log.json",
    )
    parser.add_argument("--seed", type=int, default=140, help="Random seed for reproducibility")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = train_ad_performance(manifest, args.output_dir, seed=args.seed)
    print(f"Wrote metrics to {result.metrics_path}")
    print(f"  ROAS MAPE={result.metrics['roas_mape']:.4f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
