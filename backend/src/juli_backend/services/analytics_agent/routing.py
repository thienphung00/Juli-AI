"""Intent parse (E1) and Jev routing (E2): thresholds, cross-checks, lookup rules, needs_choice
resume.

The LLM turns the Vietnamese question into English intent JSON (strict tool schema, product phrase
verbatim). One Jev request per intent routes it; code applies the thresholds (J7) and cross-checks
(J6).
A `needs_choice` answer carries `pending`; the seller's tap resumes from it in code, no new Jev
call.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from juli_backend.services.analytics_agent.chains import CHAIN_METRIC
from juli_backend.services.analytics_agent.create_card import CARD_TYPES
from juli_backend.services.analytics_agent.types import (
    DataPort,
    JevPort,
    LabelTable,
    LLMPort,
    Usage,
)
from juli_backend.services.analytics_agent.windows import (
    ASK_PERIODS,
    OTHER_PERIOD,
    OTHER_PERIOD_VI,
    PERIOD_VI,
    anchor_for,
    build_windows,
    fold,
    folded,
    window_from_phrase,
)

MAX_INTENTS = 3  # config value (J3); the rest is offered through `more`
FITS_GO, FITS_NO = 0.7, 0.3
P_TOP, RATIO = 0.6, 2.0
MAX_CLARIFY_TURNS = 2

CHAINS: dict[str, str] = {
    "orders_change": "why the number of orders went down, up, or to zero (not revenue, not click "
    "rates)",
    "ctr_change": "why the click-through rate (clicks / views) changed (not clicks turning into "
    "orders)",
    "ctor_change": "why the conversion from clicks to orders changed (not views or click-through)",
    "gmv_change": "why revenue / GMV / sales value changed (not order count only)",
    "profit_change": "why profit or profit margin changed (not revenue without costs)",
    "ads_change": "why ad spend or ROAS (ad revenue / ad cost) changed (not total revenue)",
    "cost_change": "why total costs (ads, affiliate, offers) as a share of net revenue changed",
}
METRICS: dict[str, str] = {
    "gmv": "revenue, GMV, sales value, doanh thu",
    "orders": "number of orders, đơn hàng",
    "aov": "average order value",
    "units": "units / items sold",
    "views": "product views, traffic, lượt xem",
    "clicks": "clicks on products",
    "ctr": "click-through rate, clicks divided by views",
    "ctor": "conversion from clicks to orders, orders divided by clicks",
    "profit": "profit, lợi nhuận, money left after costs",
    "margin": "profit margin, biên lợi nhuận (%)",
    "ads_spend": "advertising spend, chi phí quảng cáo",
    "roas": "ROAS, ad revenue divided by ad spend",
    "cost_ratio": "total cost as a share of net revenue",
}
WINDOWS: dict[str, str] = {
    "yesterday_vs_same_weekday": "yesterday or one recent day",
    "this_week_vs_same_days_last_week": "this week so far (Monday to yesterday) compared with the "
    "same days last week",
    "last_7d_vs_prev_7d": "the last 7 days, recently over a few days",
    "last_full_week_vs_week_before": "last calendar week (Mon-Sun) compared with the week before",
    "last_30d_vs_prev_30d": "the last 30 days or 'recently' with no period named",
    "mtd_vs_same_days_last_month": "this month so far compared with last month",
    "last_month_vs_month_before": "the whole of last month compared with the month before it",
    "named_month_vs_previous": "a specific named month compared with the month before it",
}
SCOPES = {"shop": "the whole shop, all products", "product": "one specific product"}
MODES = {
    "why": "asks WHY a number changed, what caused it, or whether something is wrong",
    "lookup": "asks WHAT a number is, HOW MUCH, a top list, or the trend, without asking why",
}
LOOKUPS = {
    "metric_total": "one metric's value for a period, compared with the period before",
    "top_products": "the products ranked by revenue or orders for a period",
    "top_decliners": "the products whose revenue fell the most compared with the period before",
    "daily_trend": "the metric day by day over a period",
    "channel_breakdown": "the metric split by traffic source / channel for a period",
}
CHAIN_ALLOWED_METRICS = {
    "orders_change": {"orders", "units"},
    "gmv_change": {"gmv", "aov"},
    "ctr_change": {"ctr", "clicks", "views"},
    "ctor_change": {"ctor"},
    "profit_change": {"profit", "margin"},
    "ads_change": {"ads_spend", "roas"},
    "cost_change": {"cost_ratio"},
}

# A named metric needs no picker (Q19): the words map to one metric, code decides, not the model.
METRIC_WORDS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (folded(rx), m)
    for rx, m in (
        (r"chi phí quảng cáo|ad(s|vertising)?\s*(spend|cost)|tiền quảng cáo", "ads_spend"),
        (r"roas hoà vốn|roas hòa vốn|break-?even roas", "roas_break_even"),
        (r"roas", "roas"),
        (r"biên|margin", "margin"),
        (r"lợi nhuận|profit", "profit"),
        (r"average order value|\baov\b|giá trị đơn trung bình|đơn trung bình", "aov"),
        (r"doanh thu|\bgmv\b|revenue|sales value", "gmv"),
        (r"đơn hàng|số đơn|\borders?\b", "orders"),
        (r"\bctor\b|chuyển đổi|conversion", "ctor"),
        (r"\bctr\b|click[- ]through", "ctr"),
        (r"lượt xem|\bviews?\b", "views"),
    )
)
DECLINE_WORDS = folded(
    r"biggest (decline|drop|fall)|fell (the )?most|declin|(dropped|fallen|falling) (the )?most|"
    r"giảm (mạnh|nhiều) nhất|giảm mạnh|tụt (mạnh|nhiều)|tụt nhất|worst"
)
#: a top list named in words (the parser's `ranking` slot left none): best sellers, top by a metric
TOP_WORDS = folded(
    r"best[- ]sell|sell(s|ing)? (the )?best|top (\d+ )?(products?|sellers?)|bán (chạy|tốt) nhất|"
    r"bán chạy|sản phẩm (nào )?(tốt|cao) nhất"
)
LIST_LOOKUPS = ("top_products", "top_decliners")
METRIC_CHAIN = {m: c for c, m in CHAIN_METRIC.items()}
METRIC_CHAIN.update(
    roas="ads_change",
    roas_break_even="ads_change",
    ads_spend="ads_change",
    margin="profit_change",
    aov="gmv_change",
)

# An entity the seller names (Q17): the answer must be filtered to it or refused, never a shop
# number under the entity's label.
ENTITY_WORDS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (folded(rx), k)
    for rx, k in (
        # a Shopee programme named as the seller sees it: no reader filters by it -> refusal
        (
            r"chương trình của shop|flash sale của shop|combo khuyến mãi|mua kèm deal sốc|"
            r"mua để nhận quà",
            "program",
        ),
        (r"voucher|mã giảm giá", "voucher"),
        # "phí hoa hồng" / "phí cố định" are Shopee fees, never affiliate commission
        (r"affiliate|tiếp thị liên kết|\bttlk\b|\bkoc\b|\bkol\b|hoa hồng tiếp thị", "affiliate"),
    )
)
_AD_WORDS = folded(r"quảng cáo|\bqc\b|dvht|dịch vụ hiển thị|\bads?\b|advertis")
_CAMPAIGN = folded(r"campaign|chiến dịch")
_PRODUCT_LOSS = folded(
    r"(sản phẩm|products?).{0,40}(lỗ|losing|loss|lose)|(lỗ|losing|loss).{0,40}(sản phẩm|products?)"
)
#: one ads line of Tổng quan's Quảng cáo split (channel_split's ad rows), named beside an ad word
AD_LINE_WORDS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (folded(rx), k)
    for rx, k in (
        (r"dvht\s*shop|dịch vụ hiển thị shop|shop\s*\+|shop plus", "ads_shop"),
        (r"dvht\s*(sản phẩm|sp\b)|dịch vụ hiển thị sản phẩm|product ads", "ads_product"),
        (r"livestream|\blive\b", "ads_livestream"),
        (r"\bkhác\b|\bother\b", "ads_other"),
    )
)
#: affiliate commission named without the channel ("tốn bao nhiêu hoa hồng"); "phí hoa hồng" is
#: a Shopee fee, never the affiliate's
_COMMISSION = folded(r"(?<!phí )hoa hồng|(?<!fee )commission(?! fee)")
_AFFILIATE = folded(r"affiliate|tiếp thị liên kết|\bttlk\b|\bkoc\b|\bkol\b")


#: registry metric key -> the agent's own metric key (where they differ)
REGISTRY_TO_AGENT = {
    "cost_ads": "ads_spend",
    "cost_total_pct": "cost_ratio",
    "net_revenue": "net_revenue",
}


def named_metric_of(intent: dict[str, Any]) -> str | None:
    """The metric the seller named: the parser's typed `metric_key` wins; the phrase words are a
    safety net."""
    mk = intent.get("metric_key")
    if mk and mk != "none":
        agent = REGISTRY_TO_AGENT.get(mk, mk)
        if agent in METRICS or agent == "roas_break_even":
            return agent
    return metric_from_phrase(intent.get("metric_phrase"))


def metric_from_phrase(phrase: str | None) -> str | None:
    text = fold(phrase or "")
    for rx, m in METRIC_WORDS:
        if text and rx.search(text):
            return m
    return None


def entity_kind(intent: dict[str, Any]) -> str | None:
    """voucher | affiliate | campaign | program when the question names one (not a product: that
    is `scope`). Scans the seller's own words (`raw_text`) as well as the parsed phrases, accented
    or not. In a message split into several intents, the whole message (`msg_text`) is context
    only: "chiến dịch nào lỗ" beside "Quảng cáo tuần trước: ..." is an ad campaign, "tốn bao nhiêu
    hoa hồng" beside "Tiếp thị liên kết" is the affiliate's commission -- the intent's own words
    still name the entity."""
    # the parser's own entity slot wins; the word lists are only a safety net
    first = fold(str(intent.get("entity_phrase") or ""))
    for rx, k in ENTITY_WORDS:
        if first and rx.search(first):
            return k
    if first and _CAMPAIGN.search(first):
        return "campaign"
    blob = fold(
        " ".join(
            str(intent.get(k) or "")
            for k in ("entity_phrase", "metric_phrase", "source_phrase", "raw_text")
        )
    )
    context = blob + " " + fold(str(intent.get("msg_text") or ""))
    for rx, k in ENTITY_WORDS:
        if rx.search(blob):
            return k
    if ad_line_of(intent):
        return "ad_line"
    if _CAMPAIGN.search(blob) and _AD_WORDS.search(context):  # a campaign means an ad campaign
        return "campaign"
    if _PRODUCT_LOSS.search(blob) and _AD_WORDS.search(context):  # "sản phẩm nào lỗ sau quảng cáo"
        return "product_loss"
    if _COMMISSION.search(blob) and _AFFILIATE.search(context):
        return "affiliate"
    return None


def ad_line_of(intent: dict[str, Any]) -> str | None:
    """ads_product | ads_shop | ads_livestream | ads_other when the intent's own words name one
    ads line together with an ad word ("Quảng cáo Livestream", "DVHT Shop+")."""
    blob = fold(
        " ".join(
            str(intent.get(k) or "")
            for k in ("entity_phrase", "metric_phrase", "source_phrase", "raw_text")
        )
    )
    if not _AD_WORDS.search(blob):
        return None
    return next((k for rx, k in AD_LINE_WORDS if rx.search(blob)), None)


def ranking_of(intent: dict[str, Any]) -> str:
    """top | decline | none: the parser's typed slot, else the intent's own words (a best-seller
    or biggest-drop list is answered as one, never by asking which number)."""
    typed = str(intent.get("ranking") or "none")
    if typed in ("top", "decline"):
        return typed
    said = fold(str(intent.get("metric_phrase") or ""))
    if DECLINE_WORDS.search(said):
        return "decline"
    if TOP_WORDS.search(said):
        return "top"
    return "none"


def window_of(intent: dict[str, Any]) -> str | None:
    """The window the seller named (owner #113: never asked, never moved), else None: the
    question names no period and Chat asks for one (`ASK_PERIODS`). Explicit dates run as given
    (`custom`, the engine reads them)."""
    return named_period(intent)


def _ask_period(dec: dict[str, Any]) -> dict[str, Any]:
    """Owner #113: no period named -> one question, the period buttons; nothing is assumed."""
    dec.update(outcome="needs_choice", remaining=[("window", list(ASK_PERIODS))])
    return dec


def named_period(intent: dict[str, Any]) -> str | None:
    """The window the seller named in words or dates ("custom" for explicit dates), else None."""
    if intent.get("explicit_from") and intent.get("explicit_to"):
        return "custom"
    if intent.get("named_month"):
        return "named_month_vs_previous"
    return window_from_phrase(intent.get("time_phrase"))


#: the empty value of each create-card slot (the strict schema allows no optional / union fields)
CARD_SLOT_EMPTY: dict[str, Any] = {
    "card_type": "none",
    "from_date": "",
    "to_date": "",
    "start_hour": -1,
    "amount": -1,
    "amount_unit": "none",
    "min_spend": -1,
    "quantity": -1,
    "name": "",
}
CREATE_SLOTS = (
    "card_type",
    "from_date",
    "to_date",
    "start_hour",
    "amount",
    "amount_unit",
    "min_spend",
    "quantity",
    "name",
)


def _registry_metric_keys() -> list[str]:
    from juli_backend.services.metrics.registry import METRICS as REG

    return list(REG)


def _registry_metric_names() -> str:
    """User-facing metric names, generated from registry.py (never hand-typed)."""
    from juli_backend.services.metrics.registry import METRICS

    return "; ".join(f"{k} = {m.label_vi}" for k, m in METRICS.items() if "{" not in m.label_vi)


INTENT_TOOL: dict[str, Any] = {
    "name": "emit_intent",
    "strict": True,
    "description": "Return the seller's question as structured English intent.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["intents", "restated_vi"],
        "properties": {
            "restated_vi": {
                "type": "string",
                "description": "the seller's question restated as one full Vietnamese sentence "
                "(never a placeholder)",
            },
            "intents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "question_type",
                        "metric_phrase",
                        "claimed_direction",
                        "time_phrase",
                        "explicit_from",
                        "explicit_to",
                        "named_month",
                        "product_phrase",
                        "source_phrase",
                        "entity_phrase",
                        "metric_key",
                        "ranking",
                        "asks_why",
                        "needs_advice",
                        "goal",
                        "card",
                    ],
                    "properties": {
                        "question_type": {
                            "type": "string",
                            "enum": [
                                "why_changed",
                                "status",
                                "compare",
                                "plan",
                                "create_card",
                                "other",
                            ],
                        },
                        "metric_phrase": {"type": ["string", "null"]},
                        "claimed_direction": {
                            "type": "string",
                            "enum": ["down", "up", "zero", "changed", "none"],
                        },
                        "time_phrase": {"type": ["string", "null"]},
                        "explicit_from": {
                            "type": ["string", "null"],
                            "description": "YYYY-MM-DD only if the seller gave dates",
                        },
                        "explicit_to": {"type": ["string", "null"]},
                        "named_month": {
                            "type": ["string", "null"],
                            "description": "YYYY-MM if one month is named",
                        },
                        "product_phrase": {
                            "type": ["string", "null"],
                            "description": "the product words copied exactly as the seller wrote "
                            "them, no translation",
                        },
                        "source_phrase": {"type": ["string", "null"]},
                        "metric_key": {
                            "type": "string",
                            "enum": [*_registry_metric_keys(), "none"],
                            "description": "the registry key of the metric the seller asks about "
                            "(the prompt lists key = label); none when no metric is asked",
                        },
                        "ranking": {
                            "type": "string",
                            "enum": ["none", "top", "decline"],
                            "description": "top = best sellers / top by a metric; decline = the "
                            "biggest drop; none = not a ranking",
                        },
                        "asks_why": {
                            "type": "boolean",
                            "description": "true when the seller also asks why",
                        },
                        "needs_advice": {
                            "type": "boolean",
                            "description": "true when the seller asks what to do, what to "
                            "prioritise, what to do first or which card to open, or asks "
                            "whether to do something (raise the ads budget, stop a campaign "
                            "or a product's ads), what to fix (a title, a price, a cover "
                            "image, a description) or how to handle or what to do about a problem "
                            "in the shop's own data, over the "
                            "shop's own data (a plan, a priority, a recommendation)",
                        },
                        "goal": {
                            "type": "string",
                            "enum": [
                                "none",
                                "plan_week",
                                "prioritise",
                                "ads",
                                "profit",
                                "traffic",
                                "pricing_promo",
                                "product",
                            ],
                            "description": "what the advice is for; none when needs_advice is "
                            "false",
                        },
                        "card": {
                            "type": "object",
                            "description": "only for question_type create_card; otherwise leave "
                            "every field at its empty value",
                            "additionalProperties": False,
                            "required": list(CARD_SLOT_EMPTY),
                            "properties": {
                                "card_type": {
                                    "type": "string",
                                    "enum": [*CARD_TYPES, "none"],
                                    "description": "the kind of card; none when not said",
                                },
                                "from_date": {
                                    "type": "string",
                                    "description": "YYYY-MM-DD or empty",
                                },
                                "to_date": {"type": "string", "description": "YYYY-MM-DD or empty"},
                                "start_hour": {
                                    "type": "integer",
                                    "description": "flash sale start hour 0-23, -1 if unsaid",
                                },
                                "amount": {
                                    "type": "number",
                                    "description": "discount value said, -1 if unsaid",
                                },
                                "amount_unit": {"type": "string", "enum": ["vnd", "pct", "none"]},
                                "min_spend": {
                                    "type": "integer",
                                    "description": "minimum order in đ, 0 = none, -1 when not said",
                                },
                                "quantity": {"type": "integer", "description": "-1 when not said"},
                                "name": {"type": "string", "description": "a name given, or empty"},
                            },
                        },
                        "entity_phrase": {
                            "type": ["string", "null"],
                            "description": "a voucher, affiliate / commission or ad campaign the "
                            "seller names, copied as written; null when none",
                        },
                    },
                },
            },
        },
    },
}


