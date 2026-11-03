"""Traffic flows from AGGREGATES (contract section 2): five additive flows + a residual row.

Order lines carry no traffic source, so flows never come from them. The input is one row per
product x Shopee source (item x source export / connector): views, clicks, orders, GMV.

Shopee's own "The san pham" total includes its child "Cua hang" (Trang shop), so the rows use
:class:`FlowSource` and :func:`build_flow_tables` splits them::

    the_san_pham = THE_SAN_PHAM_TOTAL - TRANG_SHOP        (views, clicks, orders, GMV)
    trang_shop   = TRANG_SHOP
    live, video, lien_ket                                  (L1 sources as reported)

Rules:
- The five flows add up to the shop GMV. If they do not (Shopee de-duplicates buyers across
  sources), a sixth row ``chenh_lech_nguon`` carries the difference (GMV and orders; no views,
  clicks or ratios) -- never silently scaled. A child larger than its parent raises
  :class:`FlowError`.
- Per flow: CTR = clicks / views, CTOR = orders / clicks, AOV = GMV / orders, and
  GMV = views x CTR x CTOR x AOV exactly (:meth:`FlowMetrics.gmv_by_identity` uses exact
  fractions). A ratio is ``None`` when its denominator is 0 or a count is unknown. CTR is
  never compared across flows with different view definitions (Live / Video count sessions /
  videos): no function here ranks flows by CTR.
- Ads are an overlay ("trong do"): ``ads`` on a row is spend and ad-attributed GMV landing in
  that flow, never a row of the sum.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from juli_backend.services.shopee_profit.money import ZERO, safe_div


class FlowError(ValueError):
    pass


class FlowSource(StrEnum):
    """Source keys as exported (before the Trang shop split)."""

    THE_SAN_PHAM_TOTAL = "the_san_pham_total"  # Shopee "The san pham", includes Trang shop
    TRANG_SHOP = "trang_shop"  # child "Cua hang"
    LIVE = "live"
    VIDEO = "video"
    LIEN_KET = "lien_ket"  # incl. Affiliate Live / Video


class Flow(StrEnum):
    THE_SAN_PHAM = "the_san_pham"  # outside Trang shop
    TRANG_SHOP = "trang_shop"
    LIVE = "live"
    VIDEO = "video"
    LIEN_KET = "lien_ket"


RESIDUAL_KEY = "chenh_lech_nguon"
FLOW_ORDER: tuple[Flow, ...] = tuple(Flow)
FLOW_LABELS: dict[str, str] = {
    Flow.THE_SAN_PHAM: "Thẻ sản phẩm (ngoài Trang shop)",
    Flow.TRANG_SHOP: "Trang shop",
    Flow.LIVE: "Live",
    Flow.VIDEO: "Video",
    Flow.LIEN_KET: "Tiếp thị liên kết (Affiliate)",
    RESIDUAL_KEY: "Chênh lệch nguồn",
}


@dataclass(frozen=True)
class FlowRow:
    """One product x source aggregate. ``views`` / ``clicks`` None = the source has none."""

    product_id: str
    source: FlowSource
    orders: int
    gmv: Decimal
    views: int | None = None
    clicks: int | None = None


@dataclass(frozen=True)
class FlowAdsRow:
    """Ad spend and ad-attributed GMV landing in a flow (overlay input)."""

    product_id: str
    flow: Flow
    spend: Decimal
    gmv: Decimal = ZERO
    orders: int = 0


@dataclass(frozen=True)
class FlowAds:
    spend: Decimal
    gmv: Decimal
    orders: int

    @property
    def roas(self) -> Decimal | None:
        return safe_div(self.gmv, self.spend)


@dataclass(frozen=True)
class FlowMetrics:
    key: str  # Flow value or RESIDUAL_KEY
    label: str
    views: int | None
    clicks: int | None
    orders: int
    gmv: Decimal
    ads: FlowAds | None = None  # overlay, "trong do"

    @property
    def is_residual(self) -> bool:
        return self.key == RESIDUAL_KEY

    @property
    def ctr(self) -> Decimal | None:
        if self.views is None or self.clicks is None:
            return None
        return safe_div(Decimal(self.clicks), Decimal(self.views))

    @property
    def ctor(self) -> Decimal | None:
        if self.clicks is None:
            return None
        return safe_div(Decimal(self.orders), Decimal(self.clicks))

    @property
    def aov(self) -> Decimal | None:
        return safe_div(self.gmv, Decimal(self.orders))

    def gmv_by_identity(self) -> Decimal | None:
        """views x CTR x CTOR x AOV computed with exact fractions (== ``gmv`` when defined)."""
        if self.views is None or self.clicks is None or self.views == 0:
            return None
        if self.clicks == 0 or self.orders == 0:
            return None
        ctr = Fraction(self.clicks, self.views)
        ctor = Fraction(self.orders, self.clicks)
        aov = Fraction(self.gmv) / self.orders
        exact = self.views * ctr * ctor * aov
        return Decimal(exact.numerator) / Decimal(exact.denominator)


@dataclass(frozen=True)
class FlowTable:
    """Rows in contract order (five flows, then the residual row only if it is non-zero)."""

    rows: tuple[FlowMetrics, ...]
    total_gmv: Decimal | None  # the shop / product GMV the rows add up to
    total_orders: int | None

    def row(self, key: str) -> FlowMetrics | None:
        return next((r for r in self.rows if r.key == key), None)

    @property
    def gmv_sum(self) -> Decimal:
        return sum((r.gmv for r in self.rows), ZERO)

    @property
    def orders_sum(self) -> int:
        return sum(r.orders for r in self.rows)

    @property
    def residual(self) -> FlowMetrics | None:
        return self.row(RESIDUAL_KEY)


@dataclass(frozen=True)
class FlowTables:
    shop: FlowTable
    products: dict[str, FlowTable]


@dataclass
class _Acc:
    views: int | None = None
    clicks: int | None = None
    orders: int = 0
    gmv: Decimal = ZERO

    def add(self, views: int | None, clicks: int | None, orders: int, gmv: Decimal) -> None:
        self.views = _plus(self.views, views)
        self.clicks = _plus(self.clicks, clicks)
        self.orders += orders
        self.gmv += gmv


def _plus(a: int | None, b: int | None) -> int | None:
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


def _minus(a: int | None, b: int | None) -> int | None:
    if a is None:
        return None
    return a - (b or 0)


def _split_product(rows: Iterable[FlowRow]) -> dict[Flow, _Acc]:
    """One product's rows -> five flows (Thẻ sản phẩm minus its Trang shop child)."""
    src: dict[FlowSource, _Acc] = defaultdict(_Acc)
    for r in rows:
        src[r.source].add(r.views, r.clicks, r.orders, r.gmv)
    total, child = src[FlowSource.THE_SAN_PHAM_TOTAL], src[FlowSource.TRANG_SHOP]
    if (
        child.gmv > total.gmv
        or child.orders > total.orders
        or (child.views or 0) > (total.views or 0)
        or (child.clicks or 0) > (total.clicks or 0)
    ):
        raise FlowError("Trang shop (child) exceeds Thẻ sản phẩm (total)")
    return {
        Flow.THE_SAN_PHAM: _Acc(
            _minus(total.views, child.views),
            _minus(total.clicks, child.clicks),
            total.orders - child.orders,
            total.gmv - child.gmv,
        ),
        Flow.TRANG_SHOP: child,
        Flow.LIVE: src[FlowSource.LIVE],
        Flow.VIDEO: src[FlowSource.VIDEO],
        Flow.LIEN_KET: src[FlowSource.LIEN_KET],
    }


