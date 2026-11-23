"""W3-Q5: profit needs ads. A platform whose ads spend is not known (``source_reason(ads)`` is set,
TikTok until the Business API scope) shows no profit, margin, contribution, break-even ROAS, ROI
or ad cost: each is ``None`` with the registry reason, never 0 and never a before-ads profit.

One table per payload kind lists the exact paths and field names (``[]`` = every item of a list,
``*`` = every value of a dict). Nothing is found by walking key names, so an unrelated field that
shares a name (a product called "margin") is never touched. A Shopee shop has ads: nothing changes.
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.metrics.registry import Platform, source_reason

Spec = tuple[tuple[str, tuple[str, ...]], ...]

_BRIDGE = (
    "product_profit",
    "ads_unattributed",
    "ads_no_order_days",
    "other_marketing",
    "profit",
    "ads_charged",
    "ads_total",
)
_SHOP_PROFIT: Spec = (
    ("", ("profit", "margin_pct", "ads_charged")),
    ("bridge", _BRIDGE),
)
_ADS = (
    "spend",
    "spend_per_day",
    "gmv_placed",
    "direct_gmv_placed",
    "orders_placed",
    "roas",
    "roas_broad",
    "roas_direct",
    "break_even_roas",
    "below_break_even",
)
_PRODUCT_PROFIT = ("profit", "margin_pct", "contribution", "ad_spend", "break_even_roas")
_LEVER = ("contribution", "profit", "margin_pct")
_FIVE: Spec = (
    ("five_numbers.margin", ("profit_before", "profit_after", "pct_before", "pct_after")),
    (
        "five_numbers.extra_revenue_per_extra_spend",
        ("extra_revenue", "extra_spend", "per_vnd", "pct"),
    ),
    ("five_numbers.spend_cap", ("spend_per_day", "remaining", "used_pct", "over_cap")),
)
_PRODUCT_ROW: Spec = (
    ("profit", _PRODUCT_PROFIT),
    ("levers[]", _LEVER),
    ("ads", _ADS),
    *_FIVE,
)


def _under(prefix: str, spec: Spec) -> Spec:
    return tuple((f"{prefix}.{p}" if p else prefix, names) for p, names in spec)


SPECS: dict[str, Spec] = {
    "overview": (
        ("shop_metrics", ("ad_spend", "ads_roas_placed", "profit", "margin_pct")),
        *_under("shop_metrics.shop_profit", _SHOP_PROFIT),
        *_under("shop_profit", _SHOP_PROFIT),
        ("levers.rows[]", _LEVER),
        ("ads", _ADS),
        *_FIVE,
        (
            "profit",
            (
                "profit_vnd",
                "profit_on_covered_vnd",
                "contribution_before_ads",
                "margin_pct",
                "break_even_roas",
                "other_marketing_costs",
                "known_cost_gmv_share_pct",
            ),
        ),
        ("profit.bridge", _BRIDGE),
    ),
    "matrix": (
        *_under("products[]", _PRODUCT_ROW),
        *_under("shop_profit", _SHOP_PROFIT),
    ),
    "critical": (("items[]", ("margin_pct",)), ("in_band[]", ("margin_pct",))),
    "ranking": (
        ("up[]", ("spend", "margin_pct")),
        ("down[]", ("spend", "margin_pct")),
        ("views.up.rows[]", ("spend", "margin_pct")),
        ("views.down.rows[]", ("spend", "margin_pct")),
    ),
    "product": (
        *_under("kpi_by_period.*", (("profit", _PRODUCT_PROFIT), *_FIVE)),
        *_under("nguon", _PRODUCT_ROW),
        ("ads", _ADS),
        ("ads.campaigns[]", _ADS),
        (
            "cost_and_floor.skus[]",
            ("price_margin_pct", "final_margin_pct"),
        ),
        ("cost_and_floor.skus[].final_margin_rates", ("ads_pct",)),
        (
            "cost_and_floor.skus[].waterfall_per_unit",
            ("contribution_before_ads", "profit", "margin_pct"),
        ),
    ),
    "channel_split": (
        ("kpis", ("profit", "cost_total", "cost_ads", "roi")),
        ("kpis_prev", ("profit", "cost_total", "cost_ads", "roi")),
    ),
    "channel_split_products": (("products[]", ("margin",)),),
    "kols": (
        ("totals", ("net_profit", "profit_after_samples", "roi_incl_samples")),
        ("rows[]", ("net_profit", "profit_after_samples", "roi_incl_samples", "roi")),
    ),
    "kols_compare": (
        ("total", ("net_profit", "profit_after_samples", "profit_per_order", "roi_incl_samples")),
        ("rows[]", ("net_profit", "profit_after_samples", "profit_per_order", "roi_incl_samples")),
        ("streams.rows[]", ("profit_after_cost",)),
    ),
    "product_kols": (
        ("totals", ("net_profit", "profit_after_samples", "roi_incl_samples")),
        ("rows[]", ("net_profit", "profit_after_samples", "roi_incl_samples", "roi")),
    ),
    "kol_section": (("rows[]", ("net_profit", "profit_after_samples", "roi_incl_samples")),),
    "metric_view": (),
}
#: rankings whose measure is a profit figure: refused, not shown as None rows
PROFIT_RANKINGS = frozenset({"profit_per_day", "bien", "giam_gia", "thu_them"})
_METRIC_CELLS = ("now", "prev", "change", "impact")


def ads_unknown(platform: str) -> str | None:
    """The registry reason code when ``platform`` has no ads spend, else ``None``."""
    return source_reason(Platform(platform), "ads")


def _walk(node: Any, segs: list[str], names: tuple[str, ...]) -> None:
    if node is None:
        return
    if not segs:
        if isinstance(node, dict):
            for name in names:
                if name in node:
                    node[name] = None
        return
    seg, rest = segs[0], segs[1:]
    if seg == "*":
        for value in list(node.values()) if isinstance(node, dict) else []:
            _walk(value, rest, names)
        return
    many = seg.endswith("[]")
    key = seg[:-2] if many else seg
    child = node.get(key) if isinstance(node, dict) and key else node
    if many:
        for item in child if isinstance(child, list) else []:
            _walk(item, rest, names)
    else:
        _walk(child, rest, names)


def apply(body: dict[str, Any], kind: str, platform: str) -> dict[str, Any]:
    """``body`` with the profit-needs-ads fields set to ``None`` and ``unavailable`` naming why;
    a platform with ads (Shopee) gets ``body`` back untouched."""
    reason = ads_unknown(platform)
    if reason is None:
        return body
    for path, names in SPECS[kind]:
        _walk(body, [s for s in path.split(".") if s], names)
    if kind == "metric_view" and body.get("metric") == "margin":
        for block in [body.get("total"), *body.get("channels", []), *body.get("products", [])]:
            if isinstance(block, dict):
                for key in _METRIC_CELLS:
                    if key in block:
                        block[key] = None
    body["unavailable"] = {
        **body.get("unavailable", {}),
        "ads": reason,
        "profit": reason,
        "margin": reason,
    }
    return body
