"""Synthetic fixtures for the analytics agent tests. No client data: shops, products and numbers
are invented. FakeData implements `DataPort`; the fake ports answer from recorded dicts."""

from __future__ import annotations

import copy
import random
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta
from typing import Any

from juli_backend.services.analytics_agent.types import Usage

AS_OF = date(2026, 11, 8)  # no sale day (double day, 15th, 25th) in the 14 days before
SPLIT = AS_OF - timedelta(days=7)  # last day of the comparison window


def days(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def shop_rows(first: date, last: date, **cols: Any) -> list[dict[str, Any]]:
    """One row per day; each column is a constant, a callable(day) or None (NULL)."""
    out = []
    for d in days(first, last):
        row: dict[str, Any] = {
            "day": d,
            "complete": True,
            "gmv": None,
            "orders": None,
            "units": None,
            "views": None,
            "clicks": None,
            "ads_spend": None,
            "ads_gmv": None,
        }
        for k, v in cols.items():
            row[k] = v(d) if callable(v) else v
        out.append(row)
    return out


def source_rows(first: date, last: date, source: str, **cols: Any) -> list[dict[str, Any]]:
    out = []
    for d in days(first, last):
        row: dict[str, Any] = {
            "day": d,
            "source": source,
            "views": None,
            "clicks": None,
            "orders": None,
            "gmv": None,
        }
        for k, v in cols.items():
            row[k] = v(d) if callable(v) else v
        out.append(row)
    return out


def funnel_data(
    ctr_video_before: float = 0.10, ctr_video_after: float = 0.02, other_source: str = "video"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Views 1000/day, two sources; the `other_source` collapses its CTR in the last 7 days."""
    first = AS_OF - timedelta(days=60)

    def after(d: date) -> bool:
        return d > SPLIT

    def vid_clicks(d: date) -> float:
        return 400 * (ctr_video_after if after(d) else ctr_video_before)

    srcs = source_rows(
        first,
        AS_OF,
        other_source,
        views=400,
        clicks=vid_clicks,
        orders=lambda d: vid_clicks(d) * 0.1,
    ) + source_rows(first, AS_OF, "the_san_pham_khac", views=600, clicks=30, orders=3.0)
    shop = shop_rows(
        first,
        AS_OF,
        views=1000,
        clicks=lambda d: vid_clicks(d) + 30,
        orders=lambda d: vid_clicks(d) * 0.1 + 3.0,
        gmv=lambda d: (vid_clicks(d) * 0.1 + 3.0) * 100_000,
    )
    return shop, srcs


class FakeData:
    def __init__(
        self,
        shop: list[dict[str, Any]],
        sources: list[dict[str, Any]] | None = None,
        products: list[dict[str, Any]] | None = None,
        names: dict[str, str] | None = None,
        stock: list[dict[str, Any]] | None = None,
        cards: list[dict[str, Any]] | None = None,
        overview: Callable[[date, date], dict[str, Any]] | None = None,
        mv: dict[str, Any] | None = None,
        costs: Callable[[date, date, str | None], dict[str, Any]] | None = None,
        catalog: list[dict[str, Any]] | None = None,
        critical: dict[str, Any] | None = None,
    ):
        self.shop, self.sources, self.products = shop, sources or [], products or []
        self.names, self.stock, self.cards = names or {}, stock or [], cards or []
        self._overview, self._mv, self._costs = overview, mv or {}, costs
        self.catalog, self._critical = catalog or [], critical or {}
        self.calls: list[str] = []

    async def shop_daily(self, end: date, item: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(f"shop_daily:{item}")
        return [r for r in self.shop if r["day"] <= end]

    async def source_daily(self, a: date, b: date, item: str | None = None) -> list[dict[str, Any]]:
        self.calls.append("source_daily")
        return [r for r in self.sources if a <= r["day"] <= b]

    async def product_daily(self, a: date, b: date) -> list[dict[str, Any]]:
        self.calls.append("product_daily")
        return [r for r in self.products if a <= r["day"] <= b]

    async def item_names(self, ids: list[str]) -> dict[str, str]:
        return {i: self.names.get(i, i) for i in ids}

    async def catalog_search(self, phrase: str) -> list[dict[str, Any]]:
        return self.catalog

    async def stock_events(self, a: date, b: date) -> list[dict[str, Any]]:
        return self.stock

    async def open_cards(self) -> list[dict[str, Any]]:
        return self.cards

    async def overview(self, a: date, b: date) -> dict[str, Any]:
        return self._overview(a, b) if self._overview else {}

    async def metric_view(self, metric: str, a: date, b: date, item: str | None) -> dict[str, Any]:
        self.calls.append("metric_view")
        return self._mv

    async def cost_lines(self, a: date, b: date, item: str | None = None) -> dict[str, Any]:
        return self._costs(a, b, item) if self._costs else {}

    async def cost_lines_pair(
        self, a1: date, b1: date, a0: date, b0: date, item: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.calls.append(f"cost_pair:{item}")
        return await self.cost_lines(a1, b1, item), await self.cost_lines(a0, b0, item)

    async def critical(self, a: date, b: date) -> dict[str, Any]:
        return self._critical

    #: the tabs' default period a test sets; None = the engine's fallback (the last 30 days)
    default_span: tuple[date, date] | None = None

    async def default_window(self, as_of: date) -> tuple[date, date] | None:
        return self.default_span

    async def ad_lines(self, a: date, b: date) -> dict[str, dict[str, Any]] | None:
        return None


class FakeJev:
    """Answers from a script: `answers` maps a question id to its answer, or is a callable."""

    def __init__(
        self, answers: dict[str, dict[str, Any]] | Callable[..., dict[str, dict[str, Any]]]
    ):
        self.answers, self.calls = answers, []

    async def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], Usage]:
        self.calls.append((state, questions))
        out = self.answers(state, questions) if callable(self.answers) else self.answers
        return {k: v for k, v in out.items() if k in questions}, Usage(cost_usd=0.0001)


class FakeLLM:
    def __init__(
        self,
        intent: dict[str, Any] | None = None,
        text: str = "",
        deltas: list[str] | None = None,
        rewrite: str | None = None,
        agent_script: list[list[dict[str, Any]]] | None = None,
        agent_cost: float = 0.001,
    ):
        self.intent, self._text, self.deltas, self.rewrite = intent, text, deltas, rewrite
        self.agent_script, self.agent_cost = list(agent_script or []), agent_cost
        self.agent_calls: list[dict[str, Any]] = []
        self.parse_calls, self.stream_calls, self.text_calls = 0, [], []

    async def parse(
        self, system: str, tool: dict[str, Any], user: str
    ) -> tuple[dict[str, Any] | None, Usage]:
        self.parse_calls += 1
        return self.intent, Usage(cost_usd=0.0005)

    async def stream_text(self, system: str, user: str) -> AsyncIterator[str]:
        self.stream_calls.append(user)
        for d in self.deltas or [self._text]:
            yield d

    async def agent(
        self,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        *,
        force_tool: str | None = None,
    ) -> tuple[list[dict[str, Any]], Usage]:
        """Scripted turns: each call pops the next list of content blocks; none left = an LLM
        error (the engine must fall back)."""
        self.agent_calls.append(
            {
                "tools": [t["name"] for t in tools],
                "messages": len(messages),
                "force": force_tool,
                "replayed": copy.deepcopy(messages),
            }
        )
        if not self.agent_script:
            raise RuntimeError("no scripted agent turn")
        return self.agent_script.pop(0), Usage(cost_usd=self.agent_cost)

    async def text(self, system: str, user: str) -> tuple[str, Usage]:
        self.text_calls.append(user)
        return (self.rewrite if self.rewrite is not None else self._text), Usage(cost_usd=0.0005)


class ListSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == kind]


def noisy_orders(levels_last_two: tuple[float, float], seed: int = 3) -> list[dict[str, Any]]:
    """Orders only; weekly levels random in [7, 14] until the last two weeks (prev, cur)."""
    rng = random.Random(seed)
    weeks = 15
    first = AS_OF - timedelta(days=weeks * 7 - 1)
    lv = [rng.uniform(7, 14) for _ in range(weeks - 2)] + list(levels_last_two)
    return shop_rows(first, AS_OF, orders=lambda d: lv[weeks - 1 - (AS_OF - d).days // 7])


class FakeCardEngine:
    """CardEnginePort over recorded engine results."""

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        per_kind: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.result = result if result is not None else {"ok": True, "card": engine_card()}
        self.per_kind = per_kind or {}
        self.calls: list[tuple[str, str | None]] = []

    def needs_item(self, kind: str) -> bool:
        from juli_backend.services.shopee_recommendations.generators import GENERATORS

        return GENERATORS[kind][1] if kind in GENERATORS else True

    def allowed_kinds(self, metric: str) -> tuple[str, ...]:
        from juli_backend.services.shopee_recommendations.kinds import allowed_for_metric

        return allowed_for_metric(metric)

    async def engine_card(self, kind: str, item: str | None, as_of: date) -> dict[str, Any]:
        self.calls.append((kind, item))
        return self.per_kind.get(kind, self.result)

    async def build_custom(self, spec: dict[str, Any], as_of: date) -> dict[str, Any]:
        self.custom_calls = [*getattr(self, "custom_calls", []), spec]
        return {
            "ok": True,
            "kind": "min_spend_voucher",
            "card": {**engine_card(), "title": "Mã giảm giá cho cả shop", "kind": spec["kind"]},
        }


def version(
    label: str, gmv: float | None, profit: float | None, estimable: bool = True
) -> dict[str, Any]:
    if not estimable:
        return {"label": label, "inputs": {"x": 1}, "result": {"estimable": False}}
    return {
        "label": label,
        "inputs": {"x": 1},
        "result": {
            "estimable": True,
            "cost_total": 50_000,
            "own": {"delta": {"gmv": {"p50": gmv}, "profit": {"p50": profit}}, "days": 14},
            "margin": {"before_pct": 30.0, "after_pct": 28.5},
            "option": {"cost": {"text": "Chi phí 50.000đ"}},
        },
    }


def engine_card() -> dict[str, Any]:
    return {
        "title": "Giảm giá 5% cho sản phẩm A",
        "versions": [
            version("Nhẹ", 1_000_000.0, 100_000.0),
            version("Vừa", 2_000_000.0, 300_000.0),
            version("Mạnh", None, None, estimable=False),
        ],
    }


class FakeEntityData(FakeData):
    """FakeData plus the entity readers: synthetic voucher / affiliate / campaign / product rows."""

    def __init__(self, *a: Any, **kw: Any):
        self.entity: dict[str, Any] = kw.pop("entity", {})
        super().__init__(*a, **kw)

    async def entity_totals(
        self, kind: str, a: date, b: date, item: str | None = None
    ) -> dict[str, Any]:
        rows = self.entity.get(kind, [])
        sel = [r for r in rows if a <= r["day"] <= b and (item is None or r.get("item") == item)]
        return {
            "orders": sum(r["orders"] for r in sel),
            "gmv": sum(r["gmv"] for r in sel),
            "cost": sum(r["cost"] for r in sel) if sel or kind == "voucher" else None,
        }

    async def voucher_figures(self, a: date, b: date) -> dict[str, Any] | None:
        """Synthetic `voucher_figures_of` output: per-day voucher rows (orders, GMV, cost of the
        known orders) and the voucher settings as given."""
        rows = [r for r in self.entity.get("voucher", []) if a <= r["day"] <= b]
        known = [r for r in rows if r.get("known", True)]
        gmv = sum(r["gmv"] for r in rows)
        return {
            "lines": len(rows) or self.entity.get("voucher_lines", 0),
            "orders": sum(r["orders"] for r in rows),
            "gmv": gmv,
            "cost": sum(r["cost"] for r in known) if known or not rows else None,
            "known_orders": sum(r["orders"] for r in known),
            "known_gmv_share_pct": sum(r["gmv"] for r in known) * 100 / gmv if gmv else None,
            "settings": self.entity.get("voucher_settings", []),
        }

    async def campaign_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        return self.entity.get("campaigns", [])

    async def product_profit(self, item: str, a: date, b: date) -> dict[str, Any] | None:
        return self.entity.get("product_profit", {}).get((item, a))

    async def product_profit_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        return self.entity.get("product_rows", [])

    async def budget_days(self, a: date, b: date) -> list[dict[str, Any]]:
        return [r for r in self.entity.get("budget_days", []) if a <= r["day"] <= b]


def tool_use(name: str, tid: str, **args: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": tid, "name": name, "input": args}


def plan_turn(*items: dict[str, Any]) -> list[dict[str, Any]]:
    return [tool_use("emit_plan", "p1", items=list(items))]
