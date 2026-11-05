"""KOL x product x channel: who sells what, at what profit, and what a sample cost (P91 D-9, D-11).

One row = a creator (KOL) x a product x a channel (Shopee Video / Facebook / TikTok ...), built
from the affiliate-marked ``shopee_order_lines`` (migration 118 carries the KOL on the line).

Commission is per order line, from the rate that applied to the product (``kol_rates``: the
report's own ``Chi phí(₫)`` wins, else the targeted rate, else the open rate, applied to the
line's ``buyer_paid``). Everything else is the shop's own profit waterfall: the lines are run
through ``engine.profit_pairs`` again with the resolved commission, so fees, giá vốn (imported,
else the labelled 1/3 fallback) and đóng gói are exactly the figures every other screen uses.

Per row (all money in VND, the window's confirmed lines):

- ``orders`` / ``units`` / ``gmv``: confirmed order lines (GMV = deal price x qty).
- ``net_profit``: contribution of the profit-carrying lines (delivered / accepted refund) after
  platform fees, giá vốn, đóng gói and commission; before shop advertising.
- ``sample_cost``: the Mẫu KOL shipments (sent on or before the window end) of the KOL x product,
  ``qty x (giá vốn + đóng gói) + phí ship``, split over the pair's channel rows by orders.
- ``roi_incl_samples = (net_profit - sample_cost) / (commission + sample_cost)``.
- ``roi_shopee``: the ``ROI`` of Shopee's creator export, as exported, never recomputed. That
  export is per creator (not per product), so every row of a KOL carries the same value.
- ``kol_clicks`` / ``kol_conversion``: Shopee's creator export has clicks per creator only, so a
  pair's own clicks are not known (``clicks`` is null); the conversion shown is the creator's
  orders / clicks of the same export.
- ``payback_orders``: orders of this pair needed to earn the sample back at the pair's net per
  order (null without a sample, or when the pair earns nothing).
- ``low_data``: fewer than :data:`ORDERS_THRESHOLD` (10) orders for the KOL x product pair.

``KolPool`` carries the same facts, detached, for the cards (``shopee_recommendations.kol_cards``).
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.ingest.kol_key import normal_handle
from juli_backend.services.shop_inputs import kol_samples
from juli_backend.services.shop_inputs.kol_samples import Shipment, UnitCost
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.engine import ShopLine, profit_pairs
from juli_backend.services.shopee_analytics.fmt import num
from juli_backend.services.shopee_analytics.kol_rates import (
    SRC_REPORT,
    RateBook,
    load_rate_book,
    resolve_line_commission,
)
from juli_backend.services.shopee_analytics.loaders import AffiliatePartner, ShopContext
from juli_backend.services.shopee_profit.money import ZERO

#: D-11: fewer than this many orders for a KOL x product pair = "Ít dữ liệu".
ORDERS_THRESHOLD = 10
LOW_DATA_LABEL = "Ít dữ liệu"
#: A product's per-order economics come from its affiliate orders once it has this many.
AFFILIATE_BASIS_MIN_ORDERS = 3
SORTS = ("net_profit", "orders", "gmv", "roi_incl_samples", "commission")
ROI_SHOPEE_LABEL = "ROI Shopee (chỉ hoa hồng)"
ROI_SELF_LABEL = "ROI (gồm mẫu)"
NO_ORDERS_CHANNEL = "Chưa có đơn"
UNKNOWN_CHANNEL = "Không rõ kênh"


@dataclass
class KolData:
    """What the KOL view reads besides the shop's period view."""

    book: RateBook = field(default_factory=RateBook)
    #: (kol_key, SKU scope) -> shipments
    samples: dict[tuple[str, str], list[Shipment]] = field(default_factory=dict)


async def load_kol_data(session: AsyncSession, shop_id: uuid.UUID) -> KolData:
    return KolData(
        book=await load_rate_book(session, shop_id),
        samples=await kol_samples.load_samples(session, shop_id),
    )


# ---------------------------------------------------------------------------- the lines


