"""The generated bank (owner, 26/11): the FULL cross product of the dimensions in
`dimensions.py`, at the structured-intent level (the parse is given: no LLM), each combination
a test id, its expected outcome computed by the ORACLE below from a validity table written once
per rule, never per case.

Families:
- data: period x scope x metric x output (the bulk);
- create: every `create_card.CARD_TYPES` kind x product x dates x amount;
- advise: every goal x trigger x advisor tool (every `draft_card` kind);
- plus analysis, explain-a-card, unsupported, ambiguous, templates (router up / down), and
  messages of 1..5 intents.

The router fake is the IDEAL router: it answers clearly with what the combination means, and is
split where the combination names nothing Chat has (so a correct Chat asks). Known gaps are
`GAP_RULES` (one strict rule per gap, matched by a predicate over the dimensions and the problem
text it explains); `test_chat_bank_combos.py` runs them.

`gate()` is the deploy-gate subset: a covering array with every pair of values of every two
data dimensions and every period x metric x scope triple, plus every non-data combination.
`full()` is everything (`-m bank_full`)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

from tests.unit.analytics_agent.bank import dimensions as D

#: the seller's text of a generated case: no word any code regex reads (the parse is given)
NEUTRAL_Q = "Hỏi Juli"
WRITER = "Đang tìm hiểu: câu hỏi.\nKỳ này chưa đủ số liệu để kết luận."
WHY_CHAIN = {  # the analysis that explains a metric (routing.CHAINS descriptions)
    "gmv": "gmv_change",
    "aov": "gmv_change",
    "orders": "orders_change",
    "units": "orders_change",
    "views": "ctr_change",
    "clicks": "ctr_change",
    "ctr": "ctr_change",
    "ctor": "ctor_change",
    "profit": "profit_change",
    "margin": "profit_change",
    "ads_spend": "ads_change",
    "roas": "ads_change",
    "roas_break_even": "ads_change",
    "cost_ratio": "cost_change",
}
#: Tổng quan's key for a Chat metric (shop_metrics); roas_break_even is the profit block's
OVERVIEW_KEY = {
    "gmv": "overview.gmv",
    "orders": "overview.orders",
    "aov": "overview.aov",
    "units": "overview.units",
    "views": "overview.views",
    "clicks": "overview.clicks",
    "ctr": "overview.ctr",
    "ctor": "overview.ctor",
    "profit": "overview.profit",
    "margin": "overview.margin_pct",
    "ads_spend": "overview.ad_spend",
    "roas": "overview.ads_roas_placed",
    "roas_break_even": "overview_profit.break_even_roas",
}
TREND_METRICS = (*D.COUNTS, "aov", "ctr", "ctor")
#: what each entity answers (the validity table): the registry key -> the entity's figure
VOUCHER_FIG = {"orders": "orders", "gmv": "gmv", "aov": "aov", "cost_offer_voucher": "cost"}
AFFILIATE_FIG = {"orders": "orders", "gmv": "gmv", "aov": "aov"}
AFFILIATE_COST = ("cost_affiliate", "kol_commission")
PROGRAMME_PART = {"combo": "offer_combo"}  # the other programmes are Ưu đãi's promo part
PROGRAMME_COST = ("cost_offer_combo", "cost_offer_promo", "cost_offers")
NO_FIGURE = ["needs_choice", "unsupported", "data_missing"]
#: the seeded shop's ads campaign report period (tests/support/shopee_analytics CUR_START..END)
CAMPAIGN_DAYS = ("2026-10-01", "2026-10-07")


def _overlaps(w: tuple[str, str] | None, days: tuple[str, str]) -> bool:
    return w is not None and w[0] <= days[1] and days[0] <= w[1]


NO_DATA_VI = "Juli chưa có số liệu này"
PERIOD = {p.id: p for p in D.PERIODS}
SCOPE = {s.id: s for s in D.SCOPES}


def _ddmm(a: str, b: str) -> str:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    return f"{da:%d/%m}" if da == db else f"{da:%d/%m}–{db:%d/%m}"


def _intent_base(p: D.Period, s: D.Scope) -> dict[str, Any]:
    return {**p.intent, **s.intent}


# ------------------------------------------------------------------ the data family


def data_case(pid: str, sid: str, m: str, o: str) -> dict[str, Any]:
    p, s = PERIOD[pid], SCOPE[sid]
    a = D.AGENT_OF.get(m)
    it = _intent_base(p, s)
    it.update(
        question_type="why_changed" if o == "why" else "status",
        metric_key=m,
        metric_phrase=D.phrase_of(m),
        claimed_direction="down" if o in ("why", "decline") else "none",
        ranking={"top": "top", "decline": "decline"}.get(o, "none"),
    )
    if o == "verdict":
        it["metric_phrase"] = f"{D.phrase_of(m) or 'which'} losing money after ads"
        if s.kind == "shop":
            it["metric_phrase"] = "which products are losing money after ads"
    if o == "breakdown":
        it["metric_phrase"] = f"{D.phrase_of(m) or 'numbers'} by channel"
    if o == "trend":
        it["metric_phrase"] = f"{D.phrase_of(m) or 'numbers'} per day"
    entity = s.kind in ("voucher", "affiliate", "campaign", "programme")
    named = a is not None
    jev: dict[str, Any] = {
        "fits": 0.95 if (named or entity or o in ("top", "decline")) else 0.5,
        "mode": "why" if o == "why" else "lookup",
        "lookup": D.LOOKUP_OF[o],
        "metric": a or [["gmv", 0.4], ["orders", 0.35]],
        "metric_named": 0.95 if named else (0.9 if m != "none" else 0.1),
        "window": p.preset or [["last_7d_vs_prev_7d", 0.45], ["last_30d_vs_prev_30d", 0.4]],
        "scope": "product" if s.kind == "product" else "shop",
        "product_named": 0.95 if s.kind == "product" else 0.05,
    }
    if a in WHY_CHAIN:
        jev["chain"] = WHY_CHAIN[a]
    return {
        "id": f"data.{pid}.{sid}.{m}.{o}",
        "family": "data",
        "dims": {"period": pid, "scope": sid, "metric": m, "output": o},
        "question": NEUTRAL_Q,
        "intents": [it],
        "jev": jev,
        "writer": WRITER,
        "expect": data_expect(p, s, m, o),
    }


def _window_ok(p: D.Period) -> dict[str, Any]:
    return {"window": _ddmm(*p.cur)} if p.cur else {}


def _screen(key: str, p: D.Period) -> dict[str, Any]:
    assert p.cur
    return {"screen": key, "from": p.cur[0], "to": p.cur[1]}


def data_expect(p: D.Period, s: D.Scope, m: str, o: str) -> dict[str, Any]:
    """The oracle: what a correct Chat answers for one combination. Rules in order; the first
    that matches decides."""
    a = D.AGENT_OF.get(m)
    honest = {"stop_in": NO_FIGURE, "no_events": ["data_answer"], "no_numbers": True}
    # R1: a period Chat has no window for -> it asks which period (never a guessed window)
    if p.preset is None and p.id not in D.EXPLICIT:
        return {**honest, "needs_choice_item": "window", "stop_in": ["needs_choice"]}
    # R2: a month that has not begun has no figure
    if p.cur is None:
        return honest
    if s.kind == "shop":
        return _shop_expect(p, m, a, o)
    if s.kind == "product":
        return _product_expect(p, s, m, a, o)
    if s.kind == "voucher":
        return _voucher_expect(p, m, o)
    if s.kind == "affiliate":
        return _affiliate_expect(p, m, o)
    if s.kind == "campaign":
        if not _overlaps(p.cur, CAMPAIGN_DAYS):  # the ads report covers 01/10-07/10 only
            return {"stop": ["data_missing"], "require": [NO_DATA_VI], "no_numbers": True}
        if o in ("value", "comparison", "verdict"):
            return {
                "stop": ["data_answer"],
                "answers": [
                    {**_window_ok(p), "kind": "top_products", "rows_have": ["Chiến dịch nhóm"]}
                ],
            }
        return _entity_other_output(p, o)
    if s.kind == "programme":
        if m in PROGRAMME_COST and o in ("value", "comparison"):
            part = PROGRAMME_PART.get(s.id, "offer_promo")
            return {"stop": ["data_answer"], "answers": [_screen(f"offer.{part}", p)]}
        return {**honest, "require": [NO_DATA_VI], "stop_in": ["data_missing"]}
    # channel / ad type: the channel's own figure, under its own name
    if a is None or o not in ("value", "comparison"):
        return honest
    return {"stop": ["data_answer"], "answers": [{**_window_ok(p), "title_has": _CHANNEL[s.id]}]}


_CHANNEL = {
    "channel_organic": "Organic",
    "channel_ads": "Quảng cáo",
    "dvht_product": "Dịch vụ hiển thị Sản phẩm",
    "dvht_shop": "Dịch vụ hiển thị Shop+",
    "ads_live": "Livestream",
    "ads_other": "Khác",
}


def _shop_expect(p: D.Period, m: str, a: str | None, o: str) -> dict[str, Any]:
    honest = {"stop_in": NO_FIGURE, "no_events": ["data_answer"], "no_numbers": True}
    if o in ("top", "decline"):  # a ranking needs no metric: GMV (routing.decide)
        title = "Sản phẩm giảm mạnh nhất (GMV)" if o == "decline" else "Top sản phẩm theo GMV"
        ans: dict[str, Any] = {**_window_ok(p), "kind": "top_products"}
        if m in ("gmv", "none"):
            ans["title_vi"] = title
            if o == "top":
                ans.update(_screen("metric_view.gmv", p))
        else:  # ranked by the metric asked
            ans["title_has"] = (a or m).replace("_", " ")
        return {"stop": ["data_answer"], "answers": [ans]}
    if o == "verdict":  # the products losing after ads (or 'no data' on a day without lines)
        return {"stop_in": ["data_answer", "data_missing"], "no_events": ["unsupported", "error"]}
    if a is None:  # a metric Chat does not have (or none named): ask, never another figure
        return honest
    if o == "why":
        return {
            "routes": [{"outcome": "go", "mode": "why", "chain": WHY_CHAIN[a]}],
            "no_events": ["unsupported", "error"],
        }
    if a == "cost_ratio":  # Tổng chi phí / doanh thu thực: Kênh's ratio
        return {"stop": ["data_answer"], "no_events": ["error"]}
    if o == "breakdown":
        if a not in D.MV_METRICS:
            return {**honest, "stop_in": NO_FIGURE}
        return {
            "stop": ["data_answer"],
            "answers": [
                {
                    **_window_ok(p),
                    "kind": "channel_breakdown",
                    **_screen(f"metric_view_channels.{a}", p),
                }
            ],
        }
    if o == "trend":
        ans = {**_window_ok(p), "kind": "daily_trend"}
        if a in TREND_METRICS or a in OVERVIEW_KEY:
            ans.update(_screen(f"daily.{OVERVIEW_KEY[a]}", p))
        return {"stop": ["data_answer"], "answers": [ans]}
    ans = {**_window_ok(p), "kind": "metric_total", **_screen(OVERVIEW_KEY[a], p)}
    if a in ("profit", "margin"):
        ans["missing_as"] = "—"
    if o == "comparison" and p.prev:
        ans.update(before_screen=OVERVIEW_KEY[a], prev_from=p.prev[0], prev_to=p.prev[1])
    out: dict[str, Any] = {"stop": ["data_answer"], "answers": [ans]}
    if p.sale:
        out["require"] = ["Ngày sale:"]
    return out


def _product_expect(p: D.Period, s: D.Scope, m: str, a: str | None, o: str) -> dict[str, Any]:
    honest = {"stop_in": NO_FIGURE, "no_events": ["data_answer"], "no_numbers": True}
    if o in ("top", "decline"):  # a ranking ranks the shop's products (the scope is the list)
        return {"stop": ["data_answer"], "answers": [{**_window_ok(p), "kind": "top_products"}]}
    if o == "verdict":  # lãi / lỗ of the one product after ads
        return {
            "stop": ["data_answer"],
            "answers": [
                {
                    **_window_ok(p),
                    "screen": f"product.{s.item}.profit",
                    "from": p.cur[0],
                    "to": p.cur[1],
                }
            ],
        }
    if a is None:
        return honest
    if o == "why":
        return {"routes": [{"outcome": "go", "mode": "why"}], "no_events": ["unsupported", "error"]}
    if o == "breakdown":
        if a not in D.MV_METRICS:
            return {**honest}
        return {
            "stop": ["data_answer"],
            "answers": [
                {
                    **_window_ok(p),
                    "kind": "channel_breakdown",
                    **_screen(f"metric_view_channels.{a}@{s.item}", p),
                }
            ],
        }
    if o == "trend":
        return {"stop": ["data_answer"], "answers": [{**_window_ok(p), "kind": "daily_trend"}]}
    if a in ("profit", "margin", "roas_break_even"):
        key = {"profit": "profit", "margin": "margin_pct", "roas_break_even": "break_even"}[a]
        ans = {**_window_ok(p), **_screen(f"product.{s.item}.{key}", p)}
    elif a in D.MV_METRICS:
        ans = {
            **_window_ok(p),
            "kind": "metric_total",
            **_screen(f"metric_view_total.{a}@{s.item}", p),
        }
    elif a == "ads_spend":  # the product's own ad cost (ProductProfit.ad_spend)
        ans = {**_window_ok(p), **_screen(f"product.{s.item}.ads_spend", p)}
    else:  # units / clicks of one product: the value, no product screen holds it
        ans = {**_window_ok(p), "kind": "metric_total"}
    return {"stop": ["data_answer"], "answers": [ans], "answers_optional": "screen" in ans}


def _entity_other_output(p: D.Period, o: str) -> dict[str, Any]:
    """A ranking / split / trend / why of an entity: not built for any entity -> ask or say so,
    never the entity's total under another question (and never the shop's ranking)."""
    return {"stop_in": NO_FIGURE + ["data_answer"], "no_events": ["data_answer"]}


def _voucher_expect(p: D.Period, m: str, o: str) -> dict[str, Any]:
    if o not in ("value", "comparison"):
        return _entity_other_output(p, o)
    if m == "none":  # no figure named: the three voucher figures (entities._voucher_answers)
        return {
            "stop": ["data_answer"],
            "answers": [
                {**_window_ok(p), "title_has": "Đơn dùng voucher", **_screen("voucher.orders", p)},
                {**_window_ok(p), "title_has": "GMV đơn dùng voucher", **_screen("voucher.gmv", p)},
            ],
            "answers_optional": True,
        }
    fig = VOUCHER_FIG.get(m)
    if fig is None:
        return {
            "stop_in": ["data_missing", "needs_choice"],
            "no_events": ["data_answer"],
            "no_numbers": True,
        }
    ans = {**_window_ok(p), **_screen(f"voucher.{fig}", p)}
    if o == "comparison" and p.prev:
        ans.update(before_screen=f"voucher.{fig}", prev_from=p.prev[0], prev_to=p.prev[1])
    return {"stop": ["data_answer"], "answers": [ans], "answers_optional": True}


def _affiliate_expect(p: D.Period, m: str, o: str) -> dict[str, Any]:
    if o not in ("value", "comparison"):
        return _entity_other_output(p, o)
    if m in AFFILIATE_COST:  # the shop has no commission rows: missing, never 0
        return {"stop": ["data_missing"], "require": [NO_DATA_VI], "no_numbers": True}
    fig = AFFILIATE_FIG.get(m, "orders" if m == "none" else None)
    if fig is None:
        return {
            "stop_in": ["data_missing", "needs_choice"],
            "no_events": ["data_answer"],
            "no_numbers": True,
        }
    screen = "kol.aov" if fig == "aov" else f"kol.{fig}"
    return {"stop": ["data_answer"], "answers": [{**_window_ok(p), **_screen(screen, p)}]}


def data_family() -> Iterator[dict[str, Any]]:
    for p in D.PERIODS:
        for s in D.SCOPES:
            for m in D.metric_ids():
                for o in D.OUTPUTS:
                    yield data_case(p.id, s.id, m, o)


def data_count() -> int:
    return len(D.PERIODS) * len(D.SCOPES) * len(D.metric_ids()) * len(D.OUTPUTS)


# ------------------------------------------------------------------ the other families


def create_family() -> Iterator[dict[str, Any]]:
    for ct in D.CARD_TYPES:
        for prod in (False, True):
            for dates in (False, True):
                for amount in (False, True):
                    card: dict[str, Any] = {"card_type": ct}
                    if dates:
                        card.update(from_date="2026-10-10", to_date="2026-10-12", start_hour=12)
                    if amount:
                        card.update(
                            amount=10,
                            amount_unit="pct",
                            min_spend=100_000,
                            quantity=20,
                            name="SYN thẻ",
                        )
                    it: dict[str, Any] = {"question_type": "create_card", "card": card}
                    if prod:
                        it["product_phrase"] = "găng tay"
                    need = set(D.REQUIRED[ct])
                    have = (
                        ({"product"} if prod else set())
                        | ({"from_date", "to_date", "start_hour"} if dates else set())
                        | ({"amount", "min_spend", "quantity", "name"} if amount else set())
                    )
                    missing = need - have
                    exp: dict[str, Any] = {
                        "routes": [{"outcome": "go", "mode": "create", "card_type": ct}],
                        "no_events": ["unsupported", "error"],
                    }
                    if missing:  # a required slot is asked (create_card.REQUIRED), one at a time
                        exp["stop"] = ["needs_choice"]
                    else:  # all slots given: a draft card, or the engine's stated reason
                        exp["stop_in"] = ["data_answer"]
                        exp["events_any"] = ["card", "no_card", "label"]
                    yield {
                        "id": f"create.{ct}.p{int(prod)}d{int(dates)}a{int(amount)}",
                        "family": "create",
                        "dims": {
                            "card_type": ct,
                            "product": prod,
                            "dates": dates,
                            "amount": amount,
                        },
                        "question": f"Tạo thẻ ({ct})".replace("_", " "),
                        "intents": [it],
                        "jev": None,
                        "expect": exp,
                    }


def _tool_args(tool: str, kind: str | None) -> dict[str, Any]:
    if tool == "metric_view":
        return {"metric": "gmv", "window": "last_7d_vs_prev_7d"}
    if tool == "product_profit":
        return {"window": "last_7d_vs_prev_7d"}
    if tool == "draft_card":
        return {"kind": kind, "item": "1001"}
    return {}


def advise_family() -> Iterator[dict[str, Any]]:
    steps = [(t, None) for t in D.ADVISOR_TOOLS if t != "draft_card"] + [
        ("draft_card", k) for k in D.DRAFT_KINDS
    ]
    for goal in D.GOALS:
        for trigger in ("plan", "needs_advice"):
            for tool, kind in steps:
                it = {
                    "question_type": "plan" if trigger == "plan" else "status",
                    "needs_advice": trigger == "needs_advice",
                    "goal": goal,
                }
                lead = "Tuần trước shop bán ổn định, chưa có thay đổi lớn."
                script = [
                    [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": tool,
                            "input": _tool_args(tool, kind),
                        }
                    ],
                    [
                        {
                            "type": "tool_use",
                            "id": "p1",
                            "name": "emit_plan",
                            "input": {"lead": lead, "actions": []},
                        }
                    ],
                ]
                yield {
                    "id": f"advise.{goal}.{trigger}.{tool}" + (f".{kind}" if kind else ""),
                    "family": "advise",
                    "dims": {
                        "goal": goal,
                        "trigger": trigger,
                        "advisor_tool": tool,
                        "draft_kind": kind,
                    },
                    "question": "Tuần tới shop nên làm gì?",
                    "intents": [it],
                    "jev": None,
                    "agent_script": script,
                    "expect": {
                        "routes": [{"outcome": "go", "mode": "advise", "goal": goal}],
                        "stop": ["data_answer"],
                        "require": [lead],
                        "no_events": ["unsupported", "error"],
                        "max_jev_calls": 0 if tool != "draft_card" else 99,
                    },
                }


def small_families() -> Iterator[dict[str, Any]]:
    for goal in D.GOALS:  # "phân tích": the advisor unavailable -> the weekly analysis (code)
        yield {
            "id": f"analysis.{goal}",
            "family": "analysis",
            "dims": {"goal": goal},
            "question": "Phân tích tuần vừa rồi",
            "jev": None,
            "intents": [{"question_type": "plan", "needs_advice": True, "goal": goal}],
            "expect": {
                "stop": ["data_answer"],
                "events": ["data_answer"],
                "no_events": ["unsupported", "error"],
            },
        }
    card = "P1 · 8k / 179k Lợi nhuận đóng góp dự kiến (3 ngày): +8k hiện tại: 179k"
    for cid, q in (
        ("pasted", card),
        ("pasted_why", card + " giải thích cách tính"),
        ("by_code", "Thẻ JC-2610-0001 tính thế nào?"),
    ):
        yield {
            "id": f"explain.{cid}",
            "family": "explain",
            "dims": {"explain": cid},
            "question": q,
            "jev": {"fits": 0.4},
            "intents": [
                {"question_type": "other", "metric_phrase": "how a card's figures are computed"}
            ],
            "expect": {"stop": ["data_answer"], "no_events": ["unsupported"]},
        }
    for m in D.metric_ids():  # outside Chat's data: unsupported, the offer names the metric
        yield {
            "id": f"unsupported.{m}",
            "family": "unsupported",
            "dims": {"metric": m},
            "question": "Câu hỏi ngoài dữ liệu shop",
            "jev": {"fits": 0.1, "metric_named": 0.1},
            "intents": [
                {"question_type": "other", "metric_key": m, "metric_phrase": D.phrase_of(m)}
            ],
            "expect": {
                "stop": ["unsupported"],
                "events": ["unsupported"],
                "no_events": ["data_answer"],
                "no_numbers": True,
            },
        }
    amb = {  # legitimately ambiguous -> needs_choice on the right item
        "chain": (
            {"question_type": "why_changed", "metric_phrase": None},
            {"fits": 0.5, "metric_named": 0.1, "mode": "why"},
        ),
        "window": (
            {"metric_key": "gmv", "metric_phrase": "gmv"},
            {
                "metric": "gmv",
                "window": [["last_7d_vs_prev_7d", 0.45], ["last_30d_vs_prev_30d", 0.4]],
            },
        ),
        "metric": (
            {"metric_phrase": "numbers", "time_phrase": "last week"},
            {"fits": 0.75, "metric_named": 0.1, "window": "last_full_week_vs_week_before"},
        ),
        "product": (
            {
                "metric_key": "gmv",
                "metric_phrase": "gmv",
                "time_phrase": "last 7 days",
                "product_phrase": "tự hủy",
            },
            {"metric": "gmv", "scope": "product", "product_named": 0.95},
        ),
    }
    for item, (it, jev) in amb.items():
        for p in ("none", "7d") if item != "window" else ("none",):
            per = {**it, **(PERIOD[p].intent if item not in ("window", "product") else {})}
            yield {
                "id": f"ambiguous.{item}.{p}",
                "family": "ambiguous",
                "dims": {"ask": item},
                "question": "Câu hỏi chưa rõ",
                "jev": jev,
                "intents": [per],
                "jev_product": {"pick": [["1001", 0.5], ["1003", 0.5]]},
                "expect": {
                    "stop": ["needs_choice"],
                    "needs_choice_item": item,
                    "no_events": ["data_answer"],
                },
            }
    for t in D.TEMPLATE_KEYS:
        for down in (False, True):
            yield {
                "id": f"template.{t}.{'down' if down else 'up'}",
                "family": "template",
                "dims": {"template": t, "router": "down" if down else "up"},
                "question": f"[template {t}]",
                "template": t,
                "jev_down": down,
                "writer": WRITER,
                "expect": {"no_events": ["unsupported", "error"]},
            }
    mix = {
        "lookup": [
            {"metric_key": k, "metric_phrase": k, "time_phrase": "last week"}
            for k in ("gmv", "orders", "aov", "views", "ctr")
        ],
        "entity": [
            {"metric_key": "orders", "metric_phrase": "orders", "time_phrase": "last week", **e}
            for e in (
                {"entity_phrase": "voucher"},
                {"source_phrase": "Tiếp thị liên kết"},
                {"entity_phrase": "voucher", "metric_key": "gmv", "metric_phrase": "gmv"},
                {"entity_phrase": "ad campaign"},
                {"entity_phrase": "KOL"},
            )
        ],
        "ranking": [
            {"metric_phrase": "products", "time_phrase": "last week", "ranking": r}
            for r in ("top", "decline", "top", "decline", "top")
        ],
        "mixed": [
            {"metric_key": "gmv", "metric_phrase": "gmv", "time_phrase": "last week"},
            {"metric_phrase": "products", "time_phrase": "last week", "ranking": "top"},
            {
                "metric_key": "orders",
                "metric_phrase": "orders",
                "time_phrase": "last week",
                "entity_phrase": "voucher",
            },
            {"metric_key": "ctr", "metric_phrase": "ctr", "time_phrase": "last week"},
            {"metric_key": "roas", "metric_phrase": "roas", "time_phrase": "last week"},
        ],
    }
    for kind, its in mix.items():
        for n in D.INTENT_COUNTS:
            shown = min(n, 3)
            exp: dict[str, Any] = {
                "stop": ["data_answer"] * shown,
                "n_answers_min": shown,
                "no_events": ["unsupported", "error"],
                "more_items": max(0, n - 3),
            }
            if n > 1:
                exp["n_intent_blocks"] = shown
            jevs = [
                {"metric": i.get("metric_key", "gmv"), "window": "last_full_week_vs_week_before"}
                for i in its[:n]
            ]
            yield {
                "id": f"intents.{kind}.{n}",
                "family": "intents",
                "dims": {"intents": n, "mix": kind},
                "question": "Nhiều câu hỏi trong một tin",
                "intents": its[:n],
                "jev": jevs,
                "expect": exp,
            }


def other_families() -> list[dict[str, Any]]:
    return [*create_family(), *advise_family(), *small_families(), *mismatch_family()]


# ------------------------------------------------------------------ the covering array


def covering_rows() -> list[tuple[str, str, str, str]]:
    """Every period x metric x scope triple once, the output chosen greedily so every pair of
    values of every two data dimensions is covered too. Deterministic."""
    periods = [p.id for p in D.PERIODS]
    scopes = [s.id for s in D.SCOPES]
    metrics = list(D.metric_ids())
    outputs = list(D.OUTPUTS)
    seen: set[tuple[str, str, str, str]] = set()  # (dim_a, val_a, dim_b, val_b) pairs
    rows: list[tuple[str, str, str, str]] = []

    def pairs(row: tuple[str, str, str, str]) -> list[tuple[str, str, str, str]]:
        names = ("p", "s", "m", "o")
        return [(names[i], row[i], names[j], row[j]) for i in range(4) for j in range(i + 1, 4)]

    k = 0
    for p in periods:
        for m in metrics:
            for s in scopes:
                best, gain = None, -1
                for i in range(len(outputs)):
                    o = outputs[(k + i) % len(outputs)]
                    g = sum(1 for x in pairs((p, s, m, o)) if x not in seen)
                    if g > gain:
                        best, gain = o, g
                k += 1
                row = (p, s, m, best or outputs[0])
                seen.update(pairs(row))
                rows.append(row)
    # any pair still missing (an output with a period / scope / metric) gets its own row
    for o in outputs:
        for p in periods:
            if ("p", p, "o", o) not in seen:
                rows.append((p, scopes[0], metrics[0], o))
                seen.update(pairs(rows[-1]))
        for s in scopes:
            if ("s", s, "o", o) not in seen:
                rows.append((periods[0], s, metrics[0], o))
                seen.update(pairs(rows[-1]))
        for m in metrics:
            if ("m", m, "o", o) not in seen:
                rows.append((periods[0], scopes[0], m, o))
                seen.update(pairs(rows[-1]))
    return rows


def gate() -> list[dict[str, Any]]:
    return [data_case(*r) for r in covering_rows()] + other_families()


def full() -> Iterator[dict[str, Any]]:
    yield from data_family()
    yield from other_families()


# ------------------------------------------------------------------ the known gaps


@dataclass(frozen=True)
class GapRule:
    """One known gap: which combinations it covers (`applies`) and which problems it explains
    (regexes over the check's problem lines). A problem no applying rule explains fails hard;
    a rule that applies but explains nothing fails too (strict: the fix forces the rule off)."""

    name: str
    reason: str
    applies: Callable[[dict[str, Any]], bool]
    explains: tuple[str, ...]
    pending: bool = False

    def matches(self, problem: str) -> bool:
        return any(re.search(rx, problem) for rx in self.explains)


def _d(c: dict[str, Any]) -> dict[str, Any]:
    return c.get("dims") or {}


def _is(c: dict[str, Any], family: str) -> bool:
    return c.get("family") == family


ANY = (r".",)
CRASH = r"raised|unexpected error event|stop \[.*'error'"


def _nb(m: str) -> bool:
    return m != "none" and m not in D.AGENT_OF


def _phrase_hit(m: str) -> bool:
    """The parser's words for a key Chat lacks hit `routing.METRIC_WORDS` (the safety net)."""
    from juli_backend.services.analytics_agent.routing import metric_from_phrase

    return _nb(m) and metric_from_phrase(D.phrase_of(m)) is not None


def _dd(c: dict[str, Any], *keys: str) -> tuple[Any, ...]:
    d = _d(c)
    return tuple(d.get(k) for k in keys)


def _kind(c: dict[str, Any]) -> str | None:
    sid = _d(c).get("scope")
    return SCOPE[sid].kind if sid in SCOPE else None


def _data(c: dict[str, Any], pred: Callable[[str, str, str, str], bool]) -> bool:
    if not _is(c, "data"):
        return False
    p, s, m, o = _dd(c, "period", "scope", "metric", "output")
    return pred(p, s, m, o)


def _resolved(m: str) -> str | None:
    """The metric Chat ends up answering for a key: its own, else the phrase safety net's."""
    from juli_backend.services.analytics_agent.routing import metric_from_phrase

    return D.AGENT_OF.get(m) or (metric_from_phrase(D.phrase_of(m)) if m != "none" else None)


ENTITY = ("voucher", "affiliate", "campaign")
FIGURE = ("value", "comparison")


def _entity_fig(s: str, m: str) -> bool:
    k = SCOPE[s].kind
    if k == "voucher":
        return m in VOUCHER_FIG or m == "none"
    if k == "affiliate":
        return m in AFFILIATE_FIG or m in AFFILIATE_COST or m == "none"
    return k == "campaign"


def R(
    name: str,
    reason: str,
    pred: Callable[[str, str, str, str], bool],
    explains: tuple[str, ...] = ANY,
    pending: bool = False,
) -> GapRule:
    return GapRule(name, reason, lambda c: _data(c, pred), explains, pending)


GAP_RULES: tuple[GapRule, ...] = (
    R(
        "not_started_month",
        "a month that has not begun (tháng 11 asked on 07/10) runs an inverted "
        "window: October's figures, or InvalidWindow from the tabs' service",
        lambda p, s, m, o: p == "named_not_started",
        (*ANY, CRASH),
    ),
    R(
        "no_window_ask",
        "a period with no preset (14 / 90 ngày) is not asked on the entity, "
        "ranking and programme paths: decide() takes the router's top window without the ratio "
        "check, or the programme refusal comes first",
        lambda p, s, m, o: p in ("14d", "90d"),
    ),
    R(
        "phrase_safety_net",
        "a registry metric Chat lacks is read through routing.METRIC_WORDS "
        "('net revenue' -> GMV, 'gross profit' -> profit, 'roas direct' -> ROAS ...): another "
        "metric's figure answers the asked one",
        lambda p, s, m, o: _phrase_hit(m),
    ),
    R(
        "channel_filter",
        "no channel / ad-type filter (Organic, Quảng cáo, DVHT Sản phẩm, DVHT "
        "Shop+): the shop's figure or the shop's analysis answers under the channel",
        lambda p, s, m, o: (
            SCOPE[s].kind in ("channel", "ad_type") and s not in ("ads_live", "ads_other")
        ),
    ),
    R(
        "ads_live_other_tag2",
        "Livestream / Khác ads arrive with tag 2",
        lambda p, s, m, o: s in ("ads_live", "ads_other"),
        pending=True,
    ),
    R(
        "entity_ignores_metric",
        "a voucher / affiliate / campaign question on a metric the entity "
        "has no figure for gets the entity's default figures (any cost word = the entity's own "
        "cost; no metric = đơn / all voucher figures; a campaign = its table)",
        lambda p, s, m, o: SCOPE[s].kind in ENTITY and not _entity_fig(s, m),
    ),
    R(
        "entity_ignores_output",
        "a ranking / split / daily trend / why / verdict of a voucher, "
        "affiliate or campaign answers the entity's total (or the campaign table)",
        lambda p, s, m, o: (
            SCOPE[s].kind in ENTITY
            and o not in FIGURE
            and not (SCOPE[s].kind == "campaign" and o == "verdict")
        ),
    ),
    R(
        "ranking_ignores_scope",
        "a ranking named with a product, a programme or an entity ranks the "
        "shop's products, or answers the scope's total instead of a list",
        lambda p, s, m, o: o in ("top", "decline") and SCOPE[s].kind != "shop",
    ),
    R(
        "ranking_by_gmv_only",
        "a ranking by any metric other than GMV is ranked by GMV ('Top sản phẩm theo GMV')",
        lambda p, s, m, o: o in ("top", "decline") and m not in ("gmv", "none"),
    ),
    R(
        "product_verdict",
        "lãi / lỗ of one named product is not built: the product's metric or a "
        "question back instead of its profit after ads",
        lambda p, s, m, o: SCOPE[s].kind == "product" and o == "verdict",
    ),
    R(
        "product_ads",
        "one product's ad spend / ROAS: 'Juli chưa có số liệu này' although "
        "ProductProfit holds the product's ad cost",
        lambda p, s, m, o: SCOPE[s].kind == "product" and _resolved(m) in ("ads_spend", "roas"),
    ),
    R(
        "breakdown_metric_crash",
        "a channel split of a metric metric_view does not hold (units, "
        "clicks, profit, ads, ROAS ...) raises ValueError from metric_view",
        lambda p, s, m, o: o == "breakdown" and (_resolved(m) or "gmv") not in D.MV_METRICS,
        (*ANY, CRASH),
    ),
    R(
        "cost_ratio_crash",
        "a cost_ratio lookup raises KeyError('cost_ratio') in lookup._total",
        lambda p, s, m, o: _resolved(m) == "cost_ratio",
        (*ANY, CRASH),
    ),
    R(
        "profit_dash",
        "profit / margin below 70 % known shows 'chưa có dữ liệu' where Tổng quan shows '—'",
        lambda p, s, m, o: _resolved(m) in ("profit", "margin"),
        (r"missing shown",),
    ),
    R(
        "affiliate_flow",
        "Chat's affiliate đơn / GMV are order lines flagged affiliate; Tổng quan "
        "and the KOL cell show the Tiếp thị liên kết flow",
        lambda p, s, m, o: SCOPE[s].kind == "affiliate" and o in FIGURE,
        (r"kol\.", r"answer\[\d\] missing", r"stop "),
    ),
    R(
        "baseline_shift",
        "the sale-aware baseline moves the comparison window to one without rows "
        "or other days than the window before",
        lambda p, s, m, o: o == "comparison",
        (r"before: chat",),
    ),
    R(
        "this_vs_last_week",
        "'this week compared with last week' runs last week (window_from_phrase order)",
        lambda p, s, m, o: p == "this_vs_last_week",
        (r"window '", r"chat .* != screen", r"GMV .* != screen", r"points for"),
    ),
    R(
        "entity_word_in_metric",
        "a metric whose words name an entity (voucher, KOL, affiliate, "
        "campaign) is answered by that entity's reader, whatever the asked scope",
        lambda p, s, m, o: _entity_word(m),
    ),
    R(
        "programme_figures",
        "programme figures have no reader (entity 'program' -> 'Juli chưa có "
        "số liệu này') while Ưu đãi holds the combo / promo part",
        lambda p, s, m, o: SCOPE[s].kind == "programme" and m in PROGRAMME_COST and o in FIGURE,
    ),
    R(
        "trend_vs_screen",
        "the daily trend reads shop_metrics_daily: one point per stored day only, "
        "clicks are the product-click column (Tổng quan: the source funnel) and money metrics have "
        "no daily point",
        lambda p, s, m, o: o == "trend" and SCOPE[s].kind == "shop",
        (r"\d\d/\d\d: chat", r"points for"),
    ),
    R(
        "product_traffic",
        "one product's views / CTR / CTOR come from the product's source rows; "
        "a product with none shows 'chưa có dữ liệu' while Phân tích has the product's funnel",
        lambda p, s, m, o: (
            SCOPE[s].kind == "product" and _resolved(m) in ("views", "ctr", "ctor") and o in FIGURE
        ),
        (r"metric_view_total",),
    ),
    R(
        "voucher_sale_day",
        "on the sale day alone (25/09) the voucher reader finds no voucher "
        "window and says 'Juli chưa có số liệu này' while the Phân tích voucher cell has orders",
        lambda p, s, m, o: SCOPE[s].kind == "voucher" and p == "sale_day",
        (r"Chat has no figure", r"stop "),
    ),
    R(
        "why_card_estimate_word",
        "the why chain's card note on one product says 'Juli chưa ước tính được…' (a forbidden "
        "word on a screen)",
        lambda p, s, m, o: o == "why" and SCOPE[s].kind == "product",
        (r"ước tính",),
    ),
    R(
        "top_list_vs_screen",
        "the top-products list ranks every product with a row in the window (a product with no "
        "sale included) while Phân tích lists only the products that sold",
        lambda p, s, m, o: o == "top" and SCOPE[s].kind == "shop",
        (r"order \[",),
    ),
    R(
        "product_money_output",
        "a product's profit / margin / ROAS hoà vốn answers its total "
        "whatever the output asked (split, trend)",
        lambda p, s, m, o: (
            SCOPE[s].kind == "product"
            and o not in FIGURE
            and _resolved(m) in ("profit", "margin", "roas_break_even", "ads_spend", "roas")
        ),
    ),
)


def _rule(
    name: str, reason: str, pred: Callable[[dict[str, Any]], bool], explains: tuple[str, ...] = ANY
) -> GapRule:
    return GapRule(name, reason, pred, explains)


GAP_RULES = GAP_RULES + (
    _rule(
        "create_estimate_word",
        "a card kind the engine cannot estimate says 'Juli chưa ước "
        "tính được…' (a forbidden word on a screen)",
        lambda c: (
            _is(c, "create") and _d(c)["card_type"] in ("combo", "add_on", "gift", "variation_set")
        ),
        (r"ước tính", r"internal keys"),
    ),
    _rule(
        "create_discount_error",
        "a product discount with every slot given fails with the "
        "card model's validation text ('Value error, discount_pct …') shown to the seller",
        lambda c: _is(c, "create") and _d(c)["card_type"] == "product_discount",
        (r"internal keys", r"none of"),
    ),
    _rule(
        "card_explain",
        "no card-explain path: a pasted card or a card code is unsupported",
        lambda c: _is(c, "explain"),
    ),
    _rule(
        "template_needs_router",
        "the margin / cost templates' card stage asks Jev, so with the "
        "router down the run raises JevUnavailable (prod: router_unavailable)",
        lambda c: (
            _is(c, "template")
            and _d(c)["router"] == "down"
            and _d(c)["template"] in ("improve_margin", "reduce_cost")
        ),
        (*ANY, CRASH),
    ),
)


def _entity_word(m: str) -> bool:
    from juli_backend.services.analytics_agent.routing import entity_kind

    return m != "none" and entity_kind({"metric_phrase": D.phrase_of(m)}) is not None


# ------------------------------------------------------------------ mismatches (owner, 26/11)

#: (a) a scope that cannot be measured on the asked metric: (label, scope slots, metric keys)
SCOPE_MISMATCH: tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...] = (
    (
        "dvht_shop_per_product",
        {"source_phrase": "Dịch vụ hiển thị Shop+", "product_phrase": "găng tay"},
        ("cost_ads", "roas", "ctr_ads"),
    ),
    (
        "stock_for_campaign",
        {"entity_phrase": "ad campaign"},
        ("days_left", "runs_out_on", "units_per_day", "restock_units"),
    ),
    (
        "roas_for_organic",
        {"source_phrase": "Organic"},
        ("roas", "roas_direct", "roas_break_even", "cost_ads", "ctr_ads"),
    ),
    (
        "voucher_traffic",
        {"entity_phrase": "voucher"},
        ("views", "clicks", "ctr", "ctor", "days_left", "roas"),
    ),
    (
        "affiliate_ads",
        {"source_phrase": "Tiếp thị liên kết"},
        ("cost_ads", "roas", "ctr_ads", "ctor_ads", "days_left"),
    ),
    ("combo_traffic", {"entity_phrase": "combo khuyến mãi"}, ("views", "ctr", "roas", "days_left")),
    (
        "campaign_costs",
        {"entity_phrase": "ad campaign"},
        ("cost_cogs", "margin_gross", "kol_commission", "cost_offer_voucher"),
    ),
    (
        "product_shop_only",
        {"product_phrase": "găng tay"},
        ("channel_share_organic", "kol_share", "cost_offer_voucher", "cost_total_pct"),
    ),
)
#: the metric a WIRING key means (shopee_recommendations.kinds.WIRING); "sale" is a calendar
WIRING_METRIC = {
    "views": "views",
    "ctr": "ctr",
    "ctor": "ctor",
    "aov": "aov",
    "bien": "margin",
    "roas": "roas",
    "lien_ket": "channel_gmv_affiliate",
}
#: a draft kind -> the create_card kind that builds it (the rest have no free create path)
CREATE_OF = {
    "product_discount": "product_discount",
    "price": "price",
    "min_spend_voucher": "voucher",
    "flash_sale": "flash_sale",
    "bundle_deal": "combo",
    "add_on": "add_on",
    "gift": "gift",
    "variation_set": "variation_set",
    "title": "title",
    "cover_image": "cover_image",
    "price_display": "price_display",
    "description_first_line": "description_first_line",
}
MODES = ("answer", "analysis", "build")
BUCKETS = (
    "correct_refusal",
    "nodata_refusal",
    "wrong_figure",
    "silent_switch",
    "generic_unsupported",
    "needs_choice",
    "crash",
)
MISMATCH_RULE = (
    "a mismatch (a scope the metric cannot be measured on, or a card kind that does not move "
    "the metric) gets no figure for another scope / metric under the asked label, no silent "
    "switch to shop figures, and an answer that says the pairing does not apply"
)


