"""Written allocation rules (doc §6, §7) as pure functions. Not wired to any screen yet.

- :func:`channel_partition` splits **shop GMV** into non-overlapping channels: affiliate first,
  ads capped at gmv − affiliate, organic the remainder (≥ 0). An order both affiliate- and
  ads-attributed counts as affiliate (owner 2026-11-15). The arithmetic is the registry's
  ``channel_gmv_*`` formulas, run by :mod:`.compute`.
- :func:`shop_lines` builds the labelled "Cả shop" lines that close Σ product to the shop:
  ads with no product stay "Quảng cáo chưa gán sản phẩm" (no hidden spread). What the three
  named lines do not explain is carried by a fourth, labelled remainder line (never hidden).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.metrics.components import Components
from juli_backend.services.metrics.compute import raw_value
from juli_backend.services.shopee_profit.money import ZERO

CHANNELS = ("affiliate", "ads", "organic")


def channel_partition(
    gmv: Decimal | None, affiliate_gmv: Decimal | None, ads_gmv: Decimal | None
) -> dict[str, Decimal | None]:
    """``{"affiliate", "ads", "organic"}`` GMV adding up to ``gmv``; ``None`` where unknown."""
    comps: Components = {"gmv": gmv, "affiliate_gmv": affiliate_gmv, "ads_gmv_confirmed": ads_gmv}
    out: dict[str, Decimal | None] = {}
    for ch in CHANNELS:
        value = raw_value(f"channel_gmv_{ch}", comps)
        out[ch] = value if isinstance(value, Decimal) else None
    return out


@dataclass(frozen=True)
class ShopLine:
    key: str
    label_vi: str
    #: effect on profit (no ROI, no margin on these lines)
    profit: Decimal | None
    gmv: Decimal | None = None
    orders: Decimal | None = None


@dataclass(frozen=True)
class ShopLines:
    lines: tuple[ShopLine, ...]
    products_profit: Decimal | None
    shop_profit: Decimal | None
    #: shop profit − (Σ product profit + the three named lines); 0 when the inputs share one
    #: basis. The same amount is the ``rounding_allocation`` line, so the lines add up exactly.
    gap: Decimal | None

    @property
    def residual(self) -> Decimal | None:
        """Shop profit − (Σ product profit + every line); 0 whenever the inputs are known."""
        return _minus(
            self.shop_profit, _total([self.products_profit, *(x.profit for x in self.lines)])
        )


def _total(values: Sequence[Decimal | None]) -> Decimal | None:
    if any(v is None for v in values):
        return None
    return sum((v for v in values if v is not None), ZERO)


def _minus(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a - b


def shop_lines(shop: Components, products: Sequence[Mapping[str, Decimal | None]]) -> ShopLines:
    """The product sheet's last block: lines that add Σ product up to the shop.

    ``shop`` carries ``profit``, ``ads_spend``, ``other_marketing``, ``gmv``, ``orders``;
    each product carries ``profit`` (after its own allocated ads), ``ads_spend``,
    ``line_gmv``, ``line_orders``.
    """
    product_ads = _total([p.get("ads_spend") for p in products])
    unassigned = _minus(shop.get("ads_spend"), product_ads)
    other = shop.get("other_marketing")
    lines = (
        ShopLine(
            "ads_unassigned",
            "Quảng cáo chưa gán sản phẩm",
            None if unassigned is None else -unassigned,
        ),
        ShopLine("other_marketing", "Chi phí marketing khác", None if other is None else -other),
        ShopLine(
            "basis_gap",
            "Chênh lệch cơ sở",
            ZERO,
            gmv=_minus(shop.get("gmv"), _total([p.get("line_gmv") for p in products])),
            orders=_minus(shop.get("orders"), _total([p.get("line_orders") for p in products])),
        ),
    )
    products_profit = _total([p.get("profit") for p in products])
    explained = _total([products_profit, *(line.profit for line in lines)])
    gap = _minus(shop.get("profit"), explained)
    return ShopLines(
        lines=(*lines, ShopLine("rounding_allocation", "Chênh lệch làm tròn / phân bổ", gap)),
        products_profit=products_profit,
        shop_profit=shop.get("profit"),
        gap=gap,
    )