PARSE_SYSTEM = (
    "Turn a Shopee seller's Vietnamese question into English intent JSON by calling emit_intent. "
    "Today is {today} (Vietnam). Split a message that asks about several metrics into one intent "
    "each. "
    "Write phrases in plain English, except product_phrase: copy the seller's own product words "
    "verbatim. "
    "The seller's metrics are named in this registry (a question that asks for or about any of "
    "them is 'status' or 'why_changed', never 'other'; set metric_key to its key, none if no "
    "metric is asked; ranking is top for best sellers / top by a metric, decline for the biggest "
    "drop; asks_why is true when the seller also asks why): " + _registry_metric_names() + ". "
    "Do not invent ids. Dates only when the seller states them. Questions not about the shop's own "
    "sales/traffic data (competitors, tax, forecasts) get question_type 'other'. A question asking "
    "what the shop should do next week is question_type 'plan' (only that, not how-to "
    "questions). A question that asks what to do, what to prioritise, what to do first or which "
    "card to open, or asks whether to do something (raise the ads budget, turn off campaigns, stop "
    "a product's ads) or what to fix, how to handle or what to do about a problem in the shop's "
    "own data (expired deal prices, titles, prices, cover image, description, unspent ads "
    "budget), about the shop's own numbers (not a general how-to or knowledge question about "
    "how Shopee works, not an order to create or change something), sets needs_advice true and a "
    "goal; "
    "every other question has needs_advice false and goal none. A question about ONE "
    "product's profit, margin, revenue or orders is question_type 'status' with product_phrase, "
    "never 'other'. "
    "A question that asks both what and why (for example the products that fell most, and "
    "why) is ONE intent with ranking and asks_why true. "
    "A request to create or change something (voucher, discount, combo, deal, gift, "
    "flash sale, price, product name / title, cover, variation set) is question_type "
    "'create_card': fill the `card` object with only the slots the seller said (dates as "
    "YYYY-MM-DD in the year of today, amount with amount_unit vnd or pct) and leave every other "
    "field at its empty value (none, empty text, -1); never invent a value. "
    "An order to change the ads budget, a ROAS target or an "
    "affiliate commission (not a question whether to), a how-to or knowledge question (how to "
    "get more views, how a Shopee fee is calculated) and a question about competitors are "
    "question_type 'other'."
)
RESTATE_PREFIX = "Đang tìm hiểu: "
_PREFIXES = re.compile(r"^\s*(đang tìm hiểu|tôi hiểu)\s*[:：]\s*", re.I)
_PLACEHOLDER = re.compile(r"(placeholder|lorem|^\W*$|^(n/?a|none|null|tbd|\.\.\.|…)$)", re.I)


