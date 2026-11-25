"""The stored daily facts of the data layer (batch-1124-c-data, decisions #62-#66). Pure: no I/O.

:mod:`materialize` hands one day's view and raw rows to these functions and upserts what they
return. Every value is an additive registry component (``services/metrics/components.py`` ids);
ratios are evaluated at read time, never stored. Missing is ``None``, never 0.

- :func:`scope_components` (F1): the profit-ladder components of one scope's order lines, from
  the code the screens already use (``shopee_profit.ladder.components_of`` for the covered lines,
  ``affiliate_cost`` for THE AFF cost, A1; ``ProfitBreakdown.offer_cost`` parts for Ưu đãi).
- :func:`item_report_splits` (A5): a product's GMV / đơn are Shopee's product report
  (``item_performance``) wherever it has a row that day; order lines only split what the report
  does not cover.
- :func:`ads_gmv_by_item` (A6): the ads-by-product GMV of a day, each campaign x product day
  counted once (``metrics.allocation.deoverlap_periods``).
- :func:`campaign_rows` (F3): one row per campaign and day from the Connector's
  ``ads_campaign_daily``, only when it spent or sold.
- :func:`channel_rows` (F2 / A7 / A9): the product-day split into Organic / Quảng cáo / TTLK x
  with / without a shop discount; the cells add up to the product row exactly.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from juli_backend.services.metrics.allocation import PeriodValue, deoverlap_periods
from juli_backend.services.shopee_analytics.metrics import SPLIT_LINES, ProductSplit, allocate
from juli_backend.services.shopee_profit.ladder import affiliate_cost, components_of, covered
from juli_backend.services.shopee_profit.order_profit import counts_in_sales

ZERO = Decimal(0)
CENT = Decimal("0.01")
ONE = Decimal(1)

#: the components the shop row and the product row both carry (column = registry id)
COMPONENT_COLUMNS: tuple[str, ...] = (
    "net_revenue",
    "net_revenue_known",
    "cogs",
    "cogs_known_gmv",
    "packaging",
    "fees",
    "shipping_net",
    "offer_promo",
    "offer_voucher",
    "offer_combo",
    "affiliate_commission",
    "affiliate_gmv",
)
#: ``product_metrics_daily.source`` of a product whose day stands on Shopee's product report
SPLIT_ITEM_REPORT = "item_report"
#: the product report (Hiệu quả của sản phẩm): per day, per item, all sources
ITEM_REPORT_DATASET = "item_performance"
CHANNELS: tuple[str, ...] = ("organic", "ads", "affiliate")
#: A9: with / without a shop discount; ``unknown`` = GMV no order line explains (never guessed)
DISCOUNT_STATES: tuple[str, ...] = ("with", "without", "unknown")
#: the money columns of a channel cell beside GMV (line based; ads / AFF costs added after)
_CELL_MONEY = (
    "net_revenue",
    "net_revenue_known",
    "cogs",
    "cogs_known_gmv",
    "packaging",
    "fees",
    "shipping_net",
    "offer_promo",
    "offer_voucher",
    "offer_combo",
    "affiliate_commission",
)


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(CENT, rounding=ROUND_HALF_UP)


# -- F1: components of a scope ---------------------------------------------------------------


def scope_components(pairs: Sequence[tuple[Any, Any]]) -> dict[str, Decimal | None]:
    """The components of one scope's lines (a shop day, or a product day). ``None`` for every
    column when the scope has no order line (no data, not 0).

    - ``net_revenue`` = Σ doanh thu thực of the lines not excluded (``ShopProfit.buyer_paid``);
      ``net_revenue_known`` and the ladder costs = the covered lines (every cost known), the
      ladder's own ``components_of``.
    - Ưu đãi = the parts of ``ProfitBreakdown.offer_cost`` over every line (the Tổng quan KPI).
    - ``affiliate_commission`` = ``ladder.affiliate_cost`` (A1: the AFF row, the profit term and
      the channel split read this one sum); ``affiliate_gmv`` = the affiliate-flagged sale lines.
    - ``cogs_known_gmv`` = the GMV of the covered sale lines (covered GMV).
    """
    if not pairs:
        return dict.fromkeys(COMPONENT_COLUMNS)
    ladder = components_of(pairs)
    sale = [(ln, pb) for ln, pb in pairs if counts_in_sales(ln)]
    return {
        "net_revenue": _q(sum((pb.revenue for _, pb in pairs if pb.excluded_reason is None), ZERO)),
        "net_revenue_known": _q(ladder["net_revenue_known"]),
        "cogs": _q(ladder["cogs"]),
        "cogs_known_gmv": _q(sum((ln.order_value for ln, pb in sale if covered(pb)), ZERO)),
        "packaging": _q(ladder["packaging"]),
        "fees": _q(ladder["fees"]),
        "shipping_net": _q(ladder["shipping_net"]),
        "offer_promo": _q(sum((pb.promo_discount for _, pb in pairs), ZERO)),
        "offer_voucher": _q(sum((pb.voucher for _, pb in pairs), ZERO)),
        "offer_combo": _q(sum((pb.bundle for _, pb in pairs), ZERO)),
        "affiliate_commission": _q(affiliate_cost(pairs) or ZERO),
        "affiliate_gmv": _q(sum((ln.order_value for ln, _ in sale if ln.affiliate), ZERO)),
    }


def pairs_by_product(pairs: Iterable[tuple[Any, Any]]) -> dict[str, list[tuple[Any, Any]]]:
    out: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    for ln, pb in pairs:
        out[ln.product_id].append((ln, pb))
    return out


# -- A5: the product report wins ---------------------------------------------------------------


@dataclass(frozen=True)
class ItemReport:
    """One product's day in Shopee's product report (confirmed basis)."""

    gmv: Decimal
    orders: int
    units: int | None = None


def item_report_splits(
    splits: Mapping[str, ProductSplit],
    report: Mapping[str, ItemReport],
    shop_gmv: Decimal | None,
) -> dict[str, ProductSplit]:
    """A5: the day's product splits with Shopee's product report over the order lines.

    A product with a report row takes its GMV / đơn (units from the report when it has them, else
    the lines'). A product with order lines and no report row shares what the report leaves of the
    shop GMV, by its line GMV (never more than that rest, never below 0). A report row of zeros is
    kept (0đ, A8). No report row on the day: the splits are returned unchanged."""
    if not report:
        return dict(splits)
    out: dict[str, ProductSplit] = {}
    for item, r in report.items():
        # A8 / contract §6: a report row of zeros IS a product day (0đ, not "—")
        base = splits.get(item)
        out[item] = ProductSplit(
            item,
            r.gmv,
            r.orders,
            r.units if r.units is not None else (base.units if base else 0),
            base.line_gmv if base else ZERO,
            base.line_orders if base else 0,
            SPLIT_ITEM_REPORT,
        )
    rest_items = {i: s for i, s in splits.items() if i not in report}
    if rest_items:
        taken = sum((s.gmv for s in out.values()), ZERO)
        rest = ZERO if shop_gmv is None else max(shop_gmv - taken, ZERO)
        weights = {i: s.line_gmv for i, s in rest_items.items() if s.line_gmv > 0}
        shares = allocate(rest, weights) if weights else {}
        for i, s in rest_items.items():
            out[i] = replace(s, gmv=shares.get(i, ZERO), basis=SPLIT_LINES)
    return out


# -- A6: ads-by-product GMV, each day once ---------------------------------------------------


@dataclass(frozen=True)
class AdReportRow:
    """One ``ads_campaign_period`` row of a product: campaign x item over ``start``..``end``."""

    campaign: str
    item_id: str
    start: date
    end: date
    #: the overlay GMV the channel split uses: direct sales, else the broad GMV
    gmv: Decimal
    #: the report's own fields (None = the row does not carry it)
    direct: Decimal | None = None
    impressions: Decimal | None = None
    clicks: Decimal | None = None
    orders: Decimal | None = None


#: the report fields de-overlapped per product day (stored column <- AdReportRow field)
AD_FIELDS: tuple[tuple[str, str], ...] = (
    ("ads_gmv", "gmv"),
    ("ads_gmv_direct", "direct"),
    ("ads_views", "impressions"),
    ("ads_clicks", "clicks"),
    ("ads_orders", "orders"),
)


def _deoverlap_field(rows: Iterable[AdReportRow], day: date, attr: str) -> dict[str, Decimal]:
    by_key: dict[tuple[str, str], list[PeriodValue]] = defaultdict(list)
    for r in rows:
        value = getattr(r, attr)
        if r.item_id and value is not None:
            by_key[(r.campaign, r.item_id)].append(PeriodValue(r.start, r.end, value))
    out: dict[str, Decimal] = {}
    for (_campaign, item), periods in by_key.items():
        value = deoverlap_periods(periods).get(day)
        if value is not None:
            out[item] = out.get(item, ZERO) + value
    return out


def ads_gmv_by_item(rows: Iterable[AdReportRow], day: date) -> dict[str, Decimal]:
    """A6 (registry ``ADS_PERIOD_RULE``): each product's ads GMV on ``day``: per campaign x
    product, its report windows de-overlapped (:func:`deoverlap_periods`), then summed over the
    campaigns. A product no window covers on the day is absent (missing, never 0)."""
    return _deoverlap_field(rows, day, "gmv")


def ads_figures_by_item(
    rows: Iterable[AdReportRow], day: date
) -> dict[str, dict[str, Decimal | None]]:
    """Every :data:`AD_FIELDS` column of each product on ``day``, each de-overlapped the A6 way
    (counts to whole numbers). A field no row carries stays None (missing, never 0)."""
    rows = list(rows)
    per_field = {col: _deoverlap_field(rows, day, attr) for col, attr in AD_FIELDS}
    items = set().union(*(v.keys() for v in per_field.values()))
    out: dict[str, dict[str, Decimal | None]] = {}
    for item in items:
        cells: dict[str, Decimal | None] = {}
        for col, _ in AD_FIELDS:
            v = per_field[col].get(item)
            if v is not None and col in ("ads_views", "ads_clicks", "ads_orders"):
                v = v.to_integral_value(ROUND_HALF_UP)
            cells[col] = v
        out[item] = cells
    return out


def ads_spend_known(
    spend: Decimal | None, known_gmv: Decimal | None, gmv: Decimal | None
) -> Decimal | None:
    """A2 (registry ``KNOWN_SHARE_RULE``): the ads spend of the covered orders of a scope-day:
    spend x min(1, cogs_known_gmv / gmv); no sale (gmv 0 / None) keeps the whole spend."""
    if spend is None:
        return None
    if gmv is None or gmv <= 0:
        return _q(spend)
    share = min(ONE, max(known_gmv or ZERO, ZERO) / gmv)
    return _q(spend * share)


# -- F3: campaign days -------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    return None if value is None else int(Decimal(str(value)))


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def campaign_rows(
    rows: Iterable[Any],
    *,
    shop_id: uuid.UUID,
    day: date,
    version: str,
    contribution_by_campaign: Mapping[str, Decimal | None] | None = None,
) -> list[dict[str, Any]]:
    """F3: one row per campaign of the Connector's ``ads_campaign_daily`` day (placed-orders row
    when the day has both bases, as ``loaders._connector_ad_days``). The shop-level row
    (segment ``all``) is not a campaign. Sparse: a campaign that neither spent nor sold has no
    row. ``contribution_by_campaign``: its products' contribution (None = unknown)."""
    chosen: dict[str, Any] = {}
    for r in rows:
        if r.segment == "all" or r.day != day:
            continue
        if r.segment not in chosen or r.order_type == "placed":
            chosen[r.segment] = r
    out: list[dict[str, Any]] = []
    for key, r in sorted(chosen.items()):
        extra = r.extra or {}
        spend = _dec(extra.get("cost"))
        gmv = _dec(r.gmv)
        if not (spend or gmv):
            continue
        out.append(
            {
                "shop_id": shop_id,
                "day": day,
                "campaign_id": key,
                "ad_type": (str(extra["ad_type"])[:32] if extra.get("ad_type") else None),
                "spend": _q(spend),
                "gmv": _q(gmv),
                "gmv_direct": _q(_dec(extra.get("direct_gmv"))),
                "orders": _int(r.orders),
                "orders_direct": _int(extra.get("direct_orders")),
                "impressions": _int(r.impressions),
                "clicks": _int(r.clicks),
                "contribution_products": _q((contribution_by_campaign or {}).get(key)),
                "daily_budget": _q(_dec(extra.get("daily_budget"))),
                "derivation_version": version,
            }
        )
    return out