@dataclass(frozen=True)
class KolLine:
    kol_key: str
    handle: str
    channel: str
    item_id: str
    order_id: str
    day: date
    qty: int
    gmv: Decimal
    base: Decimal
    commission: Decimal | None
    commission_source: str
    carries_profit: bool
    contribution: Decimal | None
    mcn: bool | None
    campaign_type: str | None


def patched_lines(view: PeriodView, data: KolData) -> list[ShopLine]:
    """The view's lines with every affiliate line's commission resolved (see ``kol_rates``)."""
    out: list[ShopLine] = []
    for sl in view.lines:
        ln = sl.line
        if not ln.affiliate:
            out.append(sl)
            continue
        commission, _ = resolve_line_commission(
            reported=ln.commission,
            base=ln.buyer_paid,
            item_id=ln.product_id,
            on=ln.order_date,
            campaign_type=sl.kol.campaign_type if sl.kol else None,
            book=data.book,
        )
        out.append(replace(sl, line=replace(ln, commission=commission)))
    return out


@dataclass
class Lines:
    tagged: list[KolLine]
    untagged: int
    missing: int
    #: every line of the view with its patched waterfall: (ShopLine, contribution|None, commission)
    all_pairs: list[tuple[ShopLine, Decimal | None, Decimal | None, bool]]


def collect(view: PeriodView, data: KolData) -> Lines:
    lines = patched_lines(view, data)
    pairs = profit_pairs(lines, view.costs, view.fees)
    tagged: list[KolLine] = []
    all_pairs: list[tuple[ShopLine, Decimal | None, Decimal | None, bool]] = []
    untagged = missing = 0
    for orig, sl, (ln, pb) in zip(view.lines, lines, pairs, strict=True):
        carries = pb.excluded_reason is None
        all_pairs.append((sl, pb.contribution, pb.commission, carries))
        if not ln.affiliate:
            continue
        if ln.product_id in view.excluded:  # P92 B-1: no KOL row, no card; shop totals keep it
            continue
        if sl.kol is None:
            untagged += 1
            continue
        _, source = resolve_line_commission(
            reported=orig.line.commission,
            base=ln.buyer_paid,
            item_id=ln.product_id,
            on=ln.order_date,
            campaign_type=sl.kol.campaign_type,
            book=data.book,
        )
        if ln.commission is None:
            missing += 1
        tagged.append(
            KolLine(
                kol_key=sl.kol.key,
                handle=sl.kol.handle,
                channel=sl.kol.channel or UNKNOWN_CHANNEL,
                item_id=ln.product_id,
                order_id=ln.order_id,
                day=ln.order_date,
                qty=ln.qty,
                gmv=ln.order_value,
                base=ln.buyer_paid,
                commission=pb.commission if carries else None,
                commission_source=source,
                carries_profit=carries,
                contribution=pb.contribution if carries else None,
                mcn=sl.kol.mcn,
                campaign_type=sl.kol.campaign_type,
            )
        )
    return Lines(tagged, untagged, missing, all_pairs)


# --------------------------------------------------------------------------------- rows


