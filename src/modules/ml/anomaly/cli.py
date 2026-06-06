"""CLI entrypoint: train-anomaly."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.modules.ml.anomaly.train import train_anomaly


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train-anomaly",
        description="Train buyer-behavior anomaly detector on backtest features and labels.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to backtest manifest.json from assemble-backtest-dataset",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/training/anomaly",
        help="Directory for metrics.json and training_log.json",
    )
    parser.add_argument("--seed", type=int, default=139, help="Random seed for reproducibility")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = train_anomaly(manifest, args.output_dir, seed=args.seed)
    per_class = result.metrics["per_class"]
    print(f"Wrote metrics to {result.metrics_path}")
    for label in ("item_swap", "empty_return"):
        stats = per_class[label]
        print(
            f"  {label}: precision={stats['precision']:.4f} recall={stats['recall']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
