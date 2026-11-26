"""The capability table (owner #115): which registry metric can be MEASURED on which scope, and
which metric each card kind MOVES. One table, read by Chat (a pairing that does not apply gets one
line and the pairings that do, never another figure) and by the card side (`kinds.WIRING` is
section 8 of this table); the card builder reads it next.

Scopes are what a seller names: the shop, one product, a voucher, Tiếp thị liên kết, a KOL, an ads
campaign, a shop programme, a channel (Organic, Quảng cáo) or one ads line (DVHT Sản phẩm / Shop+,
Livestream, Khác). A scope's row is built from the registry (`levels`) and the readers that hold
the scope's figures; a card kind's row is its target metric, its section-8 wiring and the drivers
its engine family estimates, in the direction the card aims for.

Pure: no I/O. `tests/unit/test_metric_capabilities.py` fails when a registry key or a card kind
has no row, or a row disagrees with the code it is read from.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from juli_backend.services.metrics.registry import METRICS, Level

# ------------------------------------------------------------------ metric groups (registry keys)

SALES = frozenset({"gmv", "orders", "units", "aov"})
TRAFFIC = frozenset({"views", "clicks", "ctr", "ctor"})
#: the ads report's own figures (Quảng cáo, a campaign, an ads line)
ADS = frozenset({"cost_ads", "roas", "roas_direct", "ctr_ads", "ctor_ads"})
#: per product / SKU only (registry levels): stock and the product's own ad cost / sale margin
STOCK = frozenset({"units_per_day", "days_left", "runs_out_on", "restock_units"})
_CHANNEL_PARTS = ("organic", "ads", "affiliate")


def _channel(part: str) -> frozenset[str]:
    """The registry's channel_* metrics of one channel (GMV, share, net revenue, profit, cost %)."""
    return frozenset(k for k in METRICS if k.startswith("channel_") and k.endswith(f"_{part}"))


def _levels(*levels: Level) -> frozenset[str]:
    return frozenset(k for k, m in METRICS.items() if set(m.levels) & set(levels))


KOL = _levels(Level.kol)


# ------------------------------------------------------------------ scopes


@dataclass(frozen=True)
class Scope:
    id: str
    label_vi: str
    measurable: frozenset[str]
    #: False: the scope has no per-product split (a product named with it does not apply)
    per_product: bool = True
    #: the scope this one is a part of, for the short list in a refusal line
    parent: str | None = None
    source: str = ""


def _programme(sid: str, label: str, own_cost: str) -> Scope:
    return Scope(
        sid,
        label,
        SALES | {own_cost, "cost_offers"},
        source="Ưu đãi's part of the programme (offer_combo / offer_promo); its own orders",
    )


_AD_LINE = SALES | TRAFFIC | ADS | {"channel_gmv_ads"}

SCOPES: Mapping[str, Scope] = MappingProxyType(
    {
        s.id: s
        for s in (
            Scope(
                "shop",
                "Shop",
                _levels(Level.shop, Level.channel, Level.kol),
                source="registry levels shop / channel / kol (the shop's own split)",
            ),
            Scope(
                "product",
                "Sản phẩm",
                _levels(Level.product, Level.sku) - _levels(Level.channel, Level.kol),
                source="registry levels product / sku",
            ),
            Scope(
                "voucher",
                "Voucher",
                frozenset({"orders", "gmv", "aov", "cost_offer_voucher"}),
                per_product=False,
                source="entities._voucher_answers (voucher_figures): no source splits by product",
            ),
            Scope(
                "affiliate",
                "Tiếp thị liên kết",
                SALES | TRAFFIC | _channel("affiliate") | KOL | {"cost_affiliate"},
                source="registry channel_*_affiliate + kol, TRAFFIC_SOURCES[lien_ket]",
            ),
            Scope(
                "kol",
                "KOL",
                SALES | KOL | {"cost_affiliate"},
                parent="affiliate",
                source="registry level kol (kol_*)",
            ),
            Scope(
                "campaign",
                "Chiến dịch quảng cáo",
                SALES | TRAFFIC | ADS | {"channel_gmv_ads"},
                parent="ads",
                source="the ads campaign report (campaign_rows)",
            ),
            _programme("combo", "Combo Khuyến Mãi", "cost_offer_combo"),
            _programme("add_on", "Mua Kèm Deal Sốc", "cost_offer_promo"),
            _programme("flash_sale", "Flash Sale Của Shop", "cost_offer_promo"),
            _programme("programme", "Chương Trình Của Shop", "cost_offer_promo"),
            _programme("gift", "Mua Để Nhận Quà", "cost_offer_promo"),
            Scope(
                "organic",
                "Organic",
                SALES | TRAFFIC | _channel("organic"),
                source="registry channel_*_organic, TRAFFIC_SOURCES (no ads)",
            ),
            Scope(
                "ads",
                "Quảng cáo",
                SALES | TRAFFIC | ADS | _channel("ads") | {"roas_break_even", "cost_ads_pct"},
                source="registry channel_*_ads, the ads report, TRAFFIC_SOURCES[ads]",
            ),
            Scope(
                "dvht_product",
                "Dịch vụ hiển thị Sản phẩm",
                _AD_LINE,
                parent="ads",
                source="channel_split ads rows (ad_lines)",
            ),
            Scope(
                "dvht_shop",
                "Dịch vụ hiển thị Shop+",
                _AD_LINE,
                per_product=False,
                parent="ads",
                source="channel_split ads rows: Shop+ is the Shop tab, not split by product",
            ),
            Scope(
                "ads_live",
                "Quảng cáo Livestream",
                _AD_LINE,
                parent="ads",
                source="channel_split ads rows (ad_lines)",
            ),
            Scope(
                "ads_other",
                "Quảng cáo Khác",
                _AD_LINE,
                parent="ads",
                source="channel_split ads rows (ad_lines)",
            ),
        )
    }
)