def _kind_mismatches() -> list[tuple[str, str]]:
    from juli_backend.services.shopee_recommendations.kinds import WIRING

    return [(w, k) for w in WIRING_METRIC for k in D.DRAFT_KINDS if k not in WIRING[w]]


def mismatch_family() -> Iterator[dict[str, Any]]:
    for label, slots, metrics in SCOPE_MISMATCH:
        for m in metrics:
            for mode in ("answer", "analysis"):
                it = {
                    **slots,
                    "metric_key": m,
                    "metric_phrase": D.phrase_of(m),
                    "time_phrase": "last 7 days",
                }
                if mode == "analysis":
                    it.update(question_type="why_changed", claimed_direction="down")
                yield {
                    "id": f"mismatch.scope.{label}.{m}.{mode}",
                    "family": "mismatch",
                    "dims": {"mismatch": label, "metric": m, "mode": mode, "kind": "scope"},
                    "question": "Câu hỏi không khớp",
                    "intents": [it],
                    "writer": WRITER,
                    "jev": {
                        "metric": D.AGENT_OF.get(m) or [["gmv", 0.4], ["orders", 0.35]],
                        "fits": 0.95 if m in D.AGENT_OF else 0.5,
                        "mode": "why" if mode == "analysis" else "lookup",
                        "window": "last_7d_vs_prev_7d",
                        "scope": "product" if "product_phrase" in slots else "shop",
                        "product_named": 0.95 if "product_phrase" in slots else 0.05,
                    },
                    "scope_words": _SCOPE_WORDS[label],
                    "expect": {"mismatch": True},
                }
    for w, k in _kind_mismatches():
        m = WIRING_METRIC[w]
        for mode in MODES:
            if mode == "build" and k not in CREATE_OF:
                continue
            base: dict[str, Any] = {
                "id": f"mismatch.kind.{k}.{w}.{mode}",
                "family": "mismatch",
                "dims": {
                    "mismatch": f"{k}->{w}",
                    "metric": m,
                    "mode": mode,
                    "kind": "card",
                    "card_kind": k,
                },
                "question": "Thẻ này có tăng chỉ số không?",
                "writer": WRITER,
                "scope_words": (),
                "expect": {"mismatch": True},
            }
            words = f"{k.replace('_', ' ')} to raise {D.phrase_of(m)}"
            if mode == "answer":
                base.update(
                    intents=[
                        {"metric_key": m, "metric_phrase": words, "time_phrase": "last 7 days"}
                    ],
                    jev={"metric": D.AGENT_OF.get(m) or "gmv"},
                )
            elif mode == "analysis":
                goal = {"roas": "ads", "margin": "profit", "views": "traffic", "ctr": "traffic"}
                base.update(
                    intents=[
                        {
                            "question_type": "plan",
                            "needs_advice": True,
                            "goal": goal.get(m, "pricing_promo"),
                            "metric_phrase": words,
                        }
                    ],
                    jev=None,
                    agent_script=[
                        [
                            {
                                "type": "tool_use",
                                "id": "t1",
                                "name": "draft_card",
                                "input": {"kind": k, "item": "1001"},
                            }
                        ],
                        [
                            {
                                "type": "tool_use",
                                "id": "p1",
                                "name": "emit_plan",
                                "input": {
                                    "lead": "Kế hoạch tuần tới.",
                                    "actions": [
                                        {
                                            "lever": k,
                                            "card_ref": "draft:d1",
                                            "why": f"Tăng {m} bằng {k.replace('_', ' ')}.",
                                        }
                                    ],
                                },
                            }
                        ],
                    ],
                )
            else:
                card = {
                    "card_type": CREATE_OF[k],
                    "from_date": "2026-10-10",
                    "to_date": "2026-10-12",
                    "start_hour": 12,
                    "amount": 10,
                    "amount_unit": "pct",
                    "min_spend": 100_000,
                    "quantity": 20,
                    "name": "SYN thẻ",
                }
                base.update(
                    intents=[
                        {
                            "question_type": "create_card",
                            "product_phrase": "găng tay",
                            "metric_phrase": words,
                            "card": card,
                        }
                    ],
                    jev=None,
                )
            yield base