@dataclass
class KolRow:
    kol_key: str
    handle: str
    channel: str
    item_id: str
    product_name: str
    orders: int = 0
    units: int = 0
    gmv: Decimal = ZERO
    base: Decimal = ZERO
    commission: Decimal = ZERO
    net_profit: Decimal = ZERO
    profit_orders: int = 0
    unknown_lines: int = 0
    sources: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    pair_orders: int = 0
    sample_cost: Decimal | None = None
    sample_qty: int = 0
    sample_basis: str | None = None
    mcn: bool | None = None
    campaign_type: str | None = None
    roi_shopee: Decimal | None = None
    kol_clicks: Decimal | None = None
    kol_conversion: Decimal | None = None
    #: internal (hashed refs never leave the service): the distinct orders of the row
    order_ids: set[str] = field(default_factory=set, repr=False)

    @property
    def low_data(self) -> bool:
        return self.pair_orders < ORDERS_THRESHOLD

    @property
    def profit_after_samples(self) -> Decimal:
        return self.net_profit - (self.sample_cost or ZERO)

    @property
    def roi_incl_samples(self) -> Decimal | None:
        denominator = self.commission + (self.sample_cost or ZERO)
        if denominator <= 0:
            return None
        return self.profit_after_samples / denominator

    @property
    def payback_orders(self) -> int | None:
        sample = self.sample_cost or ZERO
        if sample <= 0 or self.profit_orders <= 0 or self.net_profit <= 0:
            return None
        return math.ceil(sample / (self.net_profit / self.profit_orders))

    def json(self) -> dict[str, Any]:
        roi = self.roi_incl_samples
        return {
            "kol_key": self.kol_key,
            "handle": self.handle,
            "channel": self.channel,
            "item_id": self.item_id,
            "product_name": self.product_name,
            "orders": self.orders,
            "units": self.units,
            "gmv": num(self.gmv),
            "clicks": None,
            "kol_clicks": num(self.kol_clicks),
            "kol_conversion": None
            if self.kol_conversion is None
            else float(round(self.kol_conversion, 6)),
            "commission": num(self.commission),
            "commission_rate": None
            if self.base <= 0
            else float(round(self.commission / self.base, 6)),
            "commission_sources": dict(sorted(self.sources.items())),
            "net_profit": num(self.net_profit),
            "profit_orders": self.profit_orders,
            "unknown_lines": self.unknown_lines,
            "sample_qty": self.sample_qty,
            "sample_cost": None if self.sample_cost is None else num(self.sample_cost),
            "sample_cost_basis": self.sample_basis,
            "profit_after_samples": num(self.profit_after_samples),
            "roi_incl_samples": None if roi is None else float(round(roi, 4)),
            "roi_shopee": None if self.roi_shopee is None else float(self.roi_shopee),
            "payback_orders": self.payback_orders,
            "pair_orders": self.pair_orders,
            "low_data": self.low_data,
            "low_data_label": LOW_DATA_LABEL if self.low_data else None,
            "mcn": self.mcn,
            "campaign_type": self.campaign_type,
            "card": None,
        }


@dataclass(frozen=True)
class KolStat:
    """Per creator, for the cards."""

    key: str
    handle: str
    channel: str
    line_orders: int
    partner_orders: Decimal | None
    partner_clicks: Decimal | None
    clicks_per_30d: Decimal | None
    roi_shopee: Decimal | None
    shipments: int
    typical_qty: int | None
    last_ship_fee: Decimal | None

    @property
    def conv_raw(self) -> Decimal | None:
        if not self.partner_clicks or self.partner_orders is None:
            return None
        return self.partner_orders / self.partner_clicks

    @property
    def orders_seen(self) -> int:
        """Orders the shrinkage trusts: Shopee's creator export, else our own marked lines."""
        if self.partner_orders is not None:
            return int(self.partner_orders)
        return self.line_orders


@dataclass(frozen=True)
class PairStat:
    orders: int
    units: int
    gmv: Decimal
    net_profit: Decimal
    commission: Decimal


@dataclass(frozen=True)
class ProductStat:
    """The per-order economics of a product that a forecast scales (before commission)."""

    item_id: str
    name: str
    orders: int
    aff_orders: int
    basis: str  # "affiliate" | "all"
    units_per_order: Decimal
    aov: Decimal
    base_per_order: Decimal
    precommission_per_order: Decimal
    rate: Decimal | None
    rate_source: str
    aff_clicks: Decimal | None
    aff_conv: Decimal | None
    unit_cost: UnitCost | None
    in_stock: bool | None


