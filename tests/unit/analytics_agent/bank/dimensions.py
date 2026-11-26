"""The generated bank's dimensions, enumerated FROM THE CODE: every value names the constant it
comes from, so a new metric key, window, entity word, card kind, template, advisor tool or
lever widens the product by itself (`test_dimensions_follow_the_code` pins the link).

As of the seeded shop's last complete day, 2026-10-07 (a Wednesday). The dates below are the
oracle's own reading of each window's description (`routing.WINDOWS`), written out, not
computed by `windows.build_windows` (the code under test)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.analytics_agent import levers, routing
from juli_backend.services.analytics_agent.advisor import _tool_specs
from juli_backend.services.analytics_agent.chains import COUNTS, MV_METRICS
from juli_backend.services.analytics_agent.create_card import CARD_TYPES, REQUIRED
from juli_backend.services.analytics_agent.types import TEMPLATES
from juli_backend.services.metrics.registry import METRICS as REGISTRY

AS_OF = "2026-10-07"


# ------------------------------------------------------------------ periods


@dataclass(frozen=True)
class Period:
    id: str
    source: str  # the code constant / rule the value comes from
    intent: dict[str, Any]  # the parser's time slots
    preset: str | None  # the window the router should pick (None = not built: ask)
    cur: tuple[str, str] | None  # the window's days
    prev: tuple[str, str] | None  # the comparison window as WINDOWS describes it
    sale: bool = False  # the window holds a sale day (windows.is_sale_day)


PERIODS: tuple[Period, ...] = (
    Period(
        "yesterday",
        "WINDOWS[yesterday_vs_same_weekday]",
        {"time_phrase": "yesterday"},
        "yesterday_vs_same_weekday",
        ("2026-10-07", "2026-10-07"),
        None,
    ),
    Period(
        "this_week",
        "WINDOWS[this_week_vs_same_days_last_week]",
        {"time_phrase": "this week"},
        "this_week_vs_same_days_last_week",
        ("2026-10-05", "2026-10-07"),
        ("2026-09-28", "2026-09-30"),
    ),
    Period(
        "last_week",
        "WINDOWS[last_full_week_vs_week_before]",
        {"time_phrase": "last week"},
        "last_full_week_vs_week_before",
        ("2026-09-28", "2026-10-04"),
        ("2026-09-21", "2026-09-27"),
    ),
    Period(
        "this_vs_last_week",
        "WINDOWS[this_week_vs_same_days_last_week] (both weeks named)",
        {"time_phrase": "this week compared with last week"},
        "this_week_vs_same_days_last_week",
        ("2026-10-05", "2026-10-07"),
        ("2026-09-28", "2026-09-30"),
    ),
    Period(
        "7d",
        "WINDOWS[last_7d_vs_prev_7d]",
        {"time_phrase": "last 7 days"},
        "last_7d_vs_prev_7d",
        ("2026-10-01", "2026-10-07"),
        ("2026-09-24", "2026-09-30"),
    ),
    Period("14d", "no preset in WINDOWS", {"time_phrase": "last 14 days"}, None, None, None),
    Period(
        "30d",
        "WINDOWS[last_30d_vs_prev_30d]",
        {"time_phrase": "last 30 days"},
        "last_30d_vs_prev_30d",
        ("2026-09-08", "2026-10-07"),
        ("2026-08-09", "2026-09-07"),
    ),
    Period("90d", "no preset in WINDOWS", {"time_phrase": "last 90 days"}, None, None, None),
    Period(
        "this_month",
        "WINDOWS[mtd_vs_same_days_last_month]",
        {"time_phrase": "this month"},
        "mtd_vs_same_days_last_month",
        ("2026-10-01", "2026-10-07"),
        ("2026-09-01", "2026-09-07"),
    ),
    Period(
        "last_month",
        "WINDOWS[last_month_vs_month_before]",
        {"time_phrase": "last month"},
        "last_month_vs_month_before",
        ("2026-09-01", "2026-09-30"),
        ("2026-08-01", "2026-08-31"),
        sale=True,
    ),
    Period(
        "named_finished",
        "WINDOWS[named_month_vs_previous] (month over)",
        {"time_phrase": "September", "named_month": "2026-09"},
        "named_month_vs_previous",
        ("2026-09-01", "2026-09-30"),
        ("2026-08-01", "2026-08-31"),
        sale=True,
    ),
    Period(
        "named_unfinished",
        "WINDOWS[named_month_vs_previous] (month running)",
        {"time_phrase": "October", "named_month": "2026-10"},
        "named_month_vs_previous",
        ("2026-10-01", "2026-10-07"),
        ("2026-09-01", "2026-09-07"),
    ),
    Period(
        "named_not_started",
        "WINDOWS[named_month_vs_previous] (month not begun)",
        {"time_phrase": "November", "named_month": "2026-11"},
        "named_month_vs_previous",
        None,
        None,
    ),
    Period(
        "explicit_range",
        "INTENT_TOOL explicit_from / explicit_to",
        {"time_phrase": "2/10 to 5/10", "explicit_from": "2026-10-02", "explicit_to": "2026-10-05"},
        None,
        ("2026-10-02", "2026-10-05"),
        ("2026-09-28", "2026-10-01"),
    ),
    Period(
        "single_date",
        "INTENT_TOOL explicit_from = explicit_to",
        {"time_phrase": "3/10", "explicit_from": "2026-10-03", "explicit_to": "2026-10-03"},
        None,
        ("2026-10-03", "2026-10-03"),
        ("2026-10-02", "2026-10-02"),
    ),
    Period(
        "sale_day",
        "windows.is_sale_day (the 25th), explicit date",
        {"time_phrase": "25/9", "explicit_from": "2026-09-25", "explicit_to": "2026-09-25"},
        None,
        ("2026-09-25", "2026-09-25"),
        ("2026-09-24", "2026-09-24"),
        sale=True,
    ),
    Period(
        "none",
        "no time slot: WINDOWS[last_30d_vs_prev_30d] ('no period named')",
        {},
        "last_30d_vs_prev_30d",
        ("2026-09-08", "2026-10-07"),
        ("2026-08-09", "2026-09-07"),
    ),
)
EXPLICIT = {"explicit_range", "single_date", "sale_day"}


# ------------------------------------------------------------------ scopes


@dataclass(frozen=True)
class Scope:
    id: str
    source: str
    intent: dict[str, Any]
    kind: str  # shop | product | voucher | affiliate | campaign | programme | channel | ad_type
    item: str | None = None


SCOPES: tuple[Scope, ...] = (
    Scope("shop", "routing.SCOPES[shop]", {}, "shop"),
    Scope(
        "product_name",
        "routing.SCOPES[product] + catalog_search (name words)",
        {"product_phrase": "găng tay"},
        "product",
        "1001",
    ),
    Scope(
        "product_id",
        "catalog_search (exact item id)",
        {"product_phrase": "1002"},
        "product",
        "1002",
    ),
    Scope(
        "product_sku", "catalog_search (seller SKU)", {"product_phrase": "T1"}, "product", "1003"
    ),
    Scope("voucher", "ENTITY_WORDS[voucher]", {"entity_phrase": "voucher"}, "voucher"),
    Scope(
        "affiliate",
        "ENTITY_WORDS[affiliate] (TTLK)",
        {"source_phrase": "Tiếp thị liên kết"},
        "affiliate",
    ),
    Scope("kol", "ENTITY_WORDS[affiliate] (KOL)", {"entity_phrase": "KOL"}, "affiliate"),
    Scope("campaign", "_CAMPAIGN + _AD_WORDS", {"entity_phrase": "ad campaign"}, "campaign"),
    Scope(
        "combo",
        "ENTITY_WORDS[program] combo khuyến mãi",
        {"entity_phrase": "combo khuyến mãi"},
        "programme",
    ),
    Scope(
        "add_on",
        "ENTITY_WORDS[program] mua kèm deal sốc",
        {"entity_phrase": "mua kèm deal sốc"},
        "programme",
    ),
    Scope(
        "flash_sale",
        "ENTITY_WORDS[program] flash sale của shop",
        {"entity_phrase": "flash sale của shop"},
        "programme",
    ),
    Scope(
        "programme",
        "ENTITY_WORDS[program] chương trình của shop",
        {"entity_phrase": "chương trình của shop"},
        "programme",
    ),
    Scope(
        "gift",
        "ENTITY_WORDS[program] mua để nhận quà",
        {"entity_phrase": "mua để nhận quà"},
        "programme",
    ),
    Scope("channel_organic", "registry channel_*_organic", {"source_phrase": "Organic"}, "channel"),
    Scope(
        "channel_ads", "labels.sources[ads] Quảng cáo", {"source_phrase": "Quảng cáo"}, "channel"
    ),
    Scope(
        "dvht_product",
        "labels.sources[ads_product]",
        {"source_phrase": "Dịch vụ hiển thị Sản phẩm"},
        "ad_type",
    ),
    Scope(
        "dvht_shop",
        "labels.sources[ads_shop]",
        {"source_phrase": "Dịch vụ hiển thị Shop+"},
        "ad_type",
    ),
    Scope(
        "ads_live",
        "labels.sources[live] (ads: tag 2)",
        {"source_phrase": "Livestream ads"},
        "ad_type",
    ),
    Scope(
        "ads_other", "the 'Khác' ads line (tag 2)", {"source_phrase": "other ads (Khác)"}, "ad_type"
    ),
)


# ------------------------------------------------------------------ metrics

#: Chat's own metric for a registry key it has (routing.METRICS + REGISTRY_TO_AGENT)
AGENT_OF = {
    **{k: k for k in routing.METRICS if k in REGISTRY},
    "roas_break_even": "roas_break_even",
    **{k: v for k, v in routing.REGISTRY_TO_AGENT.items() if v in routing.METRICS},
}


def metric_ids() -> tuple[str, ...]:
    """Every metric id the parser may emit: the registry keys (`INTENT_TOOL.metric_key` enum)
    plus "none"."""
    return (*routing._registry_metric_keys(), "none")


def phrase_of(key: str) -> str | None:
    """The parser's English metric phrase: the registry key read as words."""
    return None if key == "none" else key.replace("_", " ")