def clean_restatement(restated: str | None, seller_text: str) -> str:
    """Restatement guard: empty / placeholder / no letters -> the seller's own words. Always
    prefixed."""
    body = _PREFIXES.sub("", restated or "").strip()
    if not body or _PLACEHOLDER.search(body) or not re.search(r"[^\W\d_]{2,}", body):
        body = seller_text.strip()
    return RESTATE_PREFIX + body.rstrip(".")


def flatten_card(intent: dict[str, Any]) -> dict[str, Any]:
    """The schema's `card` object (sentinels for "not said") becomes the flat slots the engine
    reads, None for "not said". An intent with the flat slots already (tests, old rows) is kept."""
    card = intent.pop("card", None)
    if not isinstance(card, dict):
        return intent
    for k, empty in CARD_SLOT_EMPTY.items():
        v = card.get(k, empty)
        intent[k] = None if v == empty else v
    return intent


async def parse_intents(
    llm: LLMPort, text: str, today: date
) -> tuple[dict[str, Any] | None, Usage]:
    """Strict-schema parse, one retry. Returns {"restated", "intents", "more"} or None (-> template
    buttons)."""
    cost = 0.0
    for _ in range(2):
        out, u = await llm.parse(PARSE_SYSTEM.format(today=today.isoformat()), INTENT_TOOL, text)
        cost += u.cost_usd
        intents = (out or {}).get("intents")
        if isinstance(intents, list) and intents and all(isinstance(i, dict) for i in intents):
            for i in intents:
                flatten_card(i)
            return (
                {
                    "restated": clean_restatement((out or {}).get("restated_vi"), text),
                    "intents": intents[:MAX_INTENTS],
                    "more": intents[MAX_INTENTS:],
                },
                Usage(cost_usd=cost),
            )
    return None, Usage(cost_usd=cost)