@dataclass
class KolPool:
    """Everything a KOL forecast needs, detached."""

    window_days: int
    kols: dict[str, KolStat] = field(default_factory=dict)
    pairs: dict[tuple[str, str], PairStat] = field(default_factory=dict)
    products: dict[str, ProductStat] = field(default_factory=dict)
    shop_conv: Decimal | None = None
    #: channel -> affiliate orders; (item, channel) -> affiliate orders; item -> affiliate orders
    channel_orders: dict[str, int] = field(default_factory=dict)
    item_channel_orders: dict[tuple[str, str], int] = field(default_factory=dict)
    item_aff_orders: dict[str, int] = field(default_factory=dict)
    aff_orders_total: int = 0
    default_ship_fee: Decimal | None = None
    #: (kol_key, item) pairs a shipment was recorded for
    sent_pairs: set[tuple[str, str]] = field(default_factory=set)


@dataclass
class KolModel:
    window: dict[str, Any]
    rows: list[KolRow]
    pool: KolPool
    untagged_lines: int
    missing_commission_lines: int
    partner_period: dict[str, Any] | None


def _match_partner(
    partners: list[AffiliatePartner], key: str, handle: str
) -> AffiliatePartner | None:
    wanted = normal_handle(handle)
    for p in partners:
        if p.key == key:
            return p
    for p in partners:
        if wanted and normal_handle(p.handle) == wanted:
            return p
    return None


def _item_of(sku_scope: str) -> str:
    return sku_scope.partition(":")[0]


def sample_unit_cost(ctx: ShopContext, view: PeriodView, sku_scope: str) -> UnitCost | None:
    """giá vốn + đóng gói of one unit of a SKU scope (``item`` or ``item:variation``). An item
    named without variation takes the mean of its variations' imported costs when it has no own."""
    item_id = _item_of(sku_scope)
    info = ctx.catalog.items.get(item_id)
    list_price = info.list_price if info and info.list_price else None
    if list_price is None:
        prices = [p for k, p in view.costs.list_price.items() if k in (sku_scope, item_id)]
        list_price = max(prices) if prices else None
    if list_price is None:
        prices = [ln.original_price for ln, _ in view.pairs if ln.product_id == item_id]
        list_price = max(prices) if prices else None
    sku_cost = dict(ctx.rules.sku_cost)
    packaging = dict(ctx.rules.packaging_by_key)
    for table in (sku_cost, packaging):
        if sku_scope in table:
            continue
        # the import keys a cost by item / item:variation, the order export by seller SKU
        skus: list[str | None] = []
        if info is not None:
            if ":" in sku_scope:
                variation = sku_scope.partition(":")[2]
                skus = [v.seller_sku for v in info.variations if v.variation_id == variation]
            else:
                skus = [info.seller_sku, *(v.seller_sku for v in info.variations)]
        values = [table[k] for k in skus if k and k in table]
        if ":" not in sku_scope:
            values += [v for k, v in table.items() if k.startswith(f"{sku_scope}:")]
        if values:
            table[sku_scope] = sum(values, ZERO) / len(values)
    return kol_samples.unit_cost(
        sku_scope=sku_scope,
        item_id=item_id,
        list_price=list_price,
        sku_cost=sku_cost,
        product_cost=dict(ctx.rules.product_cost),
        packaging=packaging,
    )


def _sample_totals(
    ctx: ShopContext, view: PeriodView, data: KolData
) -> dict[tuple[str, str], tuple[Decimal | None, int, str | None]]:
    """``(kol_key, item) -> (cost, qty, basis)``; cost None = a shipment has no cost to price."""
    out: dict[tuple[str, str], tuple[Decimal | None, int, str | None]] = {}
    end = view.window.end
    for (key, sku_scope), shipments in data.samples.items():
        sent = [s for s in shipments if s.sent_on <= end]
        if not sent:
            continue
        unit = sample_unit_cost(ctx, view, sku_scope)
        cost = kol_samples.sample_cost(sent, unit)
        item = _item_of(sku_scope)
        prev_cost, prev_qty, prev_basis = out.get((key, item), (ZERO, 0, None))
        total = None if cost is None or prev_cost is None else prev_cost + cost
        basis = unit.cogs_source if unit else None
        if prev_basis == "assumed" or basis == "assumed":
            basis = "assumed"
        out[(key, item)] = (total, prev_qty + sum(s.qty for s in sent), basis or prev_basis)
    return out


