"""CLI entrypoint: train-seller-stage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.ai.seller_stage.train import train_seller_stage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train-seller-stage",
        description="Train seller lifecycle classifier on backtest features.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to backtest manifest.json from assemble-backtest-dataset",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/training/seller_stage",
        help="Directory for metrics.json and training_log.json",
    )
    parser.add_argument("--seed", type=int, default=138, help="Random seed for reproducibility")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = train_seller_stage(manifest, args.output_dir, seed=args.seed)
    print(f"Wrote metrics to {result.metrics_path}")
    print(f"  precision={result.metrics['precision']:.4f} recall_macro={result.metrics['recall_macro']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