# ------------------------------------------------------------------ Jev request


def _crit(d: dict[str, str]) -> dict[str, str]:
    return dict(d)


async def route(jev: JevPort, intent: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], Usage]:
    """The Jev routing answers of one intent; a plan / create request needs none (code decides)."""
    if intent.get("question_type") in ("plan", "create_card") or wants_advice(intent):
        return {}, Usage()
    return await jev.ask(jev_state(intent), routing_questions(intent))


async def classify(text: str, today: date, llm: LLMPort, jev: JevPort) -> dict[str, Any]:
    """Parse + routing decision of one message, with NO data reads: what Juli understood and which
    route it would take. For the 20-question check; costs one parse and one Jev call per intent."""
    parsed, usage = await parse_intents(llm, text, today)
    if parsed is None:
        return {"outcome": "parse_failed", "intents": []}
    single = len(parsed["intents"]) == 1
    out: list[dict[str, Any]] = []
    for intent in parsed["intents"]:
        if single:
            intent["raw_text"] = text
        else:
            intent["msg_text"] = text
        answers, _ = await route(jev, intent)
        dec = (
            decide(intent, answers)
            if answers or wants_advice(intent) or intent.get("question_type") == "create_card"
            else {"outcome": "go", "checks": {}}
        )
        out.append(
            {
                "intent": {k: v for k, v in intent.items() if k not in ("raw_text", "msg_text")},
                "outcome": dec.get("outcome"),
                "mode": dec.get("mode"),
                "goal": dec.get("goal"),
                "chain": dec.get("chain"),
                "metric": dec.get("metric"),
                "window": dec.get("window"),
                "lookup": dec.get("lookup"),
                "entity": entity_kind(intent),
                "card_type": intent.get("card_type"),
                "checks": dec.get("checks"),
            }
        )
    return {
        "restated": parsed["restated"],
        "outcome": "parsed",
        "intents": out,
        "cost_usd": usage.cost_usd,
    }