def _table(
    per_flow: Mapping[Flow, _Acc],
    total_gmv: Decimal | None,
    total_orders: int | None,
    ads: Mapping[Flow, FlowAds],
) -> FlowTable:
    rows = [
        FlowMetrics(
            key=f.value,
            label=FLOW_LABELS[f],
            views=per_flow[f].views,
            clicks=per_flow[f].clicks,
            orders=per_flow[f].orders,
            gmv=per_flow[f].gmv,
            ads=ads.get(f),
        )
        for f in FLOW_ORDER
    ]
    gmv_gap = (total_gmv - sum((r.gmv for r in rows), ZERO)) if total_gmv is not None else ZERO
    order_gap = (total_orders - sum(r.orders for r in rows)) if total_orders is not None else 0
    if gmv_gap != 0 or order_gap != 0:
        rows.append(
            FlowMetrics(RESIDUAL_KEY, FLOW_LABELS[RESIDUAL_KEY], None, None, order_gap, gmv_gap)
        )
    return FlowTable(tuple(rows), total_gmv, total_orders)


def _ads_by_flow(rows: Iterable[FlowAdsRow]) -> dict[Flow, FlowAds]:
    acc: dict[Flow, FlowAds] = {}
    for a in rows:
        prev = acc.get(a.flow, FlowAds(ZERO, ZERO, 0))
        acc[a.flow] = FlowAds(prev.spend + a.spend, prev.gmv + a.gmv, prev.orders + a.orders)
    return acc


def build_flow_tables(
    rows: Iterable[FlowRow],
    *,
    shop_gmv: Decimal,
    shop_orders: int | None = None,
    product_totals: Mapping[str, tuple[Decimal, int]] | None = None,
    ads: Iterable[FlowAdsRow] = (),
) -> FlowTables:
    """Shop table (all products summed) and one table per product.

    ``shop_gmv`` / ``shop_orders`` are the shop's Doanh so / confirmed orders; any gap to the
    five flows becomes the ``chenh_lech_nguon`` row. ``product_totals`` (product -> (GMV,
    orders)) does the same per product; without it a product table is just its five flows.
    """
    by_product: dict[str, list[FlowRow]] = defaultdict(list)
    for r in rows:
        by_product[r.product_id].append(r)
    ads_list = list(ads)

    shop_acc: dict[Flow, _Acc] = {f: _Acc() for f in FLOW_ORDER}
    products: dict[str, FlowTable] = {}
    for pid, prows in by_product.items():
        split = _split_product(prows)
        for f, a in split.items():
            shop_acc[f].add(a.views, a.clicks, a.orders, a.gmv)
        totals = (product_totals or {}).get(pid)
        products[pid] = _table(
            split,
            totals[0] if totals else None,
            totals[1] if totals else None,
            _ads_by_flow(a for a in ads_list if a.product_id == pid),
        )
    shop = _table(shop_acc, shop_gmv, shop_orders, _ads_by_flow(ads_list))
    return FlowTables(shop, products)
