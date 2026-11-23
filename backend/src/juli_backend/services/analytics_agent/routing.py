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
from juli_backend.services.analytics_agent.types import (
    DataPort,
    JevPort,
    LabelTable,
    LLMPort,
    Usage,
)
from juli_backend.services.analytics_agent.windows import (
    anchor_for,
    build_windows,
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
    (re.compile(rx, re.I), m)
    for rx, m in (
        (r"chi phí quảng cáo|ad(s|vertising)?\s*(spend|cost)|tiền quảng cáo", "ads_spend"),
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
DECLINE_WORDS = re.compile(
    r"biggest (decline|drop|fall)|fell (the )?most|declin|(dropped|fallen|falling) (the )?most|"
    r"giảm (mạnh|nhiều) nhất|giảm mạnh|tụt (mạnh|nhiều)|tụt nhất|worst",
    re.I,
)
LIST_LOOKUPS = ("top_products", "top_decliners")
METRIC_CHAIN = {m: c for c, m in CHAIN_METRIC.items()}
METRIC_CHAIN.update(
    roas="ads_change", ads_spend="ads_change", margin="profit_change", aov="gmv_change"
)

# An entity the seller names (Q17): the answer must be filtered to it or refused, never a shop
# number under the entity's label.
ENTITY_WORDS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rx, re.I), k)
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
_AD_WORDS = re.compile(r"quảng cáo|\bqc\b|dvht|dịch vụ hiển thị|\bads?\b|advertis", re.I)
_CAMPAIGN = re.compile(r"campaign|chiến dịch", re.I)


def metric_from_phrase(phrase: str | None) -> str | None:
    for rx, m in METRIC_WORDS:
        if phrase and rx.search(phrase):
            return m
    return None


def entity_kind(intent: dict[str, Any]) -> str | None:
    """voucher | affiliate | campaign | program when the question names one (not a product: that
    is `scope`). Scans the seller's own words (`raw_text`) as well as the parsed phrases."""
    blob = " ".join(
        str(intent.get(k) or "")
        for k in ("entity_phrase", "metric_phrase", "source_phrase", "raw_text")
    )
    for rx, k in ENTITY_WORDS:
        if rx.search(blob):
            return k
    if _CAMPAIGN.search(blob) and _AD_WORDS.search(blob):  # a campaign means an ad campaign
        return "campaign"
    return None


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
                    ],
                    "properties": {
                        "question_type": {
                            "type": "string",
                            "enum": ["why_changed", "status", "compare", "plan", "other"],
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
    "Do not invent ids. Dates only when the seller states them. Questions not about the shop's own "
    "sales/traffic data (competitors, tax, forecasts) get question_type 'other'. A question asking "
    "what the shop should do next / next week, or how to improve, is question_type 'plan'."
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


def decide(intent: dict[str, Any], answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Thresholds (J7) + cross-checks (J6b) + lookup rules. `outcome` = go | needs_choice |
    unsupported."""
    dec: dict[str, Any] = {"checks": {}}
    if intent.get("question_type") == "plan":  # "what should the shop do next week" (J8)
        dec.update(outcome="go", mode="analysis", window=window_from_phrase("last week"))
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
    if fits < FITS_GO:
        dec.update(outcome="needs_choice", remaining=[("chain", list(CHAINS))])
        return dec
    unclear: list[tuple[str, list[str]]] = []
    if "mode" in answers:
        ok, info = choice_ok(answers["mode"])
        dec["checks"]["mode"] = info
        dec["mode"] = info["pick"] if ok else "why"
        if "lookup" in answers:
            okl, infol = choice_ok(answers["lookup"])
            dec["checks"]["lookup"] = infol
            dec["lookup"] = infol["pick"] if okl else "metric_total"
            if dec["lookup"] in ("top_products", "metric_total", "top_decliners") and (
                DECLINE_WORDS.search(
                    f"{intent.get('metric_phrase') or ''} {intent.get('raw_text') or ''}"
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
    preset = window_from_phrase(intent.get("time_phrase"))
    if preset:  # one phrase, one window; never asked
        dec["window"] = preset
        dec["checks"]["window"] = {"pick": preset, "rule": "phrase"}
        unclear = [x for x in unclear if x[0] != "window"]
    named = metric_from_phrase(intent.get("metric_phrase"))
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
}
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
    dec[item] = value
    if item == "product":
        dec["item_id"] = value
        dec["scope"] = "product"
    rest = [(i, v) for i, v in pending["remaining"] if i != item]
    turns = pending.get("turns", 0) + 1
    if rest and turns < MAX_CLARIFY_TURNS:
        dec.update(outcome="needs_choice", remaining=rest)
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