def jev_state(intent: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "question_type",
        "metric_phrase",
        "claimed_direction",
        "time_phrase",
        "product_phrase",
        "source_phrase",
    ]
    return {"intent": {k: intent.get(k) for k in keys}}


def routing_questions(intent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One routing request per intent; fixed option order (J6f); window dropped when dates are
    explicit."""
    qs: dict[str, dict[str, Any]] = {
        "fits": {
            "type": "noul",
            "instructions": (
                "Does `intent` ask why one of the shop's own sales or traffic numbers (orders, "
                "revenue/GMV, average "
                "order value, views, clicks, click-through rate, conversion, profit, profit "
                "margin, ad spend, ROAS, "
                "costs) changed, how much it is, a top list or its trend?"
            ),
        },
        "mode": {
            "type": "choice",
            "instructions": "Is `intent` asking why something changed, or only asking "
            "for a value / list / trend?",
            "criteria": _crit(MODES),
        },
        "lookup": {
            "type": "choice",
            "instructions": "If `intent` only asks for data, which kind of data?",
            "criteria": _crit(LOOKUPS),
        },
        "chain": {
            "type": "choice",
            "instructions": "Which analysis fits `intent`?",
            "criteria": _crit(CHAINS),
        },
        "metric": {
            "type": "choice",
            "instructions": "Which metric does `intent` ask about?",
            "criteria": _crit(METRICS),
        },
        "scope": {
            "type": "choice",
            "instructions": "Does `intent` ask about the whole shop or one specific product?",
            "criteria": _crit(SCOPES),
        },
        "product_named": {"type": "noul", "instructions": "Does `intent` name a specific product?"},
        "metric_named": {
            "type": "noul",
            "instructions": "Does `intent` name one specific number to look at "
            "(orders, revenue, GMV, average order value, views, clicks, CTR, CTOR, conversion, "
            "profit, "
            "margin, ad spend, ROAS, costs), rather than the shop in general?",
        },
    }
    if not (intent.get("explicit_from") and intent.get("explicit_to")):
        qs["window"] = {
            "type": "choice",
            "instructions": "Which time comparison does `intent` ask for?",
            "criteria": _crit(WINDOWS),
        }
    return qs


def choice_ok(a: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    probs = sorted((a.get("probabilities") or {}).items(), key=lambda kv: -kv[1])
    top = probs[0] if probs else (a.get("choice"), 1.0)
    second = probs[1][1] if len(probs) > 1 else 0.0
    ratio = top[1] / second if second else float("inf")
    ok = top[1] >= P_TOP and ratio >= RATIO
    return ok, {
        "pick": top[0],
        "p_top": round(top[1], 4),
        "p_second": round(second, 4),
        "ratio": None if ratio == float("inf") else round(ratio, 2),
        "rule": f"p_top>={P_TOP} and ratio>={RATIO}",
        "pass": ok,
        "top2": [p[0] for p in probs[:2]],
    }


def wants_advice(intent: dict[str, Any]) -> bool:
    """The parser's typed slots decide (no word list): a plan, or needs_advice, over the shop's
    own data. A create request is never advice."""
    if intent.get("question_type") == "create_card":
        return False
    return intent.get("question_type") == "plan" or intent.get("needs_advice") is True


def _mode_of(intent: dict[str, Any]) -> str:
    """The mode the parser's slots imply when the router is split: why only for a why question."""
    if intent.get("question_type") == "why_changed" or intent.get("asks_why"):
        return "why"
    return "lookup" if intent.get("question_type") in ("status", "compare") else "why"


def decide(intent: dict[str, Any], answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Thresholds (J7) + cross-checks (J6b) + lookup rules. `outcome` = go | needs_choice |
    unsupported."""
    dec: dict[str, Any] = {"checks": {}}
    if intent.get("question_type") == "create_card":  # J10: a card from a free request
        dec.update(outcome="go", mode="create")
        return dec
    if wants_advice(intent):  # a plan / priority / "what first" request: the LLM advises (J1)
        dec.update(
            outcome="go",
            mode="advise",
            window=window_from_phrase("last week"),
            goal=str(intent.get("goal") or "none"),
        )
        return dec
    fits = answers["fits"]["noul"]
    dec["checks"]["fits"] = {
        "noul": round(fits, 4),
        "rule": f">={FITS_GO} go, <={FITS_NO} unsupported",
    }
    if intent.get("question_type") == "other" and fits < FITS_GO:
        dec["outcome"] = "unsupported"
        return dec
    if fits <= FITS_NO:
        dec["outcome"] = "unsupported"
        return dec
    rank = ranking_of(intent)
    if rank in ("top", "decline"):  # the typed slot (or the intent's own words) decides, no picker
        dec.update(
            outcome="go",
            mode="lookup",
            lookup="top_decliners" if rank == "decline" else "top_products",
        )
        dec["window"] = window_of(intent)
        dec["metric"] = named_metric_of(intent) or "gmv"
        return dec if dec["window"] else _ask_period(dec)
    ranking = False  # a ranking question needs no metric: it defaults to GMV decline
    if "mode" in answers and "lookup" in answers:
        okm, im = choice_ok(answers["mode"])
        okl, il = choice_ok(answers["lookup"])
        ranking = okm and okl and im["pick"] == "lookup" and il["pick"] in LIST_LOOKUPS
    ent = entity_kind(intent)
    if ent and fits > FITS_NO:  # an entity is answered from its own rows by code (Q17): no picker
        dec.update(outcome="go", mode="lookup", lookup="metric_total")
        dec["window"] = window_of(intent)
        named = named_metric_of(intent)
        dec["metric"] = named or (
            choice_ok(answers["metric"])[1]["pick"] if "metric" in answers else None
        )
        return dec if dec["window"] else _ask_period(dec)
    named_metric = named_metric_of(intent)
    if (
        fits < FITS_GO and not named_metric and not (ranking and fits > FITS_NO)
    ):  # a named metric is a fit (J3): no picker
        dec.update(outcome="needs_choice", remaining=[("chain", list(CHAINS))])
        return dec
    unclear: list[tuple[str, list[str]]] = []
    if "mode" in answers:
        ok, info = choice_ok(answers["mode"])
        dec["checks"]["mode"] = info
        # unclear: the parser's question type decides (a status / compare question is a lookup)
        dec["mode"] = info["pick"] if ok else _mode_of(intent)
        if "lookup" in answers:
            okl, infol = choice_ok(answers["lookup"])
            dec["checks"]["lookup"] = infol
            dec["lookup"] = infol["pick"] if okl else "metric_total"
            if dec["lookup"] in ("top_products", "metric_total", "top_decliners") and (
                DECLINE_WORDS.search(
                    fold(f"{intent.get('metric_phrase') or ''} {intent.get('raw_text') or ''}")
                )
            ):
                dec["lookup"] = "top_decliners"  # "giảm mạnh nhất" is a decline, not top by GMV
    for k in ("chain", "metric", "window", "scope"):
        if k not in answers:
            continue
        ok, info = choice_ok(answers[k])
        dec["checks"][k] = info
        dec[k] = info["pick"]
        if not ok:
            unclear.append((k, info["top2"]))
    preset = window_of(intent)
    # one phrase, one window, never asked; no period named: the seller picks it (owner #113),
    # whatever the router guessed
    unclear = [x for x in unclear if x[0] != "window"]
    if preset:
        dec["window"] = preset
        dec["checks"]["window"] = {"pick": preset, "rule": "phrase"}
    else:
        dec.pop("window", None)
        dec["checks"]["window"] = {"pick": None, "rule": "no period named: asked"}
        unclear.append(("window", list(ASK_PERIODS)))
    named = named_metric_of(intent)
    if named and dec.get("mode") != "lookup":  # a named metric is never asked about (Q19)
        dec["metric"] = named
        dec["chain"] = METRIC_CHAIN.get(named, dec.get("chain"))
        dec["checks"]["metric"] = {"pick": named, "rule": "phrase"}
        unclear = [x for x in unclear if x[0] not in ("chain", "metric")]
        answers = {**answers, "metric_named": {"noul": 1.0}}
    elif named and dec.get("lookup") not in LIST_LOOKUPS:
        dec["metric"] = named
        unclear = [x for x in unclear if x[0] != "metric"]
        answers = {**answers, "metric_named": {"noul": 1.0}}
    mn = answers.get("metric_named", {}).get("noul")
    if mn is not None:
        dec["checks"]["metric_named"] = {
            "noul": round(mn, 4),
            "rule": f"<={FITS_NO} -> ask which metric",
        }
        if mn <= FITS_NO and not (
            dec.get("mode") == "lookup" and dec.get("lookup") in LIST_LOOKUPS
        ):
            unclear.insert(0, ("chain", list(CHAINS)))
    pn = answers.get("product_named", {}).get("noul")
    if pn is not None:
        dec["checks"]["product_named"] = {"noul": round(pn, 4)}
    want = CHAIN_METRIC.get(dec.get("chain", ""))
    if want and dec.get("metric") and dec["metric"] != want and dec.get("mode") != "lookup":
        if dec["metric"] not in CHAIN_ALLOWED_METRICS.get(dec["chain"], set()):
            dec["checks"]["chain_metric_conflict"] = [dec["chain"], dec["metric"]]
            if dec["checks"]["chain"]["p_top"] >= 0.9:
                dec["metric"] = want
            else:
                unclear.insert(0, ("chain", dec["checks"]["chain"]["top2"]))
    if pn is not None and (
        (pn >= FITS_GO and dec.get("scope") == "shop")
        or (pn <= FITS_NO and dec.get("scope") == "product")
    ):
        dec["checks"]["scope_conflict"] = True
        dec["scope"] = "product" if pn >= FITS_GO and intent.get("product_phrase") else "shop"
    if (
        dec.get("mode") == "lookup"
        and dec.get("lookup") not in LIST_LOOKUPS
        and mn is not None
        and mn <= FITS_NO
    ):
        unclear.append(
            ("metric", ["gmv", "orders", "ctr", "ctor", "profit"])
        )  # vague lookup asks which number
    if (
        dec.get("mode") == "lookup"
    ):  # a data answer needs lookup kind + window (+ metric), never chain / scope
        drop = {"chain", "scope"} | ({"metric"} if dec.get("lookup") in LIST_LOOKUPS else set())
        unclear = [x for x in unclear if x[0] not in drop]
        dec["checks"].pop("chain_metric_conflict", None)
    period = named_period(intent)
    if unclear and named and period:
        # #112: a named metric with a named period is answered, never asked about; the router's
        # split votes only fill what the seller did not say (scope: the product named, else shop)
        for k, _ in unclear:
            if k == "scope":
                dec["scope"] = "product" if intent.get("product_phrase") else "shop"
            elif k == "window" and period != "custom":
                dec["window"] = period
        dec["checks"]["named_rule"] = {"metric": named, "period": period, "dropped": unclear}
        unclear = []
    order = ["chain", "metric", "window", "scope"]
    unclear.sort(key=lambda u: order.index(u[0]))
    if unclear:
        dec.update(outcome="needs_choice", remaining=unclear)
    else:
        dec["outcome"] = "go"
    return dec


# ------------------------------------------------------------------ needs_choice


QUESTION_VI = {
    "chain": "Bạn muốn tìm hiểu chỉ số nào?",
    "metric": "Bạn muốn xem chỉ số nào?",
    "window": "Bạn muốn so sánh khoảng thời gian nào?",
    "product": "Bạn muốn nói sản phẩm nào?",
    # a split scope vote used to raise KeyError here (the item had no question)
    "scope": "Bạn muốn xem cả shop hay một sản phẩm?",
}
SCOPE_VI = {"shop": "Cả shop", "product": "Một sản phẩm"}
NO_FULL_DAY_VI = "Tuần này chưa có ngày nào đủ số liệu. Xem tuần trước?"
NO_FULL_MONTH_DAY_VI = "Tháng này chưa có ngày nào đủ số liệu. Xem tháng trước?"
CHAIN_VI = {
    "orders_change": "Đơn hàng",
    "ctr_change": "CTR",
    "ctor_change": "Tỷ lệ chuyển đổi (CTOR)",
    "gmv_change": "GMV",
    "profit_change": "Lợi nhuận / biên lợi nhuận",
    "ads_change": "Quảng cáo (chi phí, ROAS)",
    "cost_change": "Tổng chi phí",
}


def options_vi(
    item: str,
    values: list[str],
    labels: LabelTable,
    as_of: date,
    names: dict[str, str] | None = None,
    latest: date | None = None,
    sale_aware: bool = False,
) -> list[dict[str, str]]:
    out = []
    for v in values:
        if item == "chain":
            label = CHAIN_VI.get(v, v)
        elif item == "metric":
            label = labels.metric(v)
        elif item == "scope":
            label = SCOPE_VI.get(v, v)
        elif item == "window" and v == OTHER_PERIOD:
            label = OTHER_PERIOD_VI
        elif item == "window" and v in ASK_PERIODS and v in PERIOD_VI:
            label = PERIOD_VI[v]  # the period question: the "more" buttons' names (owner #113)
        elif item == "window":
            label = build_windows(
                v, anchor_for(v, as_of, latest), sale_aware=sale_aware
            ).label()  # real dates (U5a)
        else:
            label = (names or {}).get(v, v)
        out.append({"label_vi": label, "value": v})
    return out


def needs_choice_event(
    dec: dict[str, Any],
    intent: dict[str, Any],
    labels: LabelTable,
    as_of: date,
    turns: int = 0,
    names: dict[str, str] | None = None,
    latest: date | None = None,
) -> dict[str, Any]:
    """The event + the `pending` state that lets the engine resume in code (no new Jev call)."""
    item, values = dec["remaining"][0]
    pending = {
        "intent": intent,
        "dec": {k: v for k, v in dec.items() if k not in ("remaining", "outcome")},
        "remaining": [[i, list(v)] for i, v in dec["remaining"]],
        "turns": turns,
    }
    return {
        "type": "needs_choice",
        "item": item,
        "question_vi": QUESTION_VI[item],
        "options": options_vi(item, values, labels, as_of, names, latest, True),
        "pending": pending,
    }


def resume(pending: dict[str, Any], choice: dict[str, Any]) -> dict[str, Any]:
    """Apply the seller's tap to the saved routing state. Returns the decision (go / needs_choice
    again)."""
    dec = dict(pending["dec"])
    item, value = choice["item"], choice["value"]
    if item == "window" and value == OTHER_PERIOD:  # the page sends words instead; ask again
        return {**dec, "outcome": "needs_choice", "remaining": pending["remaining"], "turns": 0}
    dec[item] = value
    if item == "product":
        dec["item_id"] = value
        dec["scope"] = "product"
    rest = [(i, v) for i, v in pending["remaining"] if i != item]
    turns = pending.get("turns", 0) + 1
    period = [(i, v) for i, v in rest if i == "window" and not dec.get("window")]
    if rest and turns < MAX_CLARIFY_TURNS:
        dec.update(outcome="needs_choice", remaining=rest)
    elif period:  # owner #113: the period is the seller's, never the best guess
        dec.update(outcome="needs_choice", remaining=period)
    else:
        dec["outcome"] = "go"  # max 2 clarifying turns, then go with the best pick
    dec["turns"] = turns
    return dec


# ------------------------------------------------------------------ product resolution (J3)


async def resolve_product(
    data: DataPort, jev: JevPort, intent: dict[str, Any]
) -> tuple[dict[str, Any], Usage]:
    """catalog search in code: 1 match -> use; 2+ -> Jev Choice among candidates; 0 -> closest 3."""
    phrase = (intent.get("product_phrase") or "").strip()
    cands = await data.catalog_search(phrase) if phrase else []
    if len(cands) == 1:
        return {
            "status": "found",
            "item_id": cands[0]["item_id"],
            "name": cands[0]["name"],
        }, Usage()
    if len(cands) >= 2:
        crit = {c["item_id"]: (c.get("name") or c["item_id"])[:200] for c in cands}
        ans, u = await jev.ask(
            {"product_phrase": phrase},
            {
                "product": {
                    "type": "choice",
                    "instructions": "Which product does `product_phrase` mean?",
                    "criteria": crit,
                }
            },
        )
        ok, info = choice_ok(ans["product"])
        if ok:
            return {
                "status": "found",
                "item_id": info["pick"],
                "name": crit.get(info["pick"]),
                "check": info,
            }, u
        top3 = [i for i in (info["top2"] + [c["item_id"] for c in cands]) if i in crit]
        top3 = list(dict.fromkeys(top3))[:3]
        return {
            "status": "ambiguous",
            "options": [{"item_id": i, "name": crit[i]} for i in top3],
            "check": info,
        }, u
    words = sorted(re.split(r"\s+", phrase), key=len, reverse=True)[:1]
    near = await data.catalog_search(words[0]) if words and words[0] else []
    return {
        "status": "none",
        "options": [{"item_id": c["item_id"], "name": c.get("name")} for c in near[:3]],
    }, Usage()
