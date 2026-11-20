"""Synthetic fixtures for the analytics agent tests. No client data: shops, products and numbers
are invented. FakeData implements `DataPort`; the fake ports answer from recorded dicts."""

from __future__ import annotations

import random
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta
from typing import Any

from juli_backend.services.analytics_agent.types import Usage

AS_OF = date(2026, 10, 25)  # no Shopee double day in the 14 days before
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

    async def critical(self, a: date, b: date) -> dict[str, Any]:
        return self._critical


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
    ):
        self.intent, self._text, self.deltas, self.rewrite = intent, text, deltas, rewrite
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
