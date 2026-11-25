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
        values: Callable[[list[str], date, date], dict[str, Any]] | None = None,
    ):
        self.shop, self.sources, self.products = shop, sources or [], products or []
        self.names, self.stock, self.cards = names or {}, stock or [], cards or []
        self._overview, self._mv, self._costs = overview, mv or {}, costs
        self.catalog, self._critical = catalog or [], critical or {}
        self._values = values  # scripted registry values (profit, margin, ...) by window
        self.calls: list[str] = []

    async def shop_daily(self, end: date, item: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(f"shop_daily:{item}")
        return [r for r in self.shop if r["day"] <= end]

    async def source_totals(
        self, a: date, b: date, item: str | None = None
    ) -> list[dict[str, Any]]:
        """`query(group_by="source")` stand-in: per-source window totals of the scripted days (a
        source with no value in a column stays None)."""
        self.calls.append("source_totals")
        out: dict[str, dict[str, Any]] = {}
        for r in self.sources:
            if not a <= r["day"] <= b:
                continue
            o = out.setdefault(r["source"], {"source": r["source"]})
            for k in ("views", "clicks", "orders", "gmv"):
                if r.get(k) is not None:
                    o[k] = (o.get(k) or 0.0) + r[k]
        return [
            {"views": None, "clicks": None, "orders": None, "gmv": None, **o} for o in out.values()
        ]

    async def product_daily(self, a: date, b: date) -> list[dict[str, Any]]:
        """`query(group_by="item")` stand-in: one total row per product over the window."""
        self.calls.append("product_daily")
        out: dict[str, dict[str, Any]] = {}
        for r in self.products:
            if a <= r["day"] <= b:
                o = out.setdefault(
                    r["item_id"], {"day": a, "item_id": r["item_id"], "gmv": 0.0, "orders": 0.0}
                )
                o["gmv"] += float(r["gmv"] or 0)
                o["orders"] += float(r["orders"] or 0)
        return list(out.values())

    async def campaign_products(self, a: date, b: date) -> dict[str, list[str]]:
        return {}

    def _window_values(self, ids: list[str], a: date, b: date) -> dict[str, Any]:
        """Totals of the scripted shop days for a window (a test stand-in for `query()`)."""
        from juli_backend.services.analytics_agent.chains import metric_value
        from juli_backend.services.analytics_agent.registry_reads import roas

        rows = [r for r in self.shop if a <= r["day"] <= b and r.get("complete", True)]
        out: dict[str, Any] = {}
        scripted = self._values(ids, a, b) if self._values else {}
        for i in ids:
            if i in scripted:
                out[i] = scripted[i]
            elif i in ("gmv", "orders", "units", "views", "clicks", "aov", "ctr", "ctor"):
                out[i] = metric_value(self.shop, i, a, b)
            elif i == "cost_ads":
                vals = [r["ads_spend"] for r in rows if r.get("ads_spend") is not None]
                out[i] = float(sum(vals)) if vals else None
            elif i == "roas":
                g = [r["ads_gmv"] for r in rows if r.get("ads_gmv") is not None]
                c = out.get("cost_ads") or [
                    r["ads_spend"] for r in rows if r.get("ads_spend") is not None
                ]
                spend = c if isinstance(c, float) else (float(sum(c)) if c else None)
                out[i] = roas(float(sum(g)), spend) if g and spend else None
            else:
                out[i] = None
        return out

    async def metrics(
        self,
        ids: list[str],
        a: date,
        b: date,
        *,
        scope: str = "shop",
        items: list[str] | None = None,
        channel: str | None = None,
        campaigns: list[str] | None = None,
        group_by: str | None = None,
        compare: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(f"metrics:{group_by}:{','.join(ids)}")
        if group_by == "day":
            rows = [
                {"day": r["day"], **self._window_values(ids, r["day"], r["day"])}
                for r in self.shop
                if a <= r["day"] <= b
            ]
            return {"values": {}, "rows": rows, "coverage": {}, "partial": False, "previous": None}
        if group_by is not None:
            return {"values": {}, "rows": [], "coverage": {}, "partial": False, "previous": None}
        n = (b - a).days + 1
        res: dict[str, Any] = {
            "values": self._window_values(ids, a, b),
            "rows": [],
            "coverage": {},
            "partial": False,
            "previous": None,
        }
        if compare:
            pa, pb = a - timedelta(days=n), a - timedelta(days=1)
            res["previous"] = {"values": self._window_values(ids, pa, pb), "rows": []}
        return res

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


def opp(
    oid: str, kind: str, item: str | None = "p1", profit: float | None = 100.0, **kw: Any
) -> dict[str, Any]:
    """A stored opportunity row (synthetic): published unless `outcome` says otherwise."""
    return {
        "id": oid,
        "kind": kind,
        "scope": "product" if item else "shop",
        "item_ids": [item] if item else [],
        "delta_gmv": 1000.0,
        "delta_profit": profit,
        "cost": 50.0,
        "inputs": {},
        "outcome": "published",
        "reason": None,
        "card_code": None,
        **kw,
    }


OPPORTUNITIES = [
    opp("o-roas", "ads_roas_target"),
    opp("o-title", "title", profit=80.0),
    opp("o-remove", "ads_remove_product", profit=60.0),
    opp("o-nope", "cover_image", outcome="below_band", reason="not_estimable", profit=None),
]


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

    async def voucher_income(self, a: date, b: date) -> dict[str, Any]:
        """Synthetic `order_settlements` rows: only days that have an income row count."""
        rows = [r for r in self.entity.get("voucher", []) if a <= r["day"] <= b]
        return {
            "rows": len(rows),
            "orders": sum(r["orders"] for r in rows),
            "gmv": sum(r["gmv"] for r in rows),
            "cost": sum(r["cost"] for r in rows) if rows else None,
            "income_to": max((r["day"] for r in rows), default=None),
        }

    async def voucher_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        return self.entity.get("voucher_codes", [])

    async def campaign_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        return self.entity.get("campaigns", [])

    async def product_profit(self, item: str, a: date, b: date) -> dict[str, Any] | None:
        return self.entity.get("product_profit", {}).get((item, a))

    async def product_profit_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        return self.entity.get("product_rows", [])

    async def budget_days(self, a: date, b: date) -> list[dict[str, Any]]:
        return [r for r in self.entity.get("budget_days", []) if a <= r["day"] <= b]

    async def campaign_products(self, a: date, b: date) -> dict[str, list[str]]:
        return {c["key"]: list(c.get("items") or []) for c in self.entity.get("campaigns", [])}

    # ---- the `metrics.query` / OPP seams (C1): scripted rows, no calculation here

    async def metrics(
        self,
        ids: list[str],
        a: date,
        b: date,
        *,
        scope: str = "shop",
        items: list[str] | None = None,
        channel: str | None = None,
        campaigns: list[str] | None = None,
        group_by: str | None = None,
        compare: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(f"metrics:{group_by}:{','.join(ids)}")
        if group_by == "campaign":
            rows = [
                {
                    "campaign": c["key"],
                    "campaign_name": c["name"],
                    "cost_ads": c["spend"],
                    "ads_gmv_direct": c["gmv"],
                    "roas_direct": c["roas"],
                    "roas_break_even": c["break_even"],
                    "items": c.get("items") or [],
                }
                for c in self.entity.get("campaigns", [])
            ]
            return {"values": {}, "rows": rows, "coverage": {}, "partial": False, "previous": None}
        if group_by == "item":
            rows = []
            for r in self.entity.get("product_rows", []):
                cov = (self.entity.get("coverage") or {}).get(r["item_id"], 1.0)
                rows.append(
                    {
                        "item": r["item_id"],
                        "gmv": r["gmv"],
                        "profit": r["profit"],
                        "cost_ads": r["ad_spend"],
                        "contribution": r["contribution"],
                        "roas_break_even": r["break_even_roas"],
                        "margin": r["margin_pct"],
                        "cost_coverage": cov,
                    }
                )
            return {"values": {}, "rows": rows, "coverage": {}, "partial": False, "previous": None}
        vals = self.entity.get("values")
        if vals is None:
            return await super().metrics(
                ids, a, b, scope=scope, items=items, channel=channel, campaigns=campaigns,
                group_by=group_by, compare=compare,
            )  # fmt: skip
        now = {i: vals.get(i, (None, None))[0] for i in ids}
        before = {i: vals.get(i, (None, None))[1] for i in ids}
        return {
            "values": now,
            "rows": [],
            "coverage": {},
            "partial": False,
            "previous": {"values": before, "rows": [], "coverage": {}, "partial": False}
            if compare
            else None,
        }

    async def opportunities(
        self, *, kind: str | None = None, item: str | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append(f"opportunities:{kind}")
        rows = [dict(o) for o in self.entity.get("opportunities", OPPORTUNITIES)]
        return [
            o
            for o in rows
            if (kind is None or o["kind"] == kind) and (item is None or item in o["item_ids"])
        ]

    async def draft_opportunity(self, opportunity_id: str) -> dict[str, Any]:
        self.calls.append(f"draft:{opportunity_id}")
        opp = next(
            o for o in self.entity.get("opportunities", OPPORTUNITIES) if o["id"] == opportunity_id
        )
        card = (self.entity.get("draft_cards") or {}).get(opp["kind"])
        return {"ok": True, "card": card if card is not None else engine_card()}

    async def compare_options(
        self, kind: str, *, item: str | None = None, points: list[Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append(f"compare:{kind}")
        return {"kind": kind, "options": self.entity.get("compare", {}).get(kind, [])}


def tool_use(name: str, tid: str, **args: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": tid, "name": name, "input": args}


def plan_turn(*items: dict[str, Any]) -> list[dict[str, Any]]:
    return [tool_use("emit_plan", "p1", items=list(items))]


class ScriptedQuery:
    """`ServiceData` with its one metrics read replaced by scripted `query()` output: what the
    delegation (shape, scope, group_by, ids) does is tested, no database."""

    def __new__(cls, script: Callable[..., dict[str, Any]]) -> Any:
        import uuid

        from juli_backend.services.analytics_agent.data_service import ServiceData

        class _Svc(ServiceData):
            def __init__(self) -> None:
                super().__init__(lambda: None, uuid.uuid4())  # type: ignore[arg-type,return-value]
                self.asked: list[dict[str, Any]] = []

            async def metrics(self, ids: list[str], a: date, b: date, **kw: Any) -> dict[str, Any]:
                self.asked.append({"ids": list(ids), "window": (a, b), **kw})
                return script(ids, a, b, **kw)

            async def item_names(self, ids: list[str]) -> dict[str, str]:
                return {i: f"Sản phẩm {i}" for i in ids}

            async def campaign_products(self, a: date, b: date) -> dict[str, list[str]]:
                return {"k1": ["p1"]}

        return _Svc()


def camp(key: str, name: str, spend: float, gmv: float, be: float | None) -> dict[str, Any]:
    """A campaign row in the shape `ServiceData.campaign_rows` returns (synthetic)."""
    from juli_backend.services.analytics_agent.registry_reads import roas_direct

    return {
        "key": key,
        "name": name,
        "spend": spend,
        "gmv": gmv,
        "roas": roas_direct(gmv, spend),
        "break_even": be,
        "profit_after_ads": None if be is None else gmv / be - spend,
        "items": [],
    }
