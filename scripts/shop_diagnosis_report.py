#!/usr/bin/env python3
"""Build the shop diagnosis report offline from a shop snapshot (ADR-108).

No network: reads the folder ``scripts/shop_diagnosis_fetch.py`` wrote and writes
``report.html`` (Vietnamese page), ``report.json`` (every number) and
``message.md`` (seller message draft) into the snapshot folder, or ``--out``.
The ranking of the five hero products is asked interactively unless
``--ranking`` is given::

    python scripts/shop_diagnosis_report.py ~/.juli-shop-snapshots/fujiwa/2026-10-06
    python scripts/shop_diagnosis_report.py <snapshot> --ranking 30d --end 2026-10-05

The logic is ``juli_backend.services.shop_diagnosis``; this wrapper owns the
prompt and the file writes.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

RANKING_PROMPT = (
    "Xếp hạng 5 sản phẩm chủ lực theo:\n"
    "  1) GMV 60 ngày gộp (mặc định)\n"
    "  2) GMV 30 ngày gần nhất\n"
    "Chọn [1/2]: "
)


def ask_ranking(read: Callable[[str], str] = input) -> str:
    """``"60d"`` unless the operator answers 2."""
    answer = read(RANKING_PROMPT).strip()
    return "30d" if answer in ("2", "30d", "30") else "60d"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("snapshot", type=Path, help="shop snapshot folder")
    parser.add_argument("--ranking", choices=("60d", "30d"), default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--out", type=Path, default=None, help="defaults to the snapshot folder")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, read: Callable[[str], str] = input) -> int:
    from juli_backend.services.shop_diagnosis import (
        Ranking,
        build_message,
        build_report,
        load_snapshot,
        render_html,
    )

    args = _parse_args(argv)
    ranking = Ranking(args.ranking or ask_ranking(read))
    report = build_report(load_snapshot(args.snapshot, args.end), ranking)
    out = args.out or args.snapshot
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_html(report), encoding="utf-8")
    (out / "report.json").write_text(report.to_json(), encoding="utf-8")
    (out / "message.md").write_text(build_message(report), encoding="utf-8")
    for name in ("report.html", "report.json", "message.md"):
        print(f"wrote {out / name}")
    return 0


def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "backend" / "src"))
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