_SCOPE_WORDS = {
    "dvht_shop_per_product": ("Dịch vụ hiển thị Shop+",),
    "stock_for_campaign": ("chiến dịch",),
    "roas_for_organic": ("Organic", "tự nhiên"),
    "voucher_traffic": ("voucher",),
    "affiliate_ads": ("Tiếp thị liên kết",),
    "combo_traffic": ("Combo", "combo"),
    "campaign_costs": ("chiến dịch",),
    "product_shop_only": ("Găng tay",),
}
PAIRING_WORDS = re.compile(
    r"không áp dụng|không đo|không tính .* cho|không có .* cho|không làm "
    r"tăng|không ảnh hưởng",
    re.I,
)


def bucket(case: dict[str, Any], out: Any) -> str:
    """The current outcome of a mismatch case, in the owner's buckets."""
    if out.error or out.of("error"):
        return "crash"
    if out.of("unsupported"):
        return "generic_unsupported"
    answers, cards = out.of("data_answer"), out.of("card")
    said = " ".join(out.seller_strings(restated=False))
    if case["dims"]["kind"] == "card":
        if cards or (case["dims"]["mode"] == "answer" and answers):
            return "wrong_figure" if cards else "silent_switch"
        if case["dims"]["mode"] == "analysis" and answers:
            return "silent_switch"
    elif answers:
        named = any(any(w in str(a.get("title_vi")) for w in case["scope_words"]) for a in answers)
        return "wrong_figure" if named else "silent_switch"
    if "needs_choice" in out.stop_reasons:
        return "needs_choice"
    return "correct_refusal" if PAIRING_WORDS.search(said) else "nodata_refusal"