def compute(view: PeriodView, ctx: ShopContext, data: KolData) -> KolModel:
    found = collect(view, data)
    partners = view.data.affiliate.partners
    sample = _sample_totals(ctx, view, data)

    rows: dict[tuple[str, str, str], KolRow] = {}
    profit_sets: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    pair_orders: dict[tuple[str, str], set[str]] = defaultdict(set)
    for kl in found.tagged:
        key = (kl.kol_key, kl.item_id, kl.channel)
        row = rows.get(key)
        if row is None:
            row = rows[key] = KolRow(
                kl.kol_key, kl.handle, kl.channel, kl.item_id, view.names.get(kl.item_id, "")
            )
        row.units += kl.qty
        row.gmv += kl.gmv
        row.base += kl.base
        row.sources[kl.commission_source] += 1
        row.mcn = kl.mcn if row.mcn is None else row.mcn
        row.campaign_type = row.campaign_type or kl.campaign_type
        row.order_ids.add(kl.order_id)
        pair_orders[(kl.kol_key, kl.item_id)].add(kl.order_id)
        if kl.carries_profit:
            profit_sets[key].add(kl.order_id)
            row.commission += kl.commission or ZERO
            if kl.contribution is None:
                row.unknown_lines += 1
            else:
                row.net_profit += kl.contribution
    handles = {kk: s.handle for (kk, _), ss in data.samples.items() for s in ss[:1]}
    handles.update({r.kol_key: r.handle for r in rows.values()})
    for kol_key, item in sample:  # a pair with samples and no order yet still gets a row
        if item in view.excluded:  # P92 B-1
            continue
        if not any(k[0] == kol_key and k[1] == item for k in rows):
            rows[(kol_key, item, NO_ORDERS_CHANNEL)] = KolRow(
                kol_key,
                handles.get(kol_key, kol_key),
                NO_ORDERS_CHANNEL,
                item,
                view.names.get(item) or ctx.catalog.name(item),
            )
    by_pair: dict[tuple[str, str], list[KolRow]] = defaultdict(list)
    for key, row in rows.items():
        row.orders = len(row.order_ids)
        row.profit_orders = len(profit_sets.get(key, ()))
        by_pair[(key[0], key[1])].append(row)
    for (kol_key, item), pair_rows in by_pair.items():
        n = len(pair_orders.get((kol_key, item), ()))
        total_orders = sum(r.orders for r in pair_rows)
        cost, qty, basis = sample.get((kol_key, item), (ZERO, 0, None))
        has_sample = (kol_key, item) in sample
        for r in pair_rows:
            r.pair_orders = n
            if not has_sample:
                continue
            r.sample_qty = qty
            r.sample_basis = basis
            if cost is not None:
                share = (
                    Decimal(r.orders) / Decimal(total_orders)
                    if total_orders
                    else Decimal(1) / Decimal(len(pair_rows))
                )
                r.sample_cost = cost * share
    for r in rows.values():
        partner = _match_partner(partners, r.kol_key, r.handle)
        if partner is not None:
            r.roi_shopee = partner.roi
            r.kol_clicks = partner.clicks
            r.kol_conversion = (partner.orders / partner.clicks) if partner.clicks else None
    choice = view.data.affiliate.choice
    return KolModel(
        window=view.window.json(),
        rows=sorted(rows.values(), key=lambda r: (-r.net_profit, r.handle, r.item_id, r.channel)),
        pool=_pool(view, ctx, data, found, rows, partners, handles),
        untagged_lines=found.untagged,
        missing_commission_lines=found.missing,
        partner_period=choice.json() if choice.periods else None,
    )


# ---------------------------------------------------------------------------------- pool


