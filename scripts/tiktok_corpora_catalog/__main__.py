"""CLI entry point: regenerate TikTok corpora catalog JSON files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tiktok_corpora_catalog.builder import build_corpus_root, write_catalogs

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "integrations" / "tiktok_corpora"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate TikTok corpora catalog JSON from markdown front matter."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory for *-catalog.json (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Override corpus root (default: JULI_TIKTOK_CORPORA_ROOT or ADR-051 path)",
    )
    args = parser.parse_args(argv)

    corpus_root = args.corpus_root or build_corpus_root()
    if not corpus_root.is_dir():
        print(f"error: corpus root not found: {corpus_root}", file=sys.stderr)
        return 1

    counts = write_catalogs(args.output, corpus_root=corpus_root)
    for corpus, count in sorted(counts.items()):
        print(f"{corpus}-catalog.json: {count} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