# ------------------------------------------------------------------ outputs and modes

OUTPUTS: dict[str, str] = {
    "value": "LOOKUPS[metric_total]",
    "comparison": "LOOKUPS[metric_total] (the window before)",
    "top": "LOOKUPS[top_products] (INTENT_TOOL ranking=top)",
    "decline": "LOOKUPS[top_decliners] (ranking=decline)",
    "breakdown": "LOOKUPS[channel_breakdown]",
    "trend": "LOOKUPS[daily_trend]",
    "why": "MODES[why] + CHAINS",
    "verdict": "entities.campaign_verdict / product_loss (lãi / lỗ)",
}
LOOKUP_OF = {
    "value": "metric_total",
    "comparison": "metric_total",
    "top": "top_products",
    "decline": "top_decliners",
    "breakdown": "channel_breakdown",
    "trend": "daily_trend",
    "why": "metric_total",
    "verdict": "metric_total",
}

GOALS: tuple[str, ...] = tuple(
    routing.INTENT_TOOL["input_schema"]["properties"]["intents"]["items"]["properties"]["goal"][
        "enum"
    ]
)
ADVISOR_TOOLS: tuple[str, ...] = tuple(
    s["name"] for s in _tool_specs(list(levers.card_kinds(None))) if s["name"] != "emit_plan"
)
DRAFT_KINDS: tuple[str, ...] = tuple(levers.card_kinds(None))
TEMPLATE_KEYS: tuple[str, ...] = tuple(t.key for t in TEMPLATES)
CHAIN_NAMES: tuple[str, ...] = tuple(routing.CHAINS)
LOOKUP_NAMES: tuple[str, ...] = tuple(routing.LOOKUPS)
INTENT_COUNTS: tuple[int, ...] = tuple(range(1, routing.MAX_INTENTS + 3))  # 1..5


