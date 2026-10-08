"""Per-product funnel windows and the shop medians they are compared against.

ADR-106 decision 1: the identity is ``GMV = Impressions × CTR × CTOR × AOV``
in TikTok's own field names. A :class:`FunnelWindow` holds the four raw
counts summed over a window and derives the three ratios; nothing here
knows where the counts came from (A-34 ``total_performance``, an A-33
``PRODUCT_CARD`` breakdown, or a test fixture).

A :class:`ProductFunnel` pairs the current window with the prior one for the
own-trend gap, and :class:`ShopMedians` is the per-factor median over the
products that clear the volume floor — the comparison set for the
shop-median gap.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import median

from juli_backend.services.optimize_product.config import StageDiagnosisConfig

ZERO = Decimal("0")


def to_decimal(value: object) -> Decimal:
    """Coerce an API string/number into a Decimal; ``None`` and junk read as 0."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


@dataclass(frozen=True)
class FunnelWindow:
    """Raw funnel counts over ``days`` days for one product and one channel scope."""

    days: int
    impressions: Decimal = ZERO
    clicks: Decimal = ZERO
    sku_orders: Decimal = ZERO
    items_sold: Decimal = ZERO
    gmv: Decimal = ZERO

    @property
    def ctr(self) -> Decimal | None:
        return None if self.impressions <= 0 else self.clicks / self.impressions

    @property
    def ctor(self) -> Decimal | None:
        return None if self.clicks <= 0 else self.sku_orders / self.clicks

    @property
    def aov(self) -> Decimal | None:
        return None if self.sku_orders <= 0 else self.gmv / self.sku_orders

    @property
    def items_per_order(self) -> Decimal | None:
        return None if self.sku_orders <= 0 else self.items_sold / self.sku_orders

    def per_day(self, value: Decimal) -> Decimal:
        return ZERO if self.days <= 0 else value / Decimal(self.days)

    @classmethod
    def from_a34_total_performance(cls, total: dict, *, days: int) -> FunnelWindow:
        """Build from one A-34 ``total_performance`` block.

        A-34 carries ``ctr`` and ``click_order_rate`` as ratios and, in the
        public doc, ``product_impressions`` / ``product_clicks`` as counts.
        When the counts are absent (the sandbox capture omits them) they are
        reconstructed from the ratios: ``clicks = sku_orders ÷ click_order_rate``,
        ``impressions = clicks ÷ ctr``. Reconstructed counts are exact for
        the ratios they came from and good enough for a floor check.
        """
        gmv = to_decimal((total.get("gmv") or {}).get("amount"))
        sku_orders = to_decimal(total.get("sku_orders"))
        items_sold = to_decimal(total.get("items_sold"))
        clicks = to_decimal(total.get("product_clicks"))
        impressions = to_decimal(total.get("product_impressions"))
        ctor = to_decimal(total.get("click_order_rate"))
        ctr = to_decimal(total.get("ctr"))
        if clicks <= 0 and ctor > 0:
            clicks = sku_orders / ctor
        if impressions <= 0 and ctr > 0 and clicks > 0:
            impressions = clicks / ctr
        return cls(
            days=days,
            impressions=impressions,
            clicks=clicks,
            sku_orders=sku_orders,
            items_sold=items_sold,
            gmv=gmv,
        )

    @classmethod
    def from_a34_product_card(cls, item: dict, *, days: int) -> FunnelWindow | None:
        """The PRODUCT_CARD-scoped window from one A-34 product row.

        The live 202605 response carries per-channel blocks beside
        ``total_performance``. TikTok's "Thẻ sản phẩm" is every non-LIVE,
        non-video surface, which A-34 splits into
        ``seller_product_card_performance`` (search, recommendation, shop
        page) and ``shop_tab_performance`` (the Shop Tab). Both are summed
        here. Each block carries its own impressions, clicks and ratios at
        four decimals, so the funnel is exact for that channel — unlike the
        A-33 breakdown, which gives per-channel traffic but all-channel
        orders. Returns ``None`` when neither block is present.
        """
        card = item.get("seller_product_card_performance")
        tab = item.get("shop_tab_performance")
        if not isinstance(card, dict) and not isinstance(tab, dict):
            return None
        card = card if isinstance(card, dict) else {}
        tab = tab if isinstance(tab, dict) else {}
        tab_clicks = to_decimal(tab.get("shop_tab_product_clicks"))
        tab_orders = tab_clicks * to_decimal(tab.get("shop_tab_ctor_sku"))
        return cls(
            days=days,
            impressions=to_decimal(card.get("product_impressions"))
            + to_decimal(tab.get("shop_tab_product_impressions")),
            clicks=to_decimal(card.get("product_clicks")) + tab_clicks,
            sku_orders=to_decimal(card.get("attributed_sku_orders")) + tab_orders,
            items_sold=to_decimal(card.get("attributed_sold_items"))
            + to_decimal(tab.get("shop_tab_sold_items")),
            gmv=to_decimal(
                (card.get("attributed_gmv") or {}).get("amount")
                if isinstance(card.get("attributed_gmv"), dict)
                else card.get("attributed_gmv")
            )
            + to_decimal(
                (tab.get("shop_tab_gmv") or {}).get("amount")
                if isinstance(tab.get("shop_tab_gmv"), dict)
                else tab.get("shop_tab_gmv")
            ),
        )


@dataclass(frozen=True)
class ProductFunnel:
    """One product's funnel: the current window, the prior window, the 28-day GMV."""

    product_id: str
    title: str
    current: FunnelWindow
    prior: FunnelWindow | None = None
    gmv_28d: Decimal = ZERO
    age_days: int | None = None
    #: Which series ``current`` came from — ``"PRODUCT_CARD"`` when the A-34
    #: channel blocks were present, ``"ALL_CHANNELS"`` when only
    #: ``total_performance`` was. Listing angles are
    #: trusted on the former; the latter is reported as a caveat.
    channel_scope: str = "ALL_CHANNELS"

    def clears_floor(self, config: StageDiagnosisConfig) -> dict[str, bool]:
        """Which factors clear the ADR-077 volume floors over the current window."""
        w = self.current
        return {
            "ctr": w.per_day(w.impressions) >= config.min_impressions_per_day,
            "ctor": w.per_day(w.clicks) >= config.min_clicks_per_day,
            "aov": w.per_day(w.sku_orders) >= config.min_orders_per_day,
        }


@dataclass(frozen=True)
class ShopMedians:
    """Per-factor median over products above the floor; ``None`` when too few peers."""

    ctr: Decimal | None
    ctor: Decimal | None
    aov: Decimal | None
    peers: dict[str, int]

    @classmethod
    def from_products(
        cls, products: Iterable[ProductFunnel], config: StageDiagnosisConfig
    ) -> ShopMedians:
        values: dict[str, list[Decimal]] = {"ctr": [], "ctor": [], "aov": []}
        for product in products:
            floors = product.clears_floor(config)
            window = product.current
            for factor, value in (("ctr", window.ctr), ("ctor", window.ctor), ("aov", window.aov)):
                if floors[factor] and value is not None:
                    values[factor].append(value)

        def _median(factor: str) -> Decimal | None:
            series = values[factor]
            if len(series) < config.min_peers_for_median:
                return None
            return Decimal(str(median(series)))

        return cls(
            ctr=_median("ctr"),
            ctor=_median("ctor"),
            aov=_median("aov"),
            peers={factor: len(series) for factor, series in values.items()},
        )