def _pool(
    view: PeriodView,
    ctx: ShopContext,
    data: KolData,
    found: Lines,
    rows: dict[tuple[str, str, str], KolRow],
    partners: list[AffiliatePartner],
    handles: dict[str, str],
) -> KolPool:
    pool = KolPool(window_days=view.window.days)
    # -- per pair and per channel, from the tagged lines
    pair_acc: dict[tuple[str, str], list[Any]] = defaultdict(lambda: [set(), 0, ZERO, ZERO, ZERO])
    chan_orders: dict[str, set[str]] = defaultdict(set)
    item_chan: dict[tuple[str, str], set[str]] = defaultdict(set)
    item_aff: dict[str, set[str]] = defaultdict(set)
    kol_orders: dict[str, set[str]] = defaultdict(set)
    kol_chan: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_aff: set[str] = set()
    for kl in found.tagged:
        acc = pair_acc[(kl.kol_key, kl.item_id)]
        acc[0].add(kl.order_id)
        acc[1] += kl.qty
        acc[2] += kl.gmv
        if kl.carries_profit:
            acc[3] += kl.contribution or ZERO
            acc[4] += kl.commission or ZERO
        chan_orders[kl.channel].add(kl.order_id)
        item_chan[(kl.item_id, kl.channel)].add(kl.order_id)
        item_aff[kl.item_id].add(kl.order_id)
        kol_orders[kl.kol_key].add(kl.order_id)
        kol_chan[kl.kol_key][kl.channel] += 1
        all_aff.add(kl.order_id)
    pool.pairs = {k: PairStat(len(a[0]), a[1], a[2], a[3], a[4]) for k, a in pair_acc.items()}
    pool.channel_orders = {c: len(s) for c, s in chan_orders.items()}
    pool.item_channel_orders = {k: len(s) for k, s in item_chan.items()}
    pool.item_aff_orders = {k: len(s) for k, s in item_aff.items()}
    pool.aff_orders_total = len(all_aff)

    # -- creators: lines, samples, Shopee's creator export
    keys = set(kol_orders) | {k for k, _ in data.samples}
    matched: dict[str, AffiliatePartner] = {}
    for key in keys:
        p = _match_partner(partners, key, handles.get(key, ""))
        if p is not None:
            matched[key] = p
    for p in partners:  # creators with an export row and no marked line yet
        if p.key not in keys and p.key not in {m.key for m in matched.values()}:
            keys.add(p.key)
            matched[p.key] = p
            handles.setdefault(p.key, p.handle)
    fees = [s.ship_fee for ss in data.samples.values() for s in ss]
    pool.default_ship_fee = Decimal(str(median(fees))) if fees else None
    for key in keys:
        p = matched.get(key)
        ships = [s for (k, _), ss in data.samples.items() if k == key for s in ss]
        chans = kol_chan.get(key) or {}
        channel = max(chans, key=lambda c: (chans[c], c)) if chans else UNKNOWN_CHANNEL
        days = (p.period[1] - p.period[0]).days + 1 if p else 0
        pool.kols[key] = KolStat(
            key=key,
            handle=handles.get(key) or (p.handle if p else key),
            channel=channel,
            line_orders=len(kol_orders.get(key, ())),
            partner_orders=p.orders if p else None,
            partner_clicks=p.clicks if p else None,
            clicks_per_30d=(p.clicks / days * 30) if p and days > 0 else None,
            roi_shopee=p.roi if p else None,
            shipments=len(ships),
            typical_qty=int(median([s.qty for s in ships])) if ships else None,
            last_ship_fee=max(ships, key=lambda s: s.sent_on).ship_fee if ships else None,
        )
    pool.sent_pairs = {(k, _item_of(sc)) for (k, sc) in data.samples}
    tot_o = sum((p.orders for p in matched.values()), ZERO)
    tot_c = sum((p.clicks for p in matched.values()), ZERO)
    pool.shop_conv = tot_o / tot_c if tot_c > 0 else None

    # -- products: per-order economics before commission
    by_item: dict[str, list[tuple[ShopLine, Decimal | None, Decimal | None]]] = defaultdict(list)
    for sl, contribution, commission, carries in found.all_pairs:
        if carries:
            by_item[sl.line.product_id].append((sl, contribution, commission))
    for item, items in by_item.items():
        aff = [t for t in items if t[0].line.affiliate]
        aff_orders = len({t[0].line.order_id for t in aff})
        basis = "affiliate" if aff_orders >= AFFILIATE_BASIS_MIN_ORDERS else "all"
        use = aff if basis == "affiliate" else items
        orders = len({t[0].line.order_id for t in use})
        known = [t for t in use if t[1] is not None]
        if orders == 0 or not known:
            continue
        units = sum(t[0].line.qty for t in use)
        gmv = sum((t[0].line.order_value for t in use), ZERO)
        base = sum((t[0].line.buyer_paid for t in use), ZERO)
        pre = sum(((t[1] or ZERO) + (t[2] or ZERO) for t in known), ZERO)
        known_orders = len({t[0].line.order_id for t in known})
        rate, source = data.book.current(item)
        if rate is None:
            reported = [t for t in aff if t[2] is not None]
            paid = sum((t[0].line.buyer_paid for t in reported), ZERO)
            if paid > 0:
                rate = sum((t[2] or ZERO for t in reported), ZERO) / paid
                source = SRC_REPORT
        o, c = view.data.affiliate.product_stats.get(item, (ZERO, ZERO))
        info = ctx.catalog.items.get(item)
        pool.products[item] = ProductStat(
            item_id=item,
            name=view.names.get(item) or ctx.catalog.name(item),
            orders=orders,
            aff_orders=aff_orders,
            basis=basis,
            units_per_order=Decimal(units) / orders,
            aov=gmv / orders,
            base_per_order=base / orders,
            precommission_per_order=pre / known_orders,
            rate=rate,
            rate_source=source,
            aff_clicks=c if c > 0 else None,
            aff_conv=(o / c) if c > 0 else None,
            unit_cost=sample_unit_cost(ctx, view, item),
            in_stock=None if info is None or info.stock is None else info.stock > 0,
        )
    return pool