# -- F2 / A7 / A9: channel x discount cells of a product day ---------------------------------


def is_discounted(ln: Any, pb: Any) -> bool:
    """A9 (owner #66): a line bought WITH a shop discount carries a seller subsidy (Chương Trình
    Của Shop / Flash Sale price), the shop voucher's share, or a combo discount."""
    return (
        pb.promo_discount > 0
        or pb.voucher > 0
        or pb.bundle > 0
        or (getattr(ln, "shop_voucher_share", ZERO) or ZERO) > 0
    )


def split_exact(
    total: Decimal, weights: Sequence[Decimal], quantum: Decimal = CENT
) -> list[Decimal]:
    """``total`` over ``weights`` (any sign of total), each piece rounded to ``quantum``, the last
    taking the rounding, so the pieces add up to ``total`` exactly. No weight: all on the last."""
    if not weights:
        return []
    w = sum(weights, ZERO)
    if w <= 0:
        return [*([ZERO] * (len(weights) - 1)), total]
    pieces = [(total * x / w).quantize(quantum, rounding=ROUND_HALF_UP) for x in weights[:-1]]
    return [*pieces, total - sum(pieces, ZERO)]


@dataclass
class _Group:
    gmv: Decimal = ZERO
    orders: set[str] = field(default_factory=set)
    units: int = 0
    sums: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(_CELL_MONEY, ZERO))


