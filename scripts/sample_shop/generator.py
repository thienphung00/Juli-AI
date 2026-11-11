"""Generate the synthetic shop as Connector-shaped ingest posts. Pure and deterministic.

``generate(end_date)`` returns a :class:`SampleShop`: the ``IngestBody`` dicts for every dataset
the Shopee screens read, plus the giá vốn per SKU. One simulated history feeds every dataset, so
the datasets agree by construction:

- an order is placed from one traffic source (Thẻ sản phẩm child / Video / Liên kết) and holds 1-2
  lines; shop orders / GMV (shop_overview, traffic_overview) are the distinct orders / Σ line GMV,
  a product's orders / GMV (item_traffic_sources) are the orders containing it, so
  product <= shop on every day and the shop's streams add up to the shop;
- the ad campaigns' daily rows add up to the shop's ads row (placed basis), ROAS 3.5-10;
- money is VND (what the Connector posts), rates are fractions, dates the GMT+7 day.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from juli_backend.services.ingest import order_ref as order_ref_mod
from scripts.sample_shop.catalog import (
    CAMPAIGNS,
    PRODUCTS,
    SAMPLE_SHOPEE_SHOP_ID,
    Product,
    Variation,
)

SEED = 20_261_111
DAYS = 30
SOURCE = "extension"
SOURCE_VERSION = "sample-1.0"
GMT7 = timezone(timedelta(hours=7))
#: The key behind the synthetic order refs. Not a secret: the shop is made up.
ORDER_REF_KEY = b"juli-sample-shop-order-ref-key-v1"

#: Thẻ sản phẩm children: (item_traffic_sources l2, traffic_overview sub_source label, weight)
CARD_CHILDREN: tuple[tuple[str, str, int], ...] = (
    ("search", "Tìm kiếm", 40),
    ("recommendation", "Đề xuất", 25),
    ("shop", "Cửa hàng", 15),
    ("shopping_cart", "Giỏ hàng", 8),
    ("my_purchase", "Đơn mua của tôi", 7),
    ("others", "Khác", 5),
)
STREAMS = ("product_card", "video", "affiliate")
STREAM_L1 = {
    "product_card": "psd_label_product_card",
    "video": "psd_label_seller_video",
    "affiliate": "psd_label_affiliate",
}
#: the impressions field of each stream on traffic_overview
STREAM_VIEWS_FIELD = {
    "product_card": "product_impressions",
    "video": "video_views",
    "affiliate": "content_views",
}
STREAM_SHARE = {"product_card": 0.80, "video": 0.08, "affiliate": 0.12}
STREAM_CTR_FACTOR = {"product_card": 1.0, "video": 1.5, "affiliate": 1.7}
STREAM_CVR_FACTOR = {"product_card": 1.0, "video": 0.8, "affiliate": 1.1}
ADS_SUB_SOURCE = "Quảng cáo GMV tối đa ROAS tùy chỉnh cho sản phẩm"
HOUR_WEIGHTS = (1, 1, 0, 0, 0, 1, 2, 3, 4, 4, 5, 5, 4, 4, 4, 4, 4, 5, 6, 8, 9, 8, 5, 3)
COMBO_START_DAY = 10
COMBO_NAME = "Combo Hiên Nhà - Mua 2 giảm 5%, mua 3 giảm 10%"
COMBO_TIERS = ((2, 5), (3, 10))
VIDEO_SHARE_MIN_CLICKS = 8
FIXED_FEE = 0.105
SERVICE_FEE = 0.079
PAYMENT_FEE = 0.06
INCOME_LAG_DAYS = 4


@dataclass
class Post:
    dataset: str
    body: dict[str, Any]


@dataclass
class SampleShop:
    end_date: date
    start_date: date
    shopee_shop_id: str
    posts: list[Post] = field(default_factory=list)
    #: scope ("item_id:model_id") -> giá vốn per unit, VND
    costs: dict[str, int] = field(default_factory=dict)
    #: the simulated truth the tests check the posts against
    days: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Line:
    product: Product
    variation: Variation
    qty: int
    value: int = 0
    bundle: int = 0
    voucher: int = 0
    ship: int = 0

    @property
    def buyer_paid(self) -> int:
        return self.value - self.bundle - self.voucher


@dataclass
class _Order:
    ref: str
    at: datetime
    stream: str
    child: int  # index into CARD_CHILDREN (card only)
    lines: list[_Line]


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _pick(rng: random.Random, weights: tuple[int, ...]) -> int:
    return rng.choices(range(len(weights)), weights=weights)[0]


def _iso(d: date) -> str:
    return d.isoformat()


def _body(
    start: date,
    end: date,
    rows: list[dict[str, Any]],
    *,
    granularity: str,
    order_type: str | None,
    shopee_shop_id: str,
    captured_at: datetime,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": SOURCE,
        "source_version": SOURCE_VERSION,
        "captured_at": captured_at.isoformat(),
        "period": {"start": _iso(start), "end": _iso(end), "granularity": granularity},
        "platform_shop_id": shopee_shop_id,
        "rows": rows,
    }
    if order_type is not None:
        body["order_type"] = order_type
    return body


def _ads_rows_money(
    gmv: int, orders: int, spend: int, clicks: int, impressions: int
) -> dict[str, Any]:
    return {
        "ads_impressions": impressions,
        "product_clicks": clicks,
        "orders": orders,
        "sales": gmv,
        "ads_expense": spend,
        "ads_roas": round(gmv / spend, 2) if spend else 0,
    }


def _simulate_orders(
    rng: random.Random, day: date, index: int, min_orders: int
) -> tuple[list[_Order], dict[int, dict[str, Any]]]:
    """The day's orders and each product's traffic draw (views, base clicks)."""
    season = 1.12 if day.weekday() >= 5 else 1.0
    trend = 1 + 0.004 * (index - DAYS / 2)
    draw: dict[int, dict[str, Any]] = {}
    orders: list[_Order] = []
    counter = 0

    def new_order(pi: int, stream: str) -> None:
        nonlocal counter
        counter += 1
        p = PRODUCTS[pi]
        lines = [_new_line(rng, p)]
        if rng.random() < 0.12:
            other = rng.choice([q for q in PRODUCTS if q is not p])
            lines.append(_new_line(rng, other))
        at = datetime.combine(day, datetime.min.time()) + timedelta(
            hours=_pick(rng, HOUR_WEIGHTS), minutes=rng.randrange(60), seconds=rng.randrange(60)
        )
        orders.append(
            _Order(
                ref=order_ref_mod.order_ref(f"SAMPLE{day:%Y%m%d}{counter:04d}", ORDER_REF_KEY),
                at=at,
                stream=stream,
                child=_pick(rng, tuple(c[2] for c in CARD_CHILDREN))
                if stream == "product_card"
                else 0,
                lines=lines,
            )
        )

    for pi, p in enumerate(PRODUCTS):
        views = min(max(round(p.base_views * season * trend * rng.uniform(0.85, 1.15)), 300), 1600)
        draw[pi] = {"views": views}
        for stream in STREAMS:
            v = round(views * STREAM_SHARE[stream])
            clicks = round(v * p.ctr * STREAM_CTR_FACTOR[stream])
            draw[pi][stream] = {"views": v, "clicks": clicks}
            for _ in range(_poisson(rng, clicks * p.cvr * STREAM_CVR_FACTOR[stream])):
                new_order(pi, stream)

    def has_product(pi: int) -> bool:
        return any(any(ln.product is PRODUCTS[pi] for ln in o.lines) for o in orders)

    # every ad campaign converts at least once a day (its ROAS is defined), and the shop sells
    for ci in range(len(CAMPAIGNS)):
        members = [i for i, p in enumerate(PRODUCTS) if p.campaign == ci]
        if not any(has_product(i) for i in members):
            new_order(rng.choice(members), "product_card")
    while len(orders) < min_orders:
        new_order(rng.randrange(len(PRODUCTS)), "product_card")
    return orders, draw


def _new_line(rng: random.Random, p: Product) -> _Line:
    var = p.variations[_pick(rng, p.variation_weights)]
    return _Line(p, var, _pick(rng, p.qty_weights) + 1)


def _price_order(rng: random.Random, order: _Order, combo_on: bool) -> None:
    """Fill value, combo discount, shop voucher and buyer shipping on the lines."""
    for ln in order.lines:
        ln.value = ln.variation.price * ln.qty
        if combo_on and ln.product.in_combo:
            pct = max((d for q, d in COMBO_TIERS if ln.qty >= q), default=0)
            ln.bundle = round(ln.value * pct / 100)
    total = sum(ln.value for ln in order.lines)
    if rng.random() < 0.10:
        voucher = min(10_000, round(total * 0.05 / 1000) * 1000)
        left = voucher
        for i, ln in enumerate(order.lines):
            share = left if i == len(order.lines) - 1 else round(voucher * ln.value / total)
            ln.voucher, left = share, left - share
    order.lines[0].ship = 0 if total >= 150_000 else rng.choice((10_000, 12_000, 15_000))


def _fees(ln: _Line) -> tuple[int, int, int]:
    return (
        round(ln.buyer_paid * FIXED_FEE),
        round(ln.buyer_paid * SERVICE_FEE),
        round((ln.buyer_paid + ln.ship) * PAYMENT_FEE),
    )


def generate(
    end_date: date,
    *,
    days: int = DAYS,
    shopee_shop_id: str | None = None,
    captured_at: datetime | None = None,
) -> SampleShop:
    """The whole synthetic history ending on ``end_date`` (every one of ``days`` days present)."""
    sid = shopee_shop_id or str(SAMPLE_SHOPEE_SHOP_ID)
    start = end_date - timedelta(days=days - 1)
    rng = random.Random(SEED)
    captured = captured_at or datetime.combine(end_date, datetime.min.time(), tzinfo=GMT7).replace(
        hour=23, minute=30
    )
    shop = SampleShop(end_date, start, sid)

    def post(dataset: str, rows: list[dict[str, Any]], s: date, e: date, **kw: Any) -> None:
        shop.posts.extend(_split(dataset, rows, s, e, sid, kw.pop("at", captured), **kw))

    shop_overview: list[dict[str, Any]] = []
    shop_traffic: list[dict[str, Any]] = []
    traffic_conf: list[dict[str, Any]] = []
    traffic_ads: list[dict[str, Any]] = []
    item_rows: list[dict[str, Any]] = []
    campaign_rows: list[dict[str, Any]] = []
    promo_daily: list[dict[str, Any]] = []
    line_rows: list[dict[str, Any]] = []
    income_rows: list[dict[str, Any]] = []
    period_ads: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    combo_totals = {"sales": 0, "orders": 0, "units": 0}
    combo_start = start + timedelta(days=COMBO_START_DAY)
    sold = [p.sold_before for p in PRODUCTS]

    for idx in range(days):
        day = start + timedelta(days=idx)
        orders, draw = _simulate_orders(rng, day, idx, min_orders=4)
        combo_on = day >= combo_start
        for o in orders:
            _price_order(rng, o, combo_on)
        shop_day = _day_rows(rng, day, orders, draw, sold)
        # --- shop-level rows
        gmv = shop_day["gmv"]
        n = len(orders)
        clicks_all = shop_day["clicks"]
        visitors = round(clicks_all * 0.72)
        buyers = n
        shop_overview.append(
            {
                "date": _iso(day),
                "sales": gmv,
                "sales_excl_shopee_subsidy": gmv,
                "orders": n,
                "sales_per_order": round(gmv / n),
                "product_clicks": clicks_all,
                "visitors": visitors,
                "conversion_rate": round(n / visitors, 4),
                "buyers": buyers,
                "new_buyers": round(buyers * 0.82),
                "existing_buyers": buyers - round(buyers * 0.82),
                "cancelled_orders": 0,
                "cancelled_sales": 0,
                "returned_orders": 0,
                "returned_sales": 0,
            }
        )
        shop_traffic.append(
            {
                "date": _iso(day),
                "device": "all",
                "visitors": visitors,
                "page_views": round(visitors * 1.9),
                "bounce_rate": round(rng.uniform(0.40, 0.50), 3),
                "new_followers": rng.randrange(2, 12),
            }
        )
        traffic_conf.extend(shop_day["traffic_rows"](day))
        item_rows.extend(shop_day["item_rows"])
        ads = shop_day["ads"]
        traffic_ads.append(
            {
                "date": _iso(day),
                "source": "psd_label_shopee_ads",
                "sub_source": ADS_SUB_SOURCE,
                **_ads_rows_money(
                    ads["gmv"], ads["orders"], ads["spend"], ads["clicks"], ads["impressions"]
                ),
            }
        )
        for (ci, pi), a in shop_day["ads_by_product"].items():
            for key, value in a.items():
                period_ads[(ci, pi)][key] += value
        campaign_rows.extend(shop_day["campaign_rows"](day))
        # --- order lines / income / combo
        for o in orders:
            line_rows.extend(_line_rows(o))
            if day <= end_date - timedelta(days=INCOME_LAG_DAYS):
                income_rows.append(_income_row(o, day))
            for ln in o.lines:
                if ln.bundle:
                    combo_totals["sales"] += ln.value
                    combo_totals["units"] += ln.qty
            if any(ln.bundle for ln in o.lines):
                combo_totals["orders"] += 1
        combo = [ln for o in orders for ln in o.lines if ln.bundle]
        if combo_on:
            combo_orders = {o.ref for o in orders if any(ln.bundle for ln in o.lines)}
            promo_daily.append(
                {
                    "date": _iso(day),
                    "promo_type": "Combo Khuyến Mãi",
                    "sales": sum(ln.value for ln in combo),
                    "orders": len(combo_orders),
                    "units": sum(ln.qty for ln in combo),
                    "buyers": len(combo_orders),
                    "sales_per_buyer": round(sum(ln.value for ln in combo) / len(combo_orders))
                    if combo_orders
                    else 0,
                }
            )
        shop.days.append(
            {
                "date": day,
                "orders": n,
                "gmv": gmv,
                "products": shop_day["products"],
                "ads": ads,
                "streams": shop_day["streams"],
            }
        )

    # --- posts, in the order a Connector would send them (catalogue first: the order lines'
    #     SKUs resolve to items through it)
    shop.posts.append(
        Post(
            "item_catalog",
            _body(
                start,
                end_date,
                _catalog_rows(),
                granularity="period",
                order_type=None,
                shopee_shop_id=sid,
                captured_at=captured,
            ),
        )
    )
    first_capture = datetime.combine(start, datetime.min.time(), tzinfo=GMT7).replace(hour=8)
    shop.posts.append(
        Post(
            "item_snapshot",
            _body(
                start,
                start,
                _snapshot_rows(sold, early=True),
                granularity="period",
                order_type=None,
                shopee_shop_id=sid,
                captured_at=first_capture,
            ),
        )
    )
    shop.posts.append(
        Post(
            "item_snapshot",
            _body(
                end_date,
                end_date,
                _snapshot_rows(sold, early=False),
                granularity="period",
                order_type=None,
                shopee_shop_id=sid,
                captured_at=captured,
            ),
        )
    )
    post(
        "order_lines",
        line_rows,
        start,
        end_date,
        granularity="period",
        order_type=None,
        day_of=lambda r: date.fromisoformat(r["ordered_at"][:10]),
    )
    post(
        "order_income",
        income_rows,
        start,
        end_date,
        granularity="period",
        order_type=None,
        day_of=lambda r: date.fromisoformat(r["ordered_on"]),
    )
    post("shop_overview", shop_overview, start, end_date, order_type="confirmed")
    post("shop_traffic", shop_traffic, start, end_date, order_type=None)
    post("traffic_overview", traffic_conf, start, end_date, order_type="confirmed")
    post("traffic_overview", traffic_ads, start, end_date, order_type="placed")
    post("item_traffic_sources", item_rows, start, end_date, order_type="confirmed")
    post("ads_campaign_daily", campaign_rows, start, end_date, order_type="placed")
    post(
        "ads_campaign_period",
        _period_ads_rows(period_ads),
        start,
        end_date,
        granularity="period",
        order_type="placed",
        day_of=None,
    )
    post("promotion_daily", promo_daily, combo_start, end_date, order_type="confirmed")
    post(
        "promotions",
        [_combo_row(combo_start, end_date, combo_totals)],
        start,
        end_date,
        granularity="period",
        order_type="confirmed",
        day_of=None,
    )
    for p in PRODUCTS:
        for v in p.variations:
            shop.costs[f"{p.item_id}:{v.model_id}"] = v.cost
    return shop


def _split(
    dataset: str,
    rows: list[dict[str, Any]],
    start: date,
    end: date,
    sid: str,
    at: datetime,
    *,
    order_type: str | None,
    granularity: str = "day",
    day_of: Any = "date",
    max_rows: int = 1200,
) -> list[Post]:
    """One post per <= 31 day slice holding <= ``max_rows`` rows (the gateway's limits)."""
    if not rows:
        return []
    if day_of is None:  # a period row: one post for the whole period
        return [
            Post(
                dataset,
                _body(
                    start,
                    end,
                    rows,
                    granularity=granularity,
                    order_type=order_type,
                    shopee_shop_id=sid,
                    captured_at=at,
                ),
            )
        ]
    key = (lambda r: date.fromisoformat(r["date"])) if day_of == "date" else day_of
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_day[key(r)].append(r)
    out: list[Post] = []
    chunk: list[dict[str, Any]] = []
    first: date | None = None
    last: date | None = None
    for d in sorted(by_day):
        too_long = first is not None and (d - first).days + 1 > 31
        too_big = chunk and len(chunk) + len(by_day[d]) > max_rows
        if first is not None and last is not None and (too_long or too_big):
            out.append(
                Post(
                    dataset,
                    _body(
                        first,
                        last,
                        chunk,
                        granularity=granularity,
                        order_type=order_type,
                        shopee_shop_id=sid,
                        captured_at=at,
                    ),
                )
            )
            chunk, first = [], None
        first = first or d
        last = d
        chunk = chunk + by_day[d]
    if first is not None and last is not None:
        out.append(
            Post(
                dataset,
                _body(
                    first,
                    last,
                    chunk,
                    granularity=granularity,
                    order_type=order_type,
                    shopee_shop_id=sid,
                    captured_at=at,
                ),
            )
        )
    return out


def _day_rows(
    rng: random.Random,
    day: date,
    orders: list[_Order],
    draw: dict[int, dict[str, Any]],
    sold: list[int],
) -> dict[str, Any]:
    """Traffic, per-product and ads figures of one day, derived from its orders."""
    child_w = tuple(c[2] for c in CARD_CHILDREN)
    wsum = sum(child_w)
    products: dict[str, dict[str, Any]] = {}
    item_rows: list[dict[str, Any]] = []
    stream_tot: dict[str, dict[str, int]] = {
        s: {"views": 0, "clicks": 0, "orders": 0, "sales": 0, "units": 0} for s in STREAMS
    }
    child_tot = [
        {"views": 0, "clicks": 0, "orders": 0, "sales": 0, "units": 0} for _ in CARD_CHILDREN
    ]
    for pi, p in enumerate(PRODUCTS):
        mine = [(o, [ln for ln in o.lines if ln.product is p]) for o in orders]
        mine = [(o, lns) for o, lns in mine if lns]
        rec: dict[str, Any] = {
            "views": 0,
            "clicks": 0,
            "orders": len(mine),
            "gmv": 0,
            "streams": {},
        }
        for stream in STREAMS:
            sel = [(o, lns) for o, lns in mine if o.stream == stream]
            n = len(sel)
            sales = sum(ln.value for _, lns in sel for ln in lns)
            units = sum(ln.qty for _, lns in sel for ln in lns)
            d = draw[pi][stream]
            if stream == "product_card":
                views = clicks = 0
                for ci, (l2, _label, w) in enumerate(CARD_CHILDREN):
                    csel = [(o, lns) for o, lns in sel if o.child == ci]
                    c_orders = len(csel)
                    c_sales = sum(ln.value for _, lns in csel for ln in lns)
                    c_units = sum(ln.qty for _, lns in csel for ln in lns)
                    c_clicks = max(round(d["clicks"] * w / wsum), c_orders)
                    c_views = max(round(d["views"] * w / wsum), c_clicks * 8)
                    views, clicks = views + c_views, clicks + c_clicks
                    item_rows.append(
                        _item_row(
                            day,
                            p,
                            "product_card",
                            l2,
                            c_views,
                            c_clicks,
                            c_orders,
                            c_sales,
                            c_units,
                        )
                    )
                    t = child_tot[ci]
                    for k, v in (
                        ("views", c_views),
                        ("clicks", c_clicks),
                        ("orders", c_orders),
                        ("sales", c_sales),
                        ("units", c_units),
                    ):
                        t[k] += v
            else:
                clicks = max(d["clicks"], n)
                views = max(d["views"], clicks * 8)
            item_rows.append(_item_row(day, p, stream, "total", views, clicks, n, sales, units))
            rec["streams"][stream] = {"views": views, "clicks": clicks, "orders": n, "gmv": sales}
            rec["views"] += views
            rec["clicks"] += clicks
            rec["gmv"] += sales
            t = stream_tot[stream]
            t["views"] += views
            t["clicks"] += clicks
            t["sales"] += sales
            t["units"] += units
        products[p.item_id] = rec
        for o, lns in mine:
            for ln in lns:
                sold[pi] += ln.qty
    for stream in STREAMS:
        stream_tot[stream]["orders"] = len([o for o in orders if o.stream == stream])
    gmv = sum(ln.value for o in orders for ln in o.lines)
    clicks_all = sum(t["clicks"] for t in stream_tot.values())

    # --- ads: per product of a campaign, a share of its confirmed orders, ROAS 3.5-10
    ads_by_product: dict[tuple[int, int], dict[str, int]] = {}
    camp: dict[int, dict[str, int]] = {
        ci: {"gmv": 0, "orders": 0, "spend": 0, "clicks": 0, "impressions": 0}
        for ci in range(len(CAMPAIGNS))
    }
    drawn: dict[int, int] = {}
    for pi, p in enumerate(PRODUCTS):
        if p.campaign is None:
            continue
        n = products[p.item_id]["orders"]
        drawn[pi] = min(n, int(n * rng.uniform(0.20, 0.45) + rng.random()))
    for ci in range(len(CAMPAIGNS)):  # a campaign converts at least once a day: ROAS is defined
        members = [pi for pi in drawn if PRODUCTS[pi].campaign == ci]
        if not any(drawn[pi] for pi in members):
            best = max(members, key=lambda pi: products[PRODUCTS[pi].item_id]["orders"])
            drawn[best] = 1
    for pi, a_orders in drawn.items():
        p = PRODUCTS[pi]
        rec = products[p.item_id]
        n = rec["orders"]
        a_gmv = round(rec["gmv"] * a_orders / n) if n else 0
        spend = round(a_gmv / rng.uniform(4.5, 9.0) / 100) * 100 if a_gmv else 0
        a_clicks = a_orders * rng.randrange(14, 30)
        a_impr = round(a_clicks / rng.uniform(0.03, 0.045))
        assert p.campaign is not None
        ads_by_product[(p.campaign, pi)] = {
            "gmv": a_gmv,
            "orders": a_orders,
            "spend": spend,
            "clicks": a_clicks,
            "impressions": a_impr,
        }
        for k, v in ads_by_product[(p.campaign, pi)].items():
            camp[p.campaign][k] += v
    ads = {
        k: sum(c[k] for c in camp.values())
        for k in ("gmv", "orders", "spend", "clicks", "impressions")
    }

    def traffic_rows(d: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for stream in STREAMS:
            t = stream_tot[stream]
            r: dict[str, Any] = {
                "date": _iso(d),
                "source": STREAM_L1[stream],
                STREAM_VIEWS_FIELD[stream]: t["views"],
                "product_clicks": t["clicks"],
                "ctr": round(t["clicks"] / t["views"], 4),
                "orders": t["orders"],
                "units": t["units"],
                "buyers": t["orders"],
                "sales": t["sales"],
            }
            rows.append(r)
        for ci, (_l2, label, _w) in enumerate(CARD_CHILDREN):
            t = child_tot[ci]
            rows.append(
                {
                    "date": _iso(d),
                    "source": STREAM_L1["product_card"],
                    "sub_source": label,
                    "product_impressions": t["views"],
                    "product_clicks": t["clicks"],
                    "orders": t["orders"],
                    "units": t["units"],
                    "buyers": t["orders"],
                    "sales": t["sales"],
                }
            )
        return rows

    def campaign_rows(d: date) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ci, (cid, title) in enumerate(CAMPAIGNS):
            c = camp[ci]
            out.append(
                {
                    "date": _iso(d),
                    "campaign_id": cid,
                    "campaign_name": title,
                    "ad_type": "gmv_max",
                    "ad_subtype": "roas_custom",
                    "state": "ongoing",
                    "daily_budget": 300_000,
                    "impression": c["impressions"],
                    "click": c["clicks"],
                    "ctr": round(c["clicks"] / c["impressions"], 4) if c["impressions"] else 0,
                    "cost": c["spend"],
                    "cpc": round(c["spend"] / c["clicks"]) if c["clicks"] else 0,
                    "broad_gmv": c["gmv"],
                    "broad_order": c["orders"],
                    "broad_roi": round(c["gmv"] / c["spend"], 2) if c["spend"] else 0,
                    "direct_gmv": round(c["gmv"] * 0.7),
                    "direct_order": max(round(c["orders"] * 0.7), 1 if c["orders"] else 0),
                }
            )
        return out

    shop_streams = {s: dict(t) for s, t in stream_tot.items()}
    return {
        "gmv": gmv,
        "clicks": clicks_all,
        "products": products,
        "item_rows": item_rows,
        "traffic_rows": traffic_rows,
        "campaign_rows": campaign_rows,
        "ads": ads,
        "ads_by_product": ads_by_product,
        "streams": shop_streams,
    }


def _item_row(
    day: date,
    p: Product,
    l1: str,
    l2: str,
    views: int,
    clicks: int,
    orders: int,
    sales: int,
    units: int,
) -> dict[str, Any]:
    return {
        "date": _iso(day),
        "item_id": p.item_id,
        "l1": l1,
        "l2": l2,
        "product_impressions": views,
        "product_clicks": clicks,
        "orders": orders,
        "units": units,
        "buyers": orders,
        "sales": sales,
    }


def _line_rows(o: _Order) -> list[dict[str, Any]]:
    rows = []
    for no, ln in enumerate(o.lines):
        fixed, service, payment = _fees(ln)
        promo = "bundle" if ln.bundle else ("voucher" if ln.voucher else "none")
        rows.append(
            {
                "order_ref": o.ref,
                "line_no": no,
                "ordered_at": o.at.isoformat(timespec="seconds"),
                "status": "delivered",
                "sku": ln.product.parent_sku,
                "variation_sku": ln.variation.sku,
                "variation_name": ln.variation.name,
                "qty": ln.qty,
                "original_price": ln.variation.price,
                "deal_price": ln.variation.price,
                "shop_voucher_share": ln.voucher,
                "bundle_discount": ln.bundle,
                "promo_kind": promo,
                "buyer_shipping_fee": ln.ship if no == 0 else 0,
                "fee_fixed": fixed,
                "fee_service": service,
                "fee_payment": payment,
                "completed_at": (o.at + timedelta(days=3)).isoformat(timespec="seconds"),
                "paid_at": (o.at + timedelta(minutes=2)).isoformat(timespec="seconds"),
            }
        )
    return rows


def _income_row(o: _Order, day: date) -> dict[str, Any]:
    fees = [_fees(ln) for ln in o.lines]
    fixed, service, payment = (sum(f[i] for f in fees) for i in range(3))
    ship_buyer = sum(ln.ship for ln in o.lines)
    ship_actual, subsidy = 26_000, 11_000
    net_ship = max(ship_actual - subsidy - ship_buyer, 0)
    paid = sum(ln.buyer_paid for ln in o.lines)
    return {
        "order_ref": o.ref,
        "ordered_on": _iso(day),
        "paid_on": _iso(day + timedelta(days=3)),
        "product_price": sum(ln.value for ln in o.lines),
        "fee_fixed": fixed,
        "fee_service": service,
        "fee_payment": payment,
        "transaction_fee_rate": PAYMENT_FEE,
        "ship_actual_cost": ship_actual,
        "ship_shopee_subsidy": subsidy,
        "ship_buyer_paid": ship_buyer,
        "net_shipping_cost": net_ship,
        "payout": paid - fixed - service - payment - net_ship,
    }


def _catalog_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in PRODUCTS:
        rows.append({"item_id": p.item_id, "item_name": p.name, "status": "normal"})
        for v in p.variations:
            rows.append(
                {
                    "item_id": p.item_id,
                    "variation_id": v.model_id,
                    "item_name": p.name,
                    "variation_name": v.name,
                    "seller_sku": v.sku,
                    "status": "normal",
                }
            )
    return rows


def _snapshot_rows(sold: list[int], *, early: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    created = datetime(2026, 1, 15, 9, 0, tzinfo=GMT7).isoformat()
    for pi, p in enumerate(PRODUCTS):
        prices = [v.price for v in p.variations]
        # the early capture: more stock, fewer sales, a little less social proof
        scale = 1.25 if early else 1.0
        total_stock = round(sum(v.stock for v in p.variations) * scale)
        sold_count = p.sold_before if early else sold[pi]
        rows.append(
            {
                "item_id": p.item_id,
                "image": f"sample_{p.parent_sku.lower()}_cover",
                "create_time": created,
                "price_min": min(prices),
                "price_max": max(prices),
                "selling_price_min": min(prices),
                "selling_price_max": max(prices),
                "has_discount": False,
                "total_available_stock": total_stock,
                "sellable_stock": total_stock,
                "view_count": p.sold_before * 9 + (0 if early else 1200 * (pi + 1)),
                "liked_count": round(p.sold_before * 0.18) + (0 if early else 40 + pi * 7),
                "sold_count": sold_count,
                "promo_has_bundle_deal": (not early) and p.in_combo,
                "unlisted": False,
            }
        )
        for v in p.variations:
            rows.append(
                {
                    "item_id": p.item_id,
                    "model_id": v.model_id,
                    "origin_price": v.price,
                    "total_available_stock": round(v.stock * scale),
                    "sellable_stock": round(v.stock * scale),
                }
            )
    return rows


def _period_ads_rows(acc: dict[tuple[int, int], dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for (ci, pi), a in sorted(acc.items()):
        spend = int(a["spend"])
        rows.append(
            {
                "campaign_name": CAMPAIGNS[ci][1],
                "item_id": PRODUCTS[pi].item_id,
                "running": True,
                "ads_impressions": int(a["impressions"]),
                "ad_clicks": int(a["clicks"]),
                "ctr": round(a["clicks"] / a["impressions"], 4) if a["impressions"] else 0,
                "conversions": int(a["orders"]),
                "sales": int(a["gmv"]),
                "ads_expense": spend,
                "ads_roas": round(a["gmv"] / spend, 2) if spend else 0,
            }
        )
    return rows


def _combo_row(start: date, end: date, totals: dict[str, int]) -> dict[str, Any]:
    return {
        "program_name": COMBO_NAME,
        "promo_type": "Combo Khuyến Mãi",
        "starts_at": datetime.combine(start, datetime.min.time()).replace(hour=10).isoformat(),
        "ends_at": datetime.combine(end + timedelta(days=30), datetime.min.time()).isoformat(),
        "status": "Đang diễn ra",
        "sales": totals["sales"],
        "orders": totals["orders"],
        "units": totals["units"],
        "buyers": totals["orders"],
        "sales_per_buyer": round(totals["sales"] / totals["orders"]) if totals["orders"] else 0,
        "extra": {
            "tier_count": len(COMBO_TIERS),
            "tier1_min_units": COMBO_TIERS[0][0],
            "tier1_discount_pct": COMBO_TIERS[0][1],
            "tier2_min_units": COMBO_TIERS[1][0],
            "tier2_discount_pct": COMBO_TIERS[1][1],
        },
    }


__all__ = ["DAYS", "Post", "SampleShop", "generate"]
