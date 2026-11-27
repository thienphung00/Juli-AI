"""The Chat regression bank's runner (owner decision #109): one case = one seller question run
end to end through `analytics_agent.run` on the seeded synthetic Shopee shop, then checked
against what the tabs show for the same metric, period and scope.

Deterministic and free: the parser output and the Jev routing answers are the case's own
(`FakeLLM` / `FakeJev`); every figure comes from the shop's rows through the production readers.
The SCREEN figure is read in the check from the same analytics service the tab reads
(`queries.overview` for Tổng quan, the Phân tích voucher / KOL cells, `metric_view`, the
shared `ProductProfit`), never from a number written in the case.

Shared by the SQLite bank (`test_chat_bank.py`) and its Postgres subset
(`tests/integration/analytics_agent/test_chat_bank_pg.py`).
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.analytics_agent import AskRequest, routing, run, shopee_labels
from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine
from tests.unit.analytics_agent.fakes import FakeJev, FakeLLM, ListSink
from tests.unit.analytics_agent.test_routing import ch, nl

BANK_DIR = Path(__file__).parent
CASES_FILE = BANK_DIR / "cases.json"
ADVISOR_FILE = BANK_DIR / "advisor_cases.json"
DEFAULT_AS_OF = date(2026, 10, 7)  # the seeded shop's last complete day (a Wednesday)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

#: what the seller may never read, on any answer
FORBIDDEN = ("ước tính", "số minh hoạ", "số minh họa", "None", "null", "NaN", "undefined")
#: an internal key that leaked into seller text (e.g. "coverage_orders")
SNAKE = re.compile(r"\b[a-z]+_[a-z]+(?:_[a-z]+)*\b")
SELLER_KEYS = (
    "text",
    "text_vi",
    "title_vi",
    "value",
    "value_vi",
    "detail_vi",
    "label_vi",
    "question_vi",
    "window_vi",
    "fresh_vi",
    "before_vi",
    "reason_vi",
    "note_vi",
    "sale_vi",
)
STATUSES = ("pass", "xfail", "pending")
#: a Vietnamese letter (a label with none is English)
VI_LETTERS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]")

INTENT_DEFAULT: dict[str, Any] = {
    "question_type": "status",
    "metric_phrase": None,
    "claimed_direction": "none",
    "time_phrase": None,
    "explicit_from": None,
    "explicit_to": None,
    "named_month": None,
    "product_phrase": None,
    "source_phrase": None,
    "entity_phrase": None,
    "metric_key": "none",
    "ranking": "none",
    "asks_why": False,
    "needs_advice": False,
    "goal": "none",
    "card": dict(routing.CARD_SLOT_EMPTY),
    "card_kind": "none",
}


def load_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["cases"])


# ------------------------------------------------------------------ fakes from the case


def intent_of(spec: dict[str, Any]) -> dict[str, Any]:
    it = {**INTENT_DEFAULT, "card": dict(INTENT_DEFAULT["card"])}
    card = spec.get("card") or {}
    it.update({k: v for k, v in spec.items() if k != "card"})
    it["card"].update(card)
    return it


def _choice(v: Any) -> dict[str, Any]:
    """ "pick" = a clear choice (0.95); [[pick, p], ...] = the probabilities as given."""
    if isinstance(v, list):
        probs = {str(k): float(p) for k, p in v}
        top = max(probs, key=lambda k: probs[k])
        return {"type": "choice", "choice": top, "probabilities": probs}
    return ch(str(v))


def jev_answers(spec: dict[str, Any] | None, it: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every routing question answered: a clear lookup of the parsed metric unless the case says
    otherwise."""
    s = dict(spec or {})
    metric = s.pop("metric", None) or routing.named_metric_of(it) or "gmv"
    top = max(metric, key=lambda kv: kv[1])[0] if isinstance(metric, list) else metric
    chain = s.pop("chain", None) or routing.METRIC_CHAIN.get(top, "gmv_change")
    out = {
        "fits": nl(float(s.pop("fits", 0.95))),
        "mode": _choice(s.pop("mode", "lookup")),
        "lookup": _choice(s.pop("lookup", "metric_total")),
        "chain": _choice(chain),
        "metric": _choice(metric),
        "window": _choice(s.pop("window", "last_7d_vs_prev_7d")),
        "scope": _choice(s.pop("scope", "shop")),
        "product_named": nl(float(s.pop("product_named", 0.05))),
        "metric_named": nl(float(s.pop("metric_named", 0.95))),
    }
    for k, v in s.items():  # e.g. "product": the product Choice of resolve_product
        out[k] = _choice(v)
    return out