def _groups(pairs: Sequence[tuple[Any, Any]]) -> dict[tuple[bool, str], _Group]:
    """(affiliate, with/without) -> its sale GMV, orders and line components. A product-order is
    affiliate / discounted when any of its lines is (đơn once per order)."""
    aff_orders = {ln.order_id for ln, _ in pairs if ln.affiliate}
    disc_orders = {ln.order_id for ln, pb in pairs if is_discounted(ln, pb)}
    out: dict[tuple[bool, str], _Group] = {
        (a, d): _Group() for a in (True, False) for d in ("with", "without")
    }
    for ln, pb in pairs:
        key = (ln.order_id in aff_orders, "with" if ln.order_id in disc_orders else "without")
        g = out[key]
        comps = scope_components([(ln, pb)])
        for col in _CELL_MONEY:
            g.sums[col] += comps[col] or ZERO
        if counts_in_sales(ln):
            g.gmv += ln.order_value
            g.orders.add(ln.order_id)
            g.units += int(ln.qty or 0)
    return out


@dataclass(frozen=True)
class ChannelInput:
    """One product day: its stored totals and the inputs of the split."""

    item_id: str
    gmv: Decimal
    orders: int
    pairs: Sequence[tuple[Any, Any]]
    #: the de-overlapped ads-by-product GMV of the day (A6); None = no ads report row
    ads_gmv: Decimal | None
    ads_spend: Decimal | None
    #: the product row's units (None = split the lines' own units)
    units: int | None = None


