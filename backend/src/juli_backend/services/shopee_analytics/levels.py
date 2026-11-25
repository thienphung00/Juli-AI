"""Which rung of the profit ladder each surface shows (owner #42 / #65 / #66 / #67, L1).

Tổng quan and Kế hoạch show Ròng (``profit`` / ``margin``; the export adds Gộp and Đóng góp).
Every product-level surface stops at Đóng góp: before ads AND affiliate, the shop discount (Ưu
đãi) already inside doanh thu thực, every margin ÷ the covered doanh thu thực
(``net_revenue_known``, L3). Chat follows the tab it answers about (Track CHAT).

The map is data (``SURFACE_METRICS``); the product-level figures come from the registry ladder
on the product's covered order lines (:func:`product_contribution`) until the stored facts
(``metrics.query``) replace the view, never from ``ProductProfit.margin_pct`` / ``.profit``
(after ads) or ``.contribution`` (after AFF).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.ladder import ladder_of
from juli_backend.services.shopee_profit.money import pct_points

#: L1: surface -> the registry metric ids it shows for profit and margin
SURFACE_METRICS: Mapping[str, tuple[str, ...]] = {
    # net allowed (ads and AFF deducted)
    "tong_quan.kpi": ("profit", "margin"),
    "tong_quan.channel_table": ("profit", "margin"),
    "ke_hoach": ("profit", "margin"),
    "export.tong_quan": (
        "gross_profit",
        "margin_gross",
        "contribution",
        "margin_contribution",
        "profit",
        "margin",
    ),
    # product level: Đóng góp (before ads and AFF), with / without a shop discount
    "tong_quan.product_list": ("contribution", "margin_contribution"),
    "phan_tich.metric_view": ("contribution", "margin_contribution"),
    "phan_tich.rankings": ("contribution", "margin_contribution"),
    "phan_tich.product_page": ("contribution", "margin_contribution"),
    "phan_tich.matrix": ("contribution", "margin_contribution"),
    "phan_tich.critical": ("contribution", "margin_contribution"),
    "quyet_dinh.picker": ("contribution", "margin_contribution"),
}
PRODUCT_LEVEL = frozenset(k for k, v in SURFACE_METRICS.items() if v[0] == "contribution")
#: the metric ids a product-level surface may never show (they deduct ads / AFF)
NET_ONLY = frozenset({"profit", "margin", "roi"})


@dataclass(frozen=True)
class ProductContribution:
    """Lợi nhuận đóng góp and Biên đóng góp (percentage points) of a scope's covered lines."""

    contribution: Decimal | None
    margin_pct: Decimal | None
    #: doanh thu thực of the covered lines (the base)
    net_revenue_known: Decimal | None


def contribution_of(pairs: Iterable[tuple[Any, Any]]) -> ProductContribution:
    """The registry ladder's Đóng góp of ``pairs`` (order line, breakdown). ``None`` when no line
    has every cost known (missing is never 0)."""
    lines = list(pairs)
    ladder = ladder_of(lines, ads_spend=None, other_marketing=None)
    base = ladder.components.get("net_revenue_known")
    if not base:
        return ProductContribution(None, None, None)
    margin = ladder.get("margin_contribution")
    return ProductContribution(
        ladder.get("contribution"),
        None if margin is None else pct_points(margin),
        base,
    )


def product_contribution(view: Any, item_ids: Iterable[str]) -> ProductContribution:
    """Đóng góp of the products ``item_ids`` over the view's window."""
    items = {str(i) for i in item_ids}
    pairs = getattr(view, "pairs", ())
    return contribution_of((ln, pb) for ln, pb in pairs if str(ln.product_id) in items)


def contribution_by_item(view: Any) -> dict[str, ProductContribution]:
    """item -> its Đóng góp, for every product with order lines in the view."""
    by: dict[str, list[tuple[Any, Any]]] = {}
    for ln, pb in getattr(view, "pairs", ()):
        by.setdefault(str(ln.product_id), []).append((ln, pb))
    return {item: contribution_of(pairs) for item, pairs in by.items()}


__all__ = [
    "NET_ONLY",
    "PRODUCT_LEVEL",
    "SURFACE_METRICS",
    "ProductContribution",
    "contribution_by_item",
    "contribution_of",
    "product_contribution",
]