def agreeable(questions: dict[str, Any], over: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A router that answers every other question (the card stage's kind / actionable / version
    ...): a Choice picks its first option clearly, a yes/no is a clear yes, unless the case's
    `jev_card` says otherwise."""
    out: dict[str, dict[str, Any]] = {}
    for k, q in questions.items():
        if k in over:
            v = over[k]
            out[k] = nl(float(v)) if isinstance(v, int | float) else _choice(v)
        elif q.get("type") == "choice" and q.get("criteria"):
            out[k] = ch(next(iter(q["criteria"])))
        else:
            out[k] = nl(0.9)
    return out


class DownJev:
    """The router is down (the gate's `JevUnavailable` after its retries)."""

    def __init__(self) -> None:
        self.calls = 0

    async def ask(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> Any:
        from juli_backend.services.juli_agent_api.ports import JevUnavailable

        self.calls += 1
        raise JevUnavailable("router down (bank case)")


def fakes_of(case: dict[str, Any]) -> tuple[FakeLLM, Any, list[dict[str, Any]]]:
    intents = [intent_of(i) for i in case.get("intents") or []]
    if case.get("parse_fails"):
        llm = FakeLLM(None)
    else:
        llm = FakeLLM(
            {"restated_vi": case.get("restated") or case["question"], "intents": intents},
            text=case.get("writer", ""),
            agent_script=case.get("agent_script"),
        )
    if case.get("jev_down"):
        return llm, DownJev(), intents
    specs = case.get("jev")
    per = specs if isinstance(specs, list) else [specs] * max(1, len(intents))
    keyed = [
        (routing.jev_state(it)["intent"], jev_answers(sp, it))
        for it, sp in zip(intents, per, strict=False)
    ]

    def answer(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        if "product_phrase" in state:  # resolve_product's Choice among catalog candidates
            pick = (case.get("jev_product") or {}).get("pick")
            return {"product": _choice(pick)} if pick else {"product": _choice([["?", 0.5]])}
        found = next((a for st, a in keyed if st == state.get("intent")), None)
        if found is None:
            found = keyed[0][1] if keyed and "intent" in state else {}
        return {**agreeable(questions, case.get("jev_card") or {}), **found}

    return llm, FakeJev(answer), intents


def ungate_if_asked(case: dict[str, Any], monkeypatch: Any) -> None:
    """`"ungated": true`: a case about a KNOWN profit. The seeded shop knows 23-57 % of its GMV,
    so the 70 % gate is lowered for Chat and the tabs alike (`tests/unit/conftest.py`
    `ungated_profit`); the gate itself has its own cases (`profit-*-below-70`)."""
    if case.get("ungated"):
        from juli_backend.services.shopee_profit import shop_profit

        monkeypatch.setattr(shop_profit, "MIN_KNOWN_GMV_SHARE_PCT", Decimal(0))


# ------------------------------------------------------------------ one run


@dataclass
class Outcome:
    events: list[dict[str, Any]]
    stop_reasons: list[str]
    routes: list[dict[str, Any]]
    error: str | None = None
    followup: Outcome | None = None
    jev_calls: int = 0
    llm: Any = None

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("type") == kind]

    def seller_strings(self, restated: bool = True) -> list[str]:
        """Every string the seller reads; `restated=False` leaves out the seller's own words."""
        out: list[str] = []

        def walk(v: Any, key: str | None) -> None:
            if isinstance(v, dict):
                for k, x in v.items():
                    if k in ("pending", "link", "routing", "templates"):
                        continue
                    if k == "value" and key == "options":  # an option's value is its id
                        continue
                    walk(x, k)
            elif isinstance(v, list):
                for x in v:
                    walk(x, key)
            elif isinstance(v, str) and key == "options":
                return
            elif isinstance(v, str) and key in SELLER_KEYS:
                out.append(v)

        for e in self.events:
            if e.get("type") in ("done", "status") or (
                e.get("type") == "restated" and not restated
            ):
                continue
            walk(e, None)
        return out

    def final_text(self) -> str:
        """The written summary as the seller ends up reading it (deltas, then a replace)."""
        text = ""
        for e in self.events:
            if e.get("type") == "text_delta":
                text += e.get("text") or ""
            elif e.get("type") == "text_replace":
                text = e.get("text") or ""
        return text


async def ask(
    factory: SessionFactory,
    data: Any,
    shop_id: Any,
    case: dict[str, Any],
    engine: Any = None,
) -> Outcome:
    as_of = date.fromisoformat(case["as_of"]) if case.get("as_of") else DEFAULT_AS_OF
    llm, jev, _ = fakes_of(case)
    sink = ListSink()
    req = AskRequest(
        shop_id=shop_id,
        platform=case.get("platform", "shopee"),
        text=None if case.get("template") else case["question"],
        template=case.get("template"),
        as_of=as_of,
    )
    engine = engine if engine is not None else ServiceCardEngine(factory, shop_id)
    out = await _run(req, data, engine, llm, jev, sink)
    out.routes = [] if case.get("template") or case.get("parse_fails") else await _classify(case)
    then = case.get("then")
    if then and out.error is None:
        asked = out.of("needs_choice")
        if asked:
            pending = asked[-1]["pending"]
            choice = then.get("choice") or {}
            value = choice.get("value")
            if value == "$first":
                value = asked[-1]["options"][0]["value"]
            follow = AskRequest(
                shop_id=shop_id,
                platform=case.get("platform", "shopee"),
                choice={"item": asked[-1]["item"], "value": value},
                pending=pending,
                as_of=as_of,
            )
            out.followup = await _run(follow, data, engine, llm, jev, ListSink())
    return out


async def _run(
    req: AskRequest,
    data: Any,
    engine: Any,
    llm: Any,
    jev: Any,
    sink: ListSink,
) -> Outcome:
    error = None
    try:
        res = await run(
            req,
            llm=llm,
            jev=jev,
            sink=sink,
            labels=shopee_labels(),
            data=data,
            card_engine=engine,
        )
        stops = list(res.stop_reasons)
    except Exception as exc:  # recorded: a case that raises fails on its expectations
        error = f"{type(exc).__name__}: {exc}"[:300]
        stops = [e["stop_reasons"] for e in sink.events if e.get("type") == "done"][-1:] or [
            ["error"]
        ]
        stops = list(stops[0])
    calls = getattr(jev, "calls", 0)
    return Outcome(
        sink.events, stops, [], error, jev_calls=calls if isinstance(calls, int) else len(calls)
    )


async def _classify(case: dict[str, Any]) -> list[dict[str, Any]]:
    """The routing decision per intent (no data reads), with the same fakes."""
    llm, jev, _ = fakes_of(case)
    as_of = date.fromisoformat(case["as_of"]) if case.get("as_of") else DEFAULT_AS_OF
    try:
        got = await routing.classify(case["question"], as_of, llm, jev)
    except Exception as exc:
        return [{"outcome": f"error: {type(exc).__name__}"}]
    return list(got.get("intents") or [])


# ------------------------------------------------------------------ the screen's figures


_SCREENS: dict[str, Any] = {}


async def screen_value(factory: SessionFactory, shop_id: Any, spec: dict[str, Any]) -> Any:
    """The tab's own figure for `spec["screen"]` over [from, to] (memoised: the shop is
    read-only; the key holds the profit gate)."""
    from juli_backend.services.shopee_profit import shop_profit

    key = f"{shop_id}|{spec['screen']}|{spec['from']}|{spec['to']}|"
    key += str(shop_profit.MIN_KNOWN_GMV_SHARE_PCT)
    if key not in _SCREENS:
        _SCREENS[key] = await _screen_value(factory, shop_id, spec)
    return copy.deepcopy(_SCREENS[key])


async def _screen_value(factory: SessionFactory, shop_id: Any, spec: dict[str, Any]) -> Any:
    from juli_backend.services.shopee_analytics import loaders, metric_view, queries, service
    from juli_backend.services.shopee_analytics.channel_split import channel_split
    from juli_backend.services.shopee_analytics.rankings import _cell_other
    from juli_backend.services.shopee_profit.ladder import components_of
    from juli_backend.services.shopee_profit.shop_profit import (
        product_margin_pct_shown,
        product_profit_shown,
    )

    a, b = date.fromisoformat(spec["from"]), date.fromisoformat(spec["to"])
    src, _, key = spec["screen"].partition(".")
    async with factory() as s:
        try:
            if src == "overview":  # Tổng quan
                body = await queries.overview(s, shop_id, period="custom", start=a, end=b)
                v = (body.get("shop_metrics") or {}).get(key)
                return None if v is None else (float(v) / 100 if key == "margin_pct" else v)
            if src == "overview_prev":  # Tổng quan's KPI strip: the window before
                body = await queries.overview(s, shop_id, period="custom", start=a, end=b)
                return ((body.get("kpi_strip") or {}).get(key) or {}).get("previous")
            if src == "overview_profit":  # Tổng quan's profit block (ROAS hoà vốn)
                body = await queries.overview(s, shop_id, period="custom", start=a, end=b)
                return (body.get("profit") or {}).get(key)
            if src in ("metric_view", "metric_view_channels", "metric_view_total"):
                # Phân tích: a metric's view (products, channels, total), optionally one product
                metric, _, item = key.partition("@")
                try:
                    return await metric_view.metric_view(
                        s,
                        shop_id,
                        metric=metric,
                        period="custom",
                        start=a,
                        end=b,
                        product_id=item or None,
                    )
                except ValueError:
                    return None
            if src == "channel_split":  # Kênh: the channel KPIs
                return (
                    (await channel_split(s, shop_id, period="custom", start=a, end=b)).get("kpis")
                    or {}
                ).get(key)
            window = await service.resolve(s, shop_id, period="custom", start=a, end=b)
            if window is None:
                return None
            ctx = await loaders.load_context(s, shop_id)
            ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
            view = await service.load_view(s, shop_id, ctx, window, funnel=True, rows="soft")
            if src in ("voucher", "kol"):  # Phân tích voucher / KOL cells; Ưu đãi's voucher part
                if key == "cost":
                    return components_of(view.pairs)["offer_voucher"]
                cell = _cell_other("vouchers" if src == "voucher" else "kols", view)
                if key == "aov":
                    return None if not cell.orders else cell.gmv / cell.orders
                return cell.orders if key == "orders" else cell.gmv
            if src == "offer":  # Ưu đãi parts: offer_combo / offer_promo / offer_voucher
                return components_of(view.pairs)[key]
            if src == "product":  # one product's profit / margin, as the cards show it
                item, _, what = key.partition(".")
                p = view.profit.products.get(item)
                if p is None:
                    return None
                if what == "profit":
                    return product_profit_shown(p)
                if what == "break_even":
                    from juli_backend.services.shopee_analytics.fmt import ratio
                    from juli_backend.services.shopee_profit.shop_profit import (
                        product_break_even_roas_shown,
                    )

                    return ratio(product_break_even_roas_shown(p), 2)
                if what == "ads_spend":
                    return p.ad_spend if view.ads.known_spend is not None else None
                v = product_margin_pct_shown(p)
                return None if v is None else float(v) / 100
            raise KeyError(f"unknown screen source {src!r}")
        finally:
            await s.rollback()


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal | int | float):
        return float(v)
    raise TypeError(f"not a number: {v!r}")


def _same(chat: Any, screen: Any) -> bool:
    c, s = _num(chat), _num(screen)
    if c is None or s is None:
        return c is None and s is None
    return abs(c - s) <= max(0.5, 1e-6 * abs(s))


# ------------------------------------------------------------------ the checks


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)

    def need(self, ok: bool, msg: str) -> None:
        if not ok:
            self.problems.append(msg)


def _subset(got: dict[str, Any], want: dict[str, Any]) -> list[str]:
    return [f"{k}: got {got.get(k)!r}, want {v!r}" for k, v in want.items() if got.get(k) != v]


async def check(
    out: Outcome,
    case: dict[str, Any],
    factory: SessionFactory,
    shop_id: Any,
    expect: dict[str, Any] | None = None,
) -> list[str]:
    exp = case["expect"] if expect is None else expect
    r = Report()
    r.need(out.error is None, f"raised {out.error}")
    if "stop" in exp and not (exp.get("answers_optional") and not out.of("data_answer")):
        r.need(out.stop_reasons == exp["stop"], f"stop {out.stop_reasons} != {exp['stop']}")
    if "stop_in" in exp:
        r.need(
            bool(out.stop_reasons) and set(out.stop_reasons) <= set(exp["stop_in"]),
            f"stop {out.stop_reasons} not in {exp['stop_in']}",
        )
    if "events_any" in exp:
        r.need(any(out.of(k) for k in exp["events_any"]), f"none of {exp['events_any']}")
    for i, want in enumerate(exp.get("routes") or []):
        got = out.routes[i] if i < len(out.routes) else {}
        for p in _subset(got, want):
            r.problems.append(f"route[{i}] {p}")
    if "n_intent_blocks" in exp:
        n = len(out.of("intent_block"))
        r.need(n == exp["n_intent_blocks"], f"{n} intent blocks, want {exp['n_intent_blocks']}")
    for kind in exp.get("events") or []:
        r.need(bool(out.of(kind)), f"no {kind} event")
    for kind in exp.get("no_events") or []:
        r.need(not out.of(kind), f"unexpected {kind} event")
    if "more_items" in exp:
        items = [i for e in out.of("more") for i in e.get("items") or []]
        r.need(len(items) == exp["more_items"], f"{len(items)} more items")
        if exp.get("more_vietnamese"):
            en = [
                i["label_vi"]
                for i in items
                if re.search(r"[a-z]{3,}", i["label_vi"]) and not VI_LETTERS.search(i["label_vi"])
            ]
            r.need(not en, f"'more' labels in English: {en}")
    if "needs_choice_item" in exp:
        asked = out.of("needs_choice")
        got = asked[-1]["item"] if asked else None
        r.need(got == exp["needs_choice_item"], f"needs_choice item {got!r}")
    answers = out.of("data_answer")
    if exp.get("answers_optional") and not answers and exp.get("answers"):
        # "no data" is right only when the tab has no figure either
        want = exp["answers"][0]
        screen = await screen_value(factory, shop_id, want) if "screen" in want else None
        if want.get("screen", "").startswith("metric_view_total."):
            screen = ((screen or {}).get("total") or {}).get("now")
        r.need(screen is None, f"Chat has no figure but the tab shows {screen!r}")
        r.need(set(out.stop_reasons) <= {"data_missing"}, f"stop {out.stop_reasons}")
        exp = {k: v for k, v in exp.items() if k not in ("answers", "stop")}
    for j, want in enumerate(exp.get("answers") or []):
        if j >= len(answers):
            r.problems.append(f"answer[{j}] missing ({len(answers)} data answers)")
            continue
        a = answers[j]
        for k in ("kind", "title_vi"):
            if k in want:
                r.need(a.get(k) == want[k], f"answer[{j}].{k} {a.get(k)!r} != {want[k]!r}")
        if "title_has" in want:
            r.need(
                want["title_has"] in str(a.get("title_vi")),
                f"answer[{j}] title {a.get('title_vi')!r}",
            )
        if "window" in want:
            r.need(
                str(a.get("window_vi") or "").startswith(want["window"]),
                f"answer[{j}] window {a.get('window_vi')!r}, want {want['window']}…",
            )
        if want.get("fresh", True):
            r.need(
                bool(re.fullmatch(r"Số liệu đến hết \d\d/\d\d", str(a.get("fresh_vi") or ""))),
                f"answer[{j}] no freshness line",
            )
        if "rows_have" in want:
            labels = [x.get("label_vi") for x in a.get("rows") or []]
            for name in want["rows_have"]:
                r.need(name in labels, f"answer[{j}] rows {labels} lack {name!r}")
        if "first_row" in want:
            rows = a.get("rows") or []
            first = rows[0].get("item_id") or rows[0].get("label_vi") if rows else None
            r.need(first == want["first_row"], f"answer[{j}] first row {first!r}")
        if "value_has" in want:
            r.need(
                want["value_has"] in str(a.get("value")), f"answer[{j}] value {a.get('value')!r}"
            )
        if "screen" in want and want["screen"].startswith(("daily.", "metric_view_channels.")):
            await _series_check(r, j, a, want, factory, shop_id)
        elif "screen" in want:
            fig = {**want, "from": want["from"], "to": want["to"]}
            screen = await screen_value(factory, shop_id, fig)
            if want["screen"].startswith("metric_view_total."):
                screen = ((screen or {}).get("total") or {}).get("now")
            if want["screen"].startswith("metric_view."):
                prods = sorted(
                    (p for p in screen.get("products") or [] if p.get("now") is not None),
                    key=lambda p: -float(p["now"]),
                )
                rows = a.get("rows") or []
                got_ids = [x.get("item_id") for x in rows]
                want_ids = [p["key"] for p in prods][: len(got_ids)]
                r.need(got_ids == want_ids, f"answer[{j}] order {got_ids} != screen {want_ids}")
                for x, p in zip(rows, prods, strict=False):
                    r.need(
                        _same(x.get("gmv"), p["now"]),
                        f"answer[{j}] {x.get('item_id')} GMV {x.get('gmv')} != screen {p['now']}",
                    )
            else:
                r.need(
                    _same(a.get("value_raw"), screen),
                    f"answer[{j}] {want['screen']}: chat {a.get('value_raw')!r} != screen "
                    f"{screen!r}",
                )
                if screen is None:
                    shown = str(a.get("value"))
                    r.need(not re.search(r"\d", shown), f"answer[{j}] shows {shown!r} for missing")
                    if "missing_as" in want:
                        r.need(
                            shown == want["missing_as"],
                            f"answer[{j}] missing shown {shown!r}, want {want['missing_as']!r}",
                        )
        if "before_screen" in want:  # the comparison figure the tab shows beside it
            prev = await screen_value(
                factory,
                shop_id,
                {
                    "screen": want["before_screen"],
                    "from": want.get("prev_from", want["from"]),
                    "to": want.get("prev_to", want["to"]),
                },
            )
            r.need(
                _same(a.get("before"), prev),
                f"answer[{j}] before: chat {a.get('before')!r} != screen {prev!r}",
            )
    if "n_answers" in exp:
        r.need(len(answers) == exp["n_answers"], f"{len(answers)} data answers")
    if "n_answers_min" in exp:
        r.need(len(answers) >= exp["n_answers_min"], f"{len(answers)} data answers")
    seller = out.seller_strings()
    blob = "\n".join(seller)
    for w in FORBIDDEN + tuple(exp.get("forbid") or ()):
        r.need(w not in blob, f"forbidden {w!r} in seller text")
    leaks = sorted({m for s in seller for m in SNAKE.findall(s)})
    r.need(not leaks, f"internal keys in seller text: {leaks}")
    said = out.seller_strings(restated=False)
    for w in exp.get("require") or []:
        r.need(w in "\n".join(said), f"seller text lacks {w!r}")
    if exp.get("no_numbers"):  # a refusal / an offer states no figure
        nums = [
            s
            for s in said
            if re.search(r"\d[\d.]*\s*(đ|%)|\b\d{2,}\b", s) and not re.search(r"\d\d/\d\d", s)
        ]
        r.need(not nums, f"a figure in a no-number answer: {nums[:3]}")
    if answers and out.stop_reasons and set(out.stop_reasons) == {"data_answer"}:
        # owner #110 rule 2: the period and the data day once, in the answer's top line
        metas = out.of("meta")
        r.need(
            any(re.fullmatch(r"Số liệu đến hết \d\d/\d\d", str(m.get("fresh_vi"))) for m in metas),
            "no top line (meta) with the freshness day",
        )
        r.need(len(metas) <= len(answers), f"{len(metas)} period lines for {len(answers)} answers")
    if "followup" in exp:
        if out.followup is None:
            r.problems.append("no follow-up ran (no needs_choice to answer)")
        else:
            sub = await check(out.followup, case, factory, shop_id, exp["followup"])
            r.problems += [f"followup: {p}" for p in sub]
    if "max_jev_calls" in exp:
        r.need(out.jev_calls <= exp["max_jev_calls"], f"{out.jev_calls} router calls")
    return r.problems


async def _series_check(
    r: Report, j: int, a: dict[str, Any], want: dict[str, Any], factory: Any, shop_id: Any
) -> None:
    """A daily trend point by point against Tổng quan of that day; a channel split row by row
    against Phân tích's channel cells."""
    src, _, key = want["screen"].partition(".")
    if src == "daily":
        a0, b0 = date.fromisoformat(want["from"]), date.fromisoformat(want["to"])
        days = [a0.fromordinal(d) for d in range(a0.toordinal(), b0.toordinal() + 1)]
        series = a.get("series") or []
        r.need(len(series) == len(days), f"answer[{j}] {len(series)} points for {len(days)} days")
        for d, pt in zip(days, series, strict=False):
            v = await screen_value(
                factory, shop_id, {"screen": key, "from": d.isoformat(), "to": d.isoformat()}
            )
            r.need(
                _same(pt.get("value"), v),
                f"answer[{j}] {d:%d/%m}: chat {pt.get('value')!r} != screen {v!r}",
            )
        return
    view = await screen_value(factory, shop_id, {**want, "screen": f"metric_view.{key}"})
    cells = {c["key"]: c.get("now") for c in (view or {}).get("channels") or []}
    for row in a.get("rows") or []:
        ch = row.get("channel")
        r.need(
            _same(row.get("value"), cells.get(ch)),
            f"answer[{j}] channel {ch}: chat {row.get('value')!r} != screen {cells.get(ch)!r}",
        )


__all__ = ["Outcome", "ask", "check", "load_cases", "screen_value"]
