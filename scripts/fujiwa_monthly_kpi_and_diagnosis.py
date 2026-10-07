#!/usr/bin/env python3
"""Read-only monthly KPI comparison and TikTok listing diagnoses for chosen products.

Pulls A-34 (shop product performance) for two 30-day windows and the product
diagnoses endpoint, then writes ``monthly_kpi.json`` / ``monthly_kpi.md``.
Every live call is a production-read GET; nothing is written to TikTok.
Examples::

    python scripts/fujiwa_monthly_kpi_and_diagnosis.py \
        --as-of 2026-10-06 --product-ids 1729,1730 --out-dir out/fujiwa-kpi

    # re-analyse files already in --out-dir, no network
    python scripts/fujiwa_monthly_kpi_and_diagnosis.py --replay --out-dir out/fujiwa-kpi \
        --product-ids 1729,1730
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

WINDOW_DAYS = 30
_HOW_TO_SOLVE_MAX = 120

# (label, key, kind) -- kind drives formatting only.
METRIC_ROWS: tuple[tuple[str, str], ...] = (
    ("orders_per_day", "Orders / day"),
    ("gmv", "GMV"),
    ("aov", "AOV"),
    ("items_per_order", "Items / order"),
    ("impressions", "Impressions"),
    ("ctr", "CTR"),
    ("add_to_cart_rate", "Add-to-cart rate"),
    ("ctor", "CTOR"),
    ("refund_share", "Refund share"),
    ("card_ctr", "Product card CTR"),
    ("card_ctor", "Product card CTOR"),
)


def window_metrics(item: dict[str, Any] | None, *, days: int = WINDOW_DAYS) -> dict[str, Any]:
    """KPI block for one A-34 product row; ``None`` ratios mean a zero denominator.

    One implementation, shared with the shop report:
    ``juli_backend.services.optimize_product.shop_report.window_metrics``.
    """
    from juli_backend.services.optimize_product.shop_report import window_metrics as impl

    return impl(item, days=days)


def _change(cur: Decimal | None, prev: Decimal | None) -> dict[str, Decimal | None]:
    from juli_backend.services.optimize_product.shop_report import change

    return change(cur, prev)


def compare_product(
    product_id: str, current_item: dict | None, previous_item: dict | None
) -> dict[str, Any]:
    cur = window_metrics(current_item)
    prev = window_metrics(previous_item)
    return {
        "product_id": product_id,
        "in_current": current_item is not None,
        "in_previous": previous_item is not None,
        "current": cur,
        "previous": prev,
        "change": {key: _change(cur[key], prev[key]) for key, _ in METRIC_ROWS},
    }


def index_products(payload: Any) -> dict[str, dict]:
    products = payload.get("products") if isinstance(payload, dict) else payload
    return {str(p["id"]): p for p in (products or []) if isinstance(p, dict) and p.get("id")}


def build_report(
    product_ids: list[str], current_payload: Any, previous_payload: Any
) -> list[dict[str, Any]]:
    cur, prev = index_products(current_payload), index_products(previous_payload)
    return [compare_product(pid, cur.get(pid), prev.get(pid)) for pid in product_ids]


def diagnosis_rows(payload: Any) -> list[dict[str, str]]:
    """Flatten ``data.products[].diagnoses[].diagnosis_results[]`` into table rows."""
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    rows: list[dict[str, str]] = []
    for product in data.get("products") or []:
        for diag in product.get("diagnoses") or []:
            for result in diag.get("diagnosis_results") or []:
                solve = str(result.get("how_to_solve") or "")
                if len(solve) > _HOW_TO_SOLVE_MAX:
                    solve = solve[: _HOW_TO_SOLVE_MAX - 3] + "..."
                rows.append(
                    {
                        "product_id": str(product.get("id")),
                        "field": str(diag.get("field")),
                        "code": str(result.get("code")),
                        "how_to_solve": solve,
                    }
                )
    return rows


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


_RATIO_KEYS = {"ctr", "add_to_cart_rate", "ctor", "refund_share", "card_ctr", "card_ctor"}


def _fmt(key: str, value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    if key in _RATIO_KEYS:
        return f"{value * 100:.2f}%"
    return f"{value:,.2f}"


def _fmt_change(key: str, change: dict[str, Decimal | None]) -> str:
    if change["abs"] is None:
        return "n/a"
    delta = change["abs"] * 100 if key in _RATIO_KEYS else change["abs"]
    unit = " pp" if key in _RATIO_KEYS else ""
    pct = "n/a" if change["pct"] is None else f"{change['pct']:+.1f}%"
    return f"{delta:+,.2f}{unit} / {pct}"


def render_markdown(
    as_of: date, report: list[dict[str, Any]], diagnoses: list[dict[str, str]], note: str | None
) -> str:
    lines = [
        f"# Monthly KPI and diagnoses (as of {as_of.isoformat()})",
        "",
        f"Current = last {WINDOW_DAYS} days to {as_of.isoformat()}; previous = the {WINDOW_DAYS} "
        "days before. Card CTR/CTOR use seller product card + shop tab only.",
        "",
    ]
    for entry in report:
        lines += [f"## Product {entry['product_id']}", ""]
        if not (entry["in_current"] or entry["in_previous"]):
            lines += ["No A-34 row in either window.", ""]
            continue
        lines += ["| Metric | Current | Previous | Change (abs / %) |", "|---|---|---|---|"]
        for key, label in METRIC_ROWS:
            lines.append(
                f"| {label} | {_fmt(key, entry['current'][key])} "
                f"| {_fmt(key, entry['previous'][key])} "
                f"| {_fmt_change(key, entry['change'][key])} |"
            )
        lines.append("")
    lines += ["## Listing diagnoses", ""]
    if note:
        lines += [note, ""]
    if diagnoses:
        lines += ["| Product | Field | Code | How to solve |", "|---|---|---|---|"]
        for row in diagnoses:
            solve = row["how_to_solve"].replace("|", "/").replace("\n", " ")
            lines.append(f"| {row['product_id']} | {row['field']} | {row['code']} | {solve} |")
        lines.append("")
    elif not note:
        lines += ["No diagnosis results returned.", ""]
    return "\n".join(lines)


def analyse(out_dir: Path, as_of: date, product_ids: list[str]) -> None:
    """Re-read the raw files in ``out_dir`` and (re)write the KPI + diagnosis outputs."""

    def load(name: str) -> Any:
        path = out_dir / name
        return json.loads(path.read_text()) if path.exists() else None

    report = build_report(product_ids, load("a34_30d_current.json"), load("a34_30d_previous.json"))
    wanted = set(product_ids)
    diagnoses = [
        row for row in diagnosis_rows(load("diagnoses_raw.json")) if row["product_id"] in wanted
    ]
    error = load("diagnoses_error.json")
    note = (
        f"Diagnoses unavailable: {error.get('error_class')}: {error.get('message')}"
        if isinstance(error, dict)
        else None
    )
    (out_dir / "monthly_kpi.json").write_text(
        json.dumps(
            _jsonable(
                {
                    "as_of": as_of.isoformat(),
                    "products": report,
                    "diagnoses": diagnoses,
                    "diagnoses_note": note,
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    (out_dir / "monthly_kpi.md").write_text(render_markdown(as_of, report, diagnoses, note))


def windows(as_of: date) -> dict[str, tuple[str, str]]:
    return {
        "current": (
            (as_of - timedelta(days=29)).isoformat(),
            (as_of + timedelta(days=1)).isoformat(),
        ),
        "previous": (
            (as_of - timedelta(days=59)).isoformat(),
            (as_of - timedelta(days=29)).isoformat(),
        ),
    }


async def _fetch_live(out_dir: Path, as_of: date, product_ids: list[str]) -> None:
    from juli_backend.core.async_db import async_database_url
    from juli_backend.core.config import require_env
    from juli_backend.core.security import resolve_production_read_credential
    from juli_backend.database.database import ensure_worker_session_factory
    from juli_backend.integrations.tiktok.factories import (
        ClientFactoryConfig,
        ProductionReadClientFactory,
    )
    from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID

    app_key, app_secret = require_env("TIKTOK_APP_KEY"), require_env("TIKTOK_APP_SECRET")
    factory = ensure_worker_session_factory(async_database_url(require_env("DATABASE_URL")))
    async with factory() as session:
        credential = await resolve_production_read_credential(session)
    resources = ProductionReadClientFactory().create_resources(
        ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=credential.access_token,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher=credential.shop_cipher,
        )
    )
    for name, (start, end) in windows(as_of).items():
        products = resources.analytics.list_product_performance_all(
            start_date_ge=start, end_date_lt=end
        )
        _write(out_dir / f"a34_30d_{name}.json", {"products": products, "window": [start, end]})
    try:
        raw = resources.products.get_diagnoses(product_ids)
        _write(out_dir / "diagnoses_raw.json", raw)
    except Exception as exc:
        _write(
            out_dir / "diagnoses_error.json",
            {"error_class": type(exc).__name__, "message": str(exc)},
        )


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=date.today() - timedelta(days=1)
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--product-ids", required=True, help="comma-separated product ids")
    parser.add_argument("--replay", action="store_true", help="skip network; re-analyse out-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    product_ids = [p.strip() for p in args.product_ids.split(",") if p.strip()]
    if not product_ids:
        print("--product-ids is empty", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if not args.replay:
        asyncio.run(_fetch_live(args.out_dir, args.as_of, product_ids))
    analyse(args.out_dir, args.as_of, product_ids)
    print(f"wrote {args.out_dir / 'monthly_kpi.md'}")
    return 0


def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "backend" / "src"))
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