@dataclass(frozen=True)
class Dimension:
    name: str
    source: str
    values: tuple[str, ...]
    notes: dict[str, str] = field(default_factory=dict)


def dimensions() -> list[Dimension]:
    return [
        Dimension(
            "period",
            "routing.WINDOWS + INTENT_TOOL time slots",
            tuple(p.id for p in PERIODS),
            {p.id: p.source for p in PERIODS},
        ),
        Dimension(
            "scope",
            "routing.SCOPES + ENTITY_WORDS + labels.sources",
            tuple(s.id for s in SCOPES),
            {s.id: s.source for s in SCOPES},
        ),
        Dimension("metric", "INTENT_TOOL.metric_key enum (metrics.registry) + none", metric_ids()),
        Dimension("output", "routing.LOOKUPS + MODES + verdicts", tuple(OUTPUTS), OUTPUTS),
        Dimension("card_type", "create_card.CARD_TYPES", tuple(CARD_TYPES)),
        Dimension("goal", "INTENT_TOOL goal enum", GOALS),
        Dimension("advisor_tool", "advisor._tool_specs", ADVISOR_TOOLS),
        Dimension("draft_kind", "levers.card_kinds", DRAFT_KINDS),
        Dimension("template", "types.TEMPLATES", TEMPLATE_KEYS),
        Dimension("chain", "routing.CHAINS", CHAIN_NAMES),
        Dimension("lookup", "routing.LOOKUPS", LOOKUP_NAMES),
        Dimension("intents", "1 .. MAX_INTENTS + 2", tuple(str(n) for n in INTENT_COUNTS)),
    ]


__all__ = [
    "ADVISOR_TOOLS",
    "AGENT_OF",
    "AS_OF",
    "CARD_TYPES",
    "COUNTS",
    "DRAFT_KINDS",
    "EXPLICIT",
    "GOALS",
    "LOOKUP_OF",
    "MV_METRICS",
    "OUTPUTS",
    "PERIODS",
    "REQUIRED",
    "SCOPES",
    "TEMPLATE_KEYS",
    "dimensions",
    "metric_ids",
    "phrase_of",
]