# --------------------------------------------------------------------------------- JSON


def _totals(rows: list[KolRow]) -> dict[str, Any]:
    orders: set[str] = set()
    for r in rows:
        orders |= r.order_ids
    commission = sum((r.commission for r in rows), ZERO)
    net = sum((r.net_profit for r in rows), ZERO)
    samples = [r.sample_cost for r in rows]
    sample = (
        None
        if any(s is None and r.sample_qty for s, r in zip(samples, rows, strict=True))
        else sum((s or ZERO for s in samples), ZERO)
    )
    denominator = commission + (sample or ZERO)
    return {
        "rows": len(rows),
        "kols": len({r.kol_key for r in rows}),
        "orders": len(orders),
        "units": sum(r.units for r in rows),
        "gmv": num(sum((r.gmv for r in rows), ZERO)),
        "commission": num(commission),
        "net_profit": num(net),
        "sample_cost": None if sample is None else num(sample),
        "profit_after_samples": num(net - (sample or ZERO)),
        "roi_incl_samples": None
        if denominator <= 0
        else float(round((net - (sample or ZERO)) / denominator, 4)),
    }


def table(
    model: KolModel,
    *,
    channel: str | None = None,
    item_id: str | None = None,
    kol: str | None = None,
    sort: str = "net_profit",
    limit: int | None = None,
) -> dict[str, Any]:
    """Phân tích › KOL: the rows (optionally one channel / product / creator), the filters the
    screen offers (always from ALL rows) and the totals of the rows shown."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {list(SORTS)}")
    keep = [
        r
        for r in model.rows
        if (channel is None or r.channel == channel)
        and (item_id is None or r.item_id == item_id)
        and (kol is None or r.kol_key == kol or normal_handle(r.handle) == normal_handle(kol))
    ]

    def sort_key(r: KolRow) -> tuple[float, str, str]:
        value = {
            "net_profit": r.net_profit,
            "orders": Decimal(r.orders),
            "gmv": r.gmv,
            "commission": r.commission,
            "roi_incl_samples": r.roi_incl_samples,
        }[sort]
        return (-(float(value) if value is not None else float("-inf")), r.handle, r.item_id)

    keep.sort(key=sort_key)
    shown = keep if limit is None else keep[:limit]
    products = {r.item_id: r.product_name for r in model.rows}
    return {
        "window": model.window,
        "rows": [r.json() for r in shown],
        "totals": _totals(keep),
        "filters": {
            "channels": sorted({r.channel for r in model.rows}),
            "products": [
                {"item_id": i, "name": n} for i, n in sorted(products.items(), key=lambda t: t[1])
            ],
            "kols": [
                {"kol_key": k, "handle": h}
                for k, h in sorted({(r.kol_key, r.handle) for r in model.rows}, key=lambda t: t[1])
            ],
        },
        "applied": {"channel": channel, "item_id": item_id, "kol": kol, "sort": sort},
        "labels": {
            "roi_self": ROI_SELF_LABEL,
            "roi_shopee": ROI_SHOPEE_LABEL,
            "low_data": LOW_DATA_LABEL,
            "roi_formula": "(lợi nhuận ròng − chi phí mẫu) ÷ (hoa hồng + chi phí mẫu)",
            "roi_shopee_note": "Giá trị ROI trong file xuất KOL của Shopee, giữ nguyên, "
            "không tính lại; chỉ tính hoa hồng.",
            "sample_cost": "số lượng × (giá vốn + đóng gói) + phí ship; không tính phí book KOL",
            "commission": "tính theo mức hoa hồng áp dụng cho từng sản phẩm bán ra",
            "low_data_threshold": ORDERS_THRESHOLD,
        },
        "data_quality": {
            "untagged_affiliate_lines": model.untagged_lines,
            "lines_without_commission": model.missing_commission_lines,
            "partner_export": model.partner_period,
        },
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
    }


def product_tab(model: KolModel, item_id: str) -> dict[str, Any]:
    """Sản phẩm › Tiếp thị liên kết: the KOLs of one product, with its current rate."""
    body = table(model, item_id=item_id)
    stat = model.pool.products.get(item_id)
    rate = stat.rate if stat else None
    body["product"] = {
        "item_id": item_id,
        "name": stat.name if stat else None,
        "commission_rate": None if rate is None else float(round(rate, 6)),
        "commission_rate_source": None if stat is None else stat.rate_source,
        "affiliate_orders": 0 if stat is None else stat.aff_orders,
    }
    return body


# ----------------------------------------------------------------------------- entry


async def load_model(
    session: AsyncSession,
    shop_id: uuid.UUID,
    ctx: ShopContext,
    view: PeriodView,
) -> KolModel:
    return compute(view, ctx, await load_kol_data(session, shop_id))


async def pair_daily(
    session: AsyncSession,
    shop_id: uuid.UUID,
    kol_key: str,
    item_id: str,
    first: date,
    last: date,
) -> dict[date, dict[str, Any]]:
    """Measurement series of a KOL x product pair: per order day the distinct orders, units and
    GMV of the pair's affiliate-marked lines (confirmed ones). What ``measure`` compares before
    and after the card's send date (``card["kol"]["measurement"]``); days without an order are
    absent, not zero rows."""
    from juli_backend.repositories import ShopeeOrderLinesRepo

    rows = await ShopeeOrderLinesRepo(session).kol_pair_lines(
        shop_id, kol_key, item_id, first, last
    )
    out: dict[date, dict[str, Any]] = {}
    orders: dict[date, set[str]] = defaultdict(set)
    for r in rows:
        if r.paid_at is None:
            continue
        day = r.ordered_at.date()
        cell = out.setdefault(day, {"orders": 0, "units": 0, "gmv": ZERO})
        cell["units"] += r.qty
        cell["gmv"] += r.deal_price * r.qty
        orders[day].add(r.order_ref)
    for day, cell in out.items():
        cell["orders"] = len(orders[day])
    return out