def channel_rows(
    inp: ChannelInput, *, shop_id: uuid.UUID, day: date, version: str
) -> list[dict[str, Any]]:
    """F2 / A7 / A9: the product day as Organic / Quảng cáo / TTLK x with / without a shop
    discount, every column adding up to the product row exactly.

    - Channels (registry ``allocation.channel_partition``, A7): TTLK = the affiliate-flagged
      orders (the order-line flag the conversion report sets), first; Quảng cáo = the ads report's
      GMV of the product, capped at what TTLK leaves; Organic = the rest. A cap that bites is
      stored (``capped_gmv`` on the channel's ``without`` cell: what the source said beyond the
      cap), never hidden.
    - đơn: TTLK = its distinct orders (capped at the product's đơn); Quảng cáo = the non-affiliate
      orders x its GMV share, capped at what is left; Organic = the rest.
    - Discount state (A9): each channel's GMV / đơn split by its own lines' with / without share;
      GMV the lines do not explain (the product report above its lines) is ``unknown``.
    - Line components (doanh thu thực, giá vốn, phí, Ưu đãi, AFF commission...): TTLK = its lines
      exactly; Quảng cáo / Organic = the non-affiliate lines x the Quảng cáo share of their GMV.
    - The product's ad spend sits on the Quảng cáo cells (split by their GMV), never elsewhere.
    Sparse: an empty cell is not returned."""
    g = _groups(inp.pairs)
    line_aff = g[(True, "with")].gmv + g[(True, "without")].gmv
    total = inp.gmv
    aff_gmv = min(max(line_aff, ZERO), max(total, ZERO))
    ads_in = inp.ads_gmv
    ads_gmv = ZERO if ads_in is None else min(max(ads_in, ZERO), max(total - aff_gmv, ZERO))
    organic_gmv = total - aff_gmv - ads_gmv
    capped = {
        "affiliate": max(line_aff - aff_gmv, ZERO),
        "ads": ZERO if ads_in is None else max(ads_in - ads_gmv, ZERO),
        "organic": ZERO,
    }
    non_aff = total - aff_gmv
    share = ZERO if non_aff <= 0 else min(ONE, ads_gmv / non_aff)
    # đơn
    o_aff_line = len(g[(True, "with")].orders) + len(g[(True, "without")].orders)
    o_rest_line = len(g[(False, "with")].orders) + len(g[(False, "without")].orders)
    o_aff = min(o_aff_line, max(inp.orders, 0))
    o_ads_raw = int((Decimal(o_rest_line) * share).to_integral_value(ROUND_HALF_UP))
    o_ads = min(o_ads_raw, inp.orders - o_aff)
    o_org = inp.orders - o_aff - o_ads

    cells: dict[tuple[str, str], dict[str, Decimal]] = {}

    def by_state(channel: str, gmv: Decimal, orders: int, aff: bool, part: Decimal) -> None:
        """``part`` = the share of the group's lines this channel stands on (TTLK: all of its
        lines; Quảng cáo / Organic: the non-affiliate lines x their share), so two channels never
        explain the same line."""
        w_gmv = [g[(aff, "with")].gmv * part, g[(aff, "without")].gmv * part]
        lines = sum(w_gmv, ZERO)
        explained = min(max(gmv, ZERO), lines) if lines > 0 else ZERO
        unknown = gmv - explained
        gw, gwo = split_exact(explained, w_gmv) if lines > 0 else (ZERO, ZERO)
        w_o = [
            Decimal(len(g[(aff, "with")].orders)) * part,
            Decimal(len(g[(aff, "without")].orders)) * part,
        ]
        line_orders = sum(w_o, ZERO).to_integral_value(ROUND_HALF_UP)
        if line_orders > 0:
            # đơn beyond the lines' own count (GMV with no line) are unknown
            known = Decimal(orders) if unknown == 0 else min(Decimal(orders), line_orders)
            ow, owo = split_exact(known, w_o, ONE)
            ou = Decimal(orders) - known
        else:
            ow = owo = ZERO
            ou = Decimal(orders)
        for state, cg, co in (("with", gw, ow), ("without", gwo, owo), ("unknown", unknown, ou)):
            cells[(channel, state)] = {"gmv": cg, "orders": co}

    by_state("affiliate", aff_gmv, o_aff, True, ONE)
    by_state("ads", ads_gmv, o_ads, False, share)
    by_state("organic", organic_gmv, o_org, False, ONE - share)
    # units: the lines' own units per cell (TTLK its lines, Quảng cáo / Organic their share of
    # the rest); what the product row holds beyond them is ``unknown`` on Organic
    line_units = [
        (ch, st, Decimal(g[(aff, st)].units) * part)
        for ch, aff, part in (
            ("affiliate", True, ONE),
            ("ads", False, share),
            ("organic", False, ONE - share),
        )
        for st in ("with", "without")
    ]
    lines_total = sum((u for *_, u in line_units), ZERO).to_integral_value(ROUND_HALF_UP)
    units_total = Decimal(inp.units) if inp.units is not None else lines_total
    known_units = min(units_total, lines_total)
    pieces = split_exact(known_units, [u for *_, u in line_units], ONE) if lines_total > 0 else []
    for (ch, st, _), piece in zip(line_units, pieces, strict=False):
        cells[(ch, st)]["units"] = piece
    cells[("organic", "unknown")]["units"] = units_total - known_units
    # line components
    for state in ("with", "without"):
        a, n = g[(True, state)].sums, g[(False, state)].sums
        for col in _CELL_MONEY:
            cells[("affiliate", state)][col] = a[col]
            ads_part = (n[col] * share).quantize(CENT, rounding=ROUND_HALF_UP)
            cells[("ads", state)][col] = ads_part
            cells[("organic", state)][col] = n[col] - ads_part
    # the product's ad spend on its Quảng cáo cells
    spend = inp.ads_spend
    ads_states = ("with", "without", "unknown")
    weights = [cells[("ads", st)]["gmv"] for st in ads_states]
    if spend is None:
        spend_parts = [ZERO, ZERO, ZERO]
    elif sum(weights, ZERO) <= 0:  # an ad-only day: the spend has no sale to follow
        spend_parts = [ZERO, spend, ZERO]
    else:
        spend_parts = split_exact(spend, weights)
    out: list[dict[str, Any]] = []
    for channel in CHANNELS:
        for state in DISCOUNT_STATES:
            cell = cells.get((channel, state), {})
            row: dict[str, Any] = {
                "shop_id": shop_id,
                "day": day,
                "item_id": inp.item_id,
                "channel": channel,
                "discounted": state,
                "gmv": _q(cell.get("gmv", ZERO)),
                "orders": int(cell.get("orders", ZERO)),
                "units": int(cell.get("units", ZERO)),
                **{col: _q(cell.get(col)) if col in cell else None for col in _CELL_MONEY},
                "ads_spend": None,
                "capped_gmv": None,
                "derivation_version": version,
            }
            # structural 0: only Quảng cáo cells carry ad spend; NULL = the spend is unknown
            if channel != "ads":
                row["ads_spend"] = ZERO
            elif spend is not None:
                row["ads_spend"] = _q(spend_parts[ads_states.index(state)])
            if capped[channel] > 0 and state == "without":
                row["capped_gmv"] = _q(capped[channel])
            out.append(row)
    kept = [r for r in out if _non_empty(r)]
    if not kept and inp.gmv == 0 and inp.orders == 0:
        # A8 / contract §6: the product day was reported (zeros): one zero cell, never "no data"
        kept = [r for r in out if r["channel"] == "organic" and r["discounted"] == "without"]
    return kept


def _non_empty(row: Mapping[str, Any]) -> bool:
    keys = ("gmv", "orders", "units", "ads_spend", "capped_gmv", *_CELL_MONEY)
    return any(row.get(k) not in (None, 0, ZERO) for k in keys)


__all__ = [
    "CHANNELS",
    "COMPONENT_COLUMNS",
    "DISCOUNT_STATES",
    "ITEM_REPORT_DATASET",
    "SPLIT_ITEM_REPORT",
    "AdReportRow",
    "ChannelInput",
    "ItemReport",
    "AD_FIELDS",
    "ads_figures_by_item",
    "ads_gmv_by_item",
    "ads_spend_known",
    "campaign_rows",
    "channel_rows",
    "is_discounted",
    "item_report_splits",
    "pairs_by_product",
    "scope_components",
    "split_exact",
]
