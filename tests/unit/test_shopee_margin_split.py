"""L1 / A9: a card's Biên đóng góp with and without a shop discount, read through ``query()``
(mocked here). ``unknown`` is a count, never folded into either side. Synthetic numbers."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal as D

import pytest

from juli_backend.services.metrics import query as q
from juli_backend.services.shopee_recommendations import margin_split

SHOP = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
WIN = (date(2026, 3, 1), date(2026, 3, 30))


def _result(rows):
    return q.QueryResult(
        window=WIN, grain="product_channel", values={}, coverage={}, partial=False,
        built_at=None, rows=rows,
    )  # fmt: skip


@pytest.fixture
def fake_query(monkeypatch):
    calls: list[dict] = []

    def install(rows):
        async def fake(session, shop_id, metrics, **kw):
            calls.append({"metrics": list(metrics), **kw})
            return _result(rows)

        monkeypatch.setattr(q, "query", fake)
        return calls

    return install


def _row(key, margin, gmv, orders):
    return {"discounted": key, "margin_contribution": margin, "gmv": D(gmv), "orders": D(orders)}


async def test_with_and_without_come_from_query_and_unknown_is_only_a_count(fake_query):
    calls = fake_query(
        [
            _row("with", D("18.04"), 400, 4),
            _row("without", D("26.5"), 600, 6),
            _row("unknown", D("9"), 50, 2),
        ]
    )
    out = await margin_split.margin_split(None, SHOP, ["p1"], WIN)
    assert out["with"] == {"margin_pct": 18.0, "gmv": 400.0, "orders": 4.0}
    assert out["without"]["margin_pct"] == 26.5
    assert out["unknown"] == {"orders": 2.0, "gmv": 50.0}
    assert "margin_pct" not in out["unknown"]  # never a margin for unknown
    assert calls[0]["group_by"] == "discounted"
    assert calls[0]["metrics"] == ["margin_contribution", "gmv", "orders"]


async def test_zero_unknown_is_not_shown_and_a_missing_side_is_none_not_zero(fake_query):
    fake_query([_row("with", D("10"), 100, 1), _row("unknown", None, 0, 0)])
    out = await margin_split.margin_split(None, SHOP, ["p1"], WIN)
    assert out["unknown"] is None
    assert out["without"] is None  # no purchases without a discount: "—", not 0
    assert out["with"]["margin_pct"] == 10.0


async def test_an_unknown_margin_stays_none(fake_query):
    fake_query([_row("with", None, 100, 1), _row("without", D("5"), 50, 1)])
    out = await margin_split.margin_split(None, SHOP, [], WIN)
    assert out["with"]["margin_pct"] is None and out["without"]["margin_pct"] == 5.0


async def test_several_products_give_no_order_count(fake_query):
    calls = fake_query([_row("with", D("10"), 100, 1), _row("unknown", D("1"), 20, 1)])
    out = await margin_split.margin_split(None, SHOP, ["p1", "p2"], WIN)
    assert "orders" not in calls[0]["metrics"]
    assert out["with"]["orders"] is None
    assert out["unknown"] == {"orders": None, "gmv": 20.0}


async def test_the_cache_asks_once_per_scope(fake_query):
    calls = fake_query([_row("with", D("10"), 100, 1)])
    cache = margin_split.SplitCache(None, SHOP, WIN)
    await cache.of(["b", "a"])
    await cache.of(["a", "b"])
    assert len(calls) == 1