#: a generic registry key read on one channel as the channel's own metric (GMV Organic ...)
CHANNEL_ALIAS: Mapping[str, str] = MappingProxyType(
    {"gmv": "gmv", "net_revenue": "net_revenue", "profit": "profit", "cost_total_pct": "cost_pct"}
)


def measurable(scope: str, metric: str) -> bool:
    """Can `metric` (a registry key) be measured on `scope`? A generic key on a channel counts
    when the channel has its own variant (`profit` on Organic = `channel_profit_organic`)."""
    s = SCOPES[scope]
    if metric in s.measurable:
        return True
    part = {"organic": "organic", "ads": "ads", "affiliate": "affiliate"}.get(scope)
    alias = CHANNEL_ALIAS.get(metric)
    return bool(part and alias and f"channel_{alias}_{part}" in s.measurable)


def scopes_for(metric: str) -> tuple[str, ...]:
    """Every scope `metric` can be measured on, in table order."""
    return tuple(s for s in SCOPES if measurable(s, metric))


def short_scopes(metric: str) -> tuple[str, ...]:
    """`scopes_for`, a part dropped when its parent is listed (Quảng cáo stands for its lines)."""
    have = scopes_for(metric)
    return tuple(s for s in have if SCOPES[s].parent not in have)


# ------------------------------------------------------------------ card kinds

#: a driver of the funnel and the outcomes it carries (GMV = views x CTR x CTOR x AOV)
FUNNEL: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "views": ("views", "clicks", "orders", "units", "gmv"),
        "ctr": ("ctr", "clicks", "orders", "units", "gmv"),
        "ctor": ("ctor", "orders", "units", "gmv"),
        "aov": ("aov", "gmv"),
        "orders": ("orders", "units", "gmv"),
    }
)

#: card kind -> the metrics it moves (its target metric, section 8, its engine family's drivers;
#: in the direction the card aims for: a discount's lower AOV is not "moving AOV"). The order of
#: rows is the order the generators try kinds for a metric (section 8 below keeps it).
MOVES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        # listing (engine_families.families._SIMPLE)
        "cover_image": ("ctr",),
        "title": ("views", "ctr"),
        "keyword": ("views",),
        "price_display": ("ctr",),
        "description_first_line": ("ctor",),
        "listing_relist": ("views",),
        "listing_hide": (),  # removal: takes the listing's views away
        "variation_restructure": (),  # a re-arrangement, no lift
        # ads (ads_edit / ads_option: views on Thẻ sản phẩm; the ads report's spend / ROAS)
        "ads_budget": ("views", "channel_gmv_ads", "cost_ads"),
        "ads_keywords": ("views", "channel_gmv_ads", "cost_ads"),
        "ads_new_campaign": ("views", "channel_gmv_ads", "cost_ads"),
        "ads_add_product": ("views", "channel_gmv_ads", "cost_ads"),
        "ads_remove_product": ("roas", "cost_ads"),
        # affiliate (affiliate_option / affiliate_rate_option: views on Liên kết)
        "affiliate_commission": ("views", "channel_gmv_affiliate", "cost_affiliate"),
        "affiliate_target_campaign": ("views", "channel_gmv_affiliate"),
        "affiliate_sample": ("views", "channel_gmv_affiliate", "orders"),
        "affiliate_invite": ("views", "channel_gmv_affiliate", "orders"),
        # basket (combo_option, voucher_option, _SIMPLE)
        "bundle_deal": ("aov", "ctor"),
        "combo_multi": ("aov", "ctor"),
        "listing_combo": ("aov", "views"),
        "add_on": ("aov",),
        "gift": ("ctor",),
        "product_discount": ("ctor",),
        "min_spend_voucher": ("aov", "ctor"),
        "review_voucher": ("ctor",),
        "variation_set": ("aov", "ctor"),
        # price and margin (price_option: CTOR and the price's own AOV; section 8 Biên)
        "price": ("ctor", "aov", "margin", "profit"),
        "voucher_cap": ("margin", "profit", "cost_offer_voucher"),
        "ads_roas_target": ("roas", "margin", "profit", "cost_ads"),
        "ads_pause": ("roas", "margin", "profit", "cost_ads"),
        "ads_purpose": ("roas",),
        # sale calendar (price_option for a flash slot; the programme's target is orders)
        "flash_sale": ("ctor", "orders"),
        "program_registration": ("orders",),
        "mega_sale": ("orders",),
    }
)

