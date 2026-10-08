"""Load a shop snapshot folder into typed objects — ADR-108 decisions 2 and 13.

A **shop snapshot** is what ``scripts/shop_diagnosis_fetch.py`` writes for one shop
and end date, outside the repo (order data holds buyer information)::

    meta.json                       {"shop_name", "shop", "end", "days", "orders_fetch", ...}
    daily/a34_<YYYY-MM-DD>.json     {"day": ..., "products": [A-34 rows]}, one file per day
    orders.json                     {"orders": [...]}, created in the 60 days (create time)
    promotions/activities.json      {"activities": [...]}, every status the search returns
    promotions/activity_details.json {<activity id>: Get Activity payload}
    promotions/coupons.json         {"coupons": [...]}
    live/sessions.json              {"sessions": [...]}, LIVE sessions of the 60 days
    live/products/<live id>.json    the session's product performance payload
    videos/videos.json              {"videos": [...]}
    videos/products/<video id>.json the video's product performance payload
    products/<product id>.json      Get Product payload (title, SKU prices)

Every file but ``daily/`` is optional: a missing one reads as empty and the page
says what it could not show. Reading files is the only I/O here; nothing calls
TikTok.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

DAILY_DIR = "daily"
DAILY_PREFIX = "a34_"


@dataclass(frozen=True)
class Windows:
    """The two 30-day windows ending at ``end`` (inclusive local dates)."""

    prior_first: date
    prior_last: date
    last_first: date
    last_last: date

    @classmethod
    def ending(cls, end: date, days: int) -> Windows:
        last_first = end - timedelta(days=days - 1)
        prior_last = last_first - timedelta(days=1)
        return cls(prior_last - timedelta(days=days - 1), prior_last, last_first, end)

    def prior_days(self) -> list[date]:
        return _span(self.prior_first, self.prior_last)

    def last_days(self) -> list[date]:
        return _span(self.last_first, self.last_last)

    def all_days(self) -> list[date]:
        return _span(self.prior_first, self.last_last)


def _span(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


@dataclass(frozen=True)
class Snapshot:
    """One shop snapshot, loaded. ``daily`` maps a local date to its A-34 rows."""

    shop_name: str
    end: date
    daily: dict[date, list[dict]]
    orders: list[dict] | None = None
    activities: list[dict] = field(default_factory=list)
    activity_details: dict[str, dict] = field(default_factory=dict)
    coupons: list[dict] = field(default_factory=list)
    live_sessions: list[dict] = field(default_factory=list)
    live_products: dict[str, Any] = field(default_factory=dict)
    videos: list[dict] = field(default_factory=list)
    video_products: dict[str, Any] = field(default_factory=dict)
    products: dict[str, dict] = field(default_factory=dict)

    def title(self, product_id: str) -> str:
        detail = self.products.get(product_id) or {}
        return str(detail.get("title") or "")

    def list_prices(self, product_id: str) -> dict[str, float]:
        """Per SKU id, the listed sale price (before any promotion)."""
        out: dict[str, float] = {}
        for sku in (self.products.get(product_id) or {}).get("skus") or []:
            if not isinstance(sku, dict):
                continue
            price = sku.get("price") if isinstance(sku.get("price"), dict) else {}
            value = to_float((price or {}).get("sale_price"))
            if sku.get("id") and value > 0:
                out[str(sku["id"])] = value
        return out


def to_float(value: object) -> float:
    """A number from an A-34 / order field: ints, numeric strings, ``{"amount": ...}``."""
    if isinstance(value, dict):
        value = value.get("amount")
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(str(value))
    except ValueError:
        return 0.0


def _read(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _unwrap(payload: Any) -> Any:
    """Strip a ``{"data": ...}`` API envelope when present."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _listed(payload: Any, key: str) -> list[dict]:
    source = _unwrap(payload)
    value = source.get(key) if isinstance(source, dict) else source
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _folder_payloads(folder: Path) -> dict[str, Any]:
    if not folder.is_dir():
        return {}
    return {p.stem: _read(p) for p in sorted(folder.glob("*.json"))}


def load_daily(folder: Path) -> dict[date, list[dict]]:
    """Every ``daily/a34_<date>.json`` as ``{date: rows}``."""
    out: dict[date, list[dict]] = {}
    daily = folder / DAILY_DIR
    for path in sorted(daily.glob(f"{DAILY_PREFIX}*.json")) if daily.is_dir() else []:
        try:
            day = date.fromisoformat(path.stem.removeprefix(DAILY_PREFIX))
        except ValueError:
            continue
        out[day] = _listed(_read(path), "products")
    return out


def load_snapshot(folder: Path, end: date | None = None) -> Snapshot:
    """Load ``folder``; ``end`` defaults to the meta end date, else the last daily file."""
    meta = _read(folder / "meta.json") or {}
    daily = load_daily(folder)
    if not daily:
        raise ValueError(f"no daily files under {folder / DAILY_DIR}")
    if end is None:
        end = date.fromisoformat(meta["end"]) if meta.get("end") else max(daily)
    orders_payload = _read(folder / "orders.json")
    details_raw = _read(folder / "promotions" / "activity_details.json") or {}
    products = {
        pid: _unwrap(payload)
        for pid, payload in _folder_payloads(folder / "products").items()
        if isinstance(_unwrap(payload), dict)
    }
    return Snapshot(
        shop_name=str(meta.get("shop_name") or meta.get("shop") or ""),
        end=end,
        daily=daily,
        orders=_listed(orders_payload, "orders") if orders_payload is not None else None,
        activities=_listed(_read(folder / "promotions" / "activities.json"), "activities"),
        activity_details={
            str(k): _unwrap(v) for k, v in details_raw.items() if isinstance(_unwrap(v), dict)
        },
        coupons=_listed(_read(folder / "promotions" / "coupons.json"), "coupons"),
        live_sessions=_listed(_read(folder / "live" / "sessions.json"), "sessions"),
        live_products=_folder_payloads(folder / "live" / "products"),
        videos=_listed(_read(folder / "videos" / "videos.json"), "videos"),
        video_products=_folder_payloads(folder / "videos" / "products"),
        products=products,
    )
