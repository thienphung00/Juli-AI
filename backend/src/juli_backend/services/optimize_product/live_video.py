"""Shop LIVE sessions and videos that featured a product (ADR-106 amendment 4).

Parses what the optional live fetch saved under ``snapshot/live`` and
``snapshot/videos``:

* ``live/sessions.json``       ``{"sessions": [...]}`` — the top LIVE sessions of the window
  (each an A-28 list entry: ``id``, ``title``, ``start_time``, ``sales_performance``);
* ``live/products/<id>.json``  the session's product performance payload
  (``data.products[]`` with ``traffic.product_impressions`` and ``sales.sku_orders``);
* ``videos/videos.json``       ``{"videos": [...]}`` — the top videos (``id``, ``title``,
  ``video_post_time``, ``products[]``);
* ``videos/products/<id>.json`` the video's product performance (``data.products[]``
  with ``units_sold``).

Pure over already-loaded JSON.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from juli_backend.services.optimize_product.funnel import to_decimal

SHOP_UTC_OFFSET_HOURS = 7
LIVE = "LIVE"
VIDEO = "Video"


@dataclass(frozen=True)
class Appearance:
    kind: str
    title: str
    #: ISO date in the shop's timezone, ``""`` when unknown.
    day: str
    #: The product's own numbers in that LIVE / video; ``None`` when not reported.
    impressions: int | None
    orders: int | None


def _day(value: object) -> str:
    text = str(value or "")
    zone = timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=zone).date().isoformat()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
        parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return parsed.astimezone(zone).date().isoformat()
    return ""


def _products(payload: object) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    source = data if isinstance(data, dict) else payload
    items = source.get("products") if isinstance(source, dict) else None
    return [p for p in items if isinstance(p, dict)] if isinstance(items, list) else []


def parse_appearances(
    sessions: list[dict],
    session_products: dict[str, object],
    videos: list[dict],
    video_products: dict[str, object],
) -> dict[str, list[Appearance]]:
    """Per product id, the LIVE sessions and videos that featured it."""
    out: dict[str, list[Appearance]] = defaultdict(list)
    for session in sessions:
        session_id = str(session.get("id") or "")
        for product in _products(session_products.get(session_id)):
            product_id = str(product.get("id") or "")
            if not product_id:
                continue
            raw_traffic, raw_sales = product.get("traffic"), product.get("sales")
            traffic: dict = raw_traffic if isinstance(raw_traffic, dict) else {}
            sales: dict = raw_sales if isinstance(raw_sales, dict) else {}
            out[product_id].append(
                Appearance(
                    LIVE,
                    str(session.get("title") or ""),
                    _day(session.get("start_time")),
                    int(to_decimal(traffic.get("product_impressions"))),
                    int(to_decimal(sales.get("sku_orders"))),
                )
            )
    for video in videos:
        video_id = str(video.get("id") or "")
        detail = {str(p.get("id")): p for p in _products(video_products.get(video_id))}
        listed = [p for p in video.get("products") or [] if isinstance(p, dict)]
        for product_id in dict.fromkeys([*(str(p.get("id") or "") for p in listed), *detail]):
            if not product_id:
                continue
            units = detail.get(product_id, {}).get("units_sold")
            out[product_id].append(
                Appearance(
                    VIDEO,
                    str(video.get("title") or ""),
                    _day(video.get("video_post_time")),
                    None,
                    int(to_decimal(units)) if units is not None else None,
                )
            )
    return dict(out)