#: owner #93 / F5: these move their metrics but carry no measured uplift until measured
NOT_MEASURED: frozenset[str] = frozenset({"title", "cover_image"})


def moves_all(kind: str) -> frozenset[str]:
    """Every metric `kind` moves: its own metrics and the funnel outcomes they carry."""
    out: set[str] = set()
    for m in MOVES[kind]:
        out.update(FUNNEL.get(m, (m,)))
    return frozenset(out)


def moves(kind: str, metric: str) -> bool:
    return metric in moves_all(kind)


def kinds_moving(metric: str, among: Iterable[str] | None = None) -> tuple[str, ...]:
    """The card kinds that move `metric`, in table order (optionally only those in `among`)."""
    pool = set(among) if among is not None else None
    return tuple(k for k in MOVES if moves(k, metric) and (pool is None or k in pool))


# ------------------------------------------------------------------ section 8 (kinds.WIRING)

#: section 8's critical metric key -> the registry metric it is
CRITICAL_METRIC: Mapping[str, str] = MappingProxyType(
    {
        "views": "views",
        "ctr": "ctr",
        "ctor": "ctor",
        "aov": "aov",
        "bien": "margin",
        "roas": "roas",
        "lien_ket": "channel_gmv_affiliate",
        "sale": "orders",
    }
)


def _section8(rows: dict[str, tuple[str, ...]]) -> Mapping[str, tuple[str, ...]]:
    """Contract section 8: the kinds a critical metric is answered with, in the generators'
    order. Each must move the metric in `MOVES` (checked here, at import)."""
    for crit, kinds in rows.items():
        bad = [k for k in kinds if not moves(k, CRITICAL_METRIC[crit])]
        if bad:
            raise ValueError(f"section 8 {crit}: {bad} do not move {CRITICAL_METRIC[crit]}")
    return MappingProxyType(rows)


SECTION8: Mapping[str, tuple[str, ...]] = _section8(
    {
        "views": ("title", "keyword", "ads_budget", "affiliate_commission"),
        "ctr": ("cover_image", "title", "price_display"),
        "ctor": ("product_discount", "min_spend_voucher", "review_voucher", "price"),
        "aov": ("bundle_deal", "add_on", "min_spend_voucher", "variation_set"),
        "bien": ("price", "voucher_cap", "ads_roas_target", "ads_pause"),
        "roas": ("ads_roas_target", "ads_pause", "ads_purpose"),
        "lien_ket": ("affiliate_commission", "affiliate_target_campaign"),
        # not in section 8 (no critical metric of their own): the sale / combo families reach the
        # shop through the same CTOR / AOV metrics plus the explicit sale calendar
        "sale": ("flash_sale", "program_registration"),
    }
)


# ------------------------------------------------------------------ the one line (Chat)


def metric_label(metric: str) -> str:
    return METRICS[metric].label_vi if metric in METRICS else metric


def _lower(label: str) -> str:
    """'Lượt xem' -> 'lượt xem'; an acronym ('CTR', 'AOV', 'ROAS') stays."""
    return label[:1].lower() + label[1:] if label[1:2].islower() else label


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " và " + parts[-1]


def scope_line(scope: str, metric: str, *, per_product: bool = False) -> str:
    """'Organic không có ROAS. ROAS chỉ có cho Shop, Sản phẩm, Quảng cáo.'"""
    s, m = SCOPES[scope].label_vi, metric_label(metric)
    if per_product and not SCOPES[scope].per_product:
        return f"{s} không tính theo từng sản phẩm."
    where = [SCOPES[x].label_vi for x in short_scopes(metric)]
    return f"{s} không có {m}." + (f" {m} chỉ có cho {', '.join(where)}." if where else "")


def kind_line(kind: str, kind_label: str, metric: str) -> str:
    """'Tên sản phẩm tác động lượt xem và CTR, không tác động AOV.'"""
    own = [_lower(metric_label(m)) for m in MOVES[kind]]
    m = metric_label(metric)
    if not own:
        return f"{kind_label} không tác động {m}."
    return f"{kind_label} tác động {_and(own)}, không tác động {m}."


__all__ = [
    "CHANNEL_ALIAS",
    "CRITICAL_METRIC",
    "FUNNEL",
    "MOVES",
    "NOT_MEASURED",
    "SCOPES",
    "SECTION8",
    "Scope",
    "kind_line",
    "kinds_moving",
    "measurable",
    "metric_label",
    "moves",
    "moves_all",
    "scope_line",
    "scopes_for",
    "short_scopes",
]
