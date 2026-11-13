"""P99b (owner 2026-11-10): never show wrong information on error or missing data. A window whose
data days have no stored daily rows is a state (``rows_not_materialized``), not figures from the raw
tables; an unknown stays null with a reason (no giá vốn, no traffic, no rows, a card without a
result, an empty plan). Synthetic reco shop only (SQLite, invented figures)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete

from juli_backend.api.routes import shopee_analytics_common as common
from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.services.shopee_analytics import (
    RowsNotMaterialized,
    loaders,
    materialize,
    service,
)
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine_families import integrate
from juli_backend.services.shopee_recommendations import plan_aggregate as pa
from juli_backend.services.shopee_recommendations import plans
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p99_one_base import _save_and_plan
from tests.unit.test_p99b_plan_horizon import _voucher
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW

WINDOW = Window(AS_OF - timedelta(days=29), AS_OF)


# ------------------------------------------------------------------------------------ pure


@dataclass
class _Base:
    totals: dict[str, D | None]
    days: int = 0
    sources: tuple[Any, ...] = ()

    def total(self, name: str) -> D | None:
        if name not in self.totals:
            raise AttributeError(name)
        return self.totals[name]


def test_no_order_on_the_days_with_costs_is_an_unknown_profit_per_order_not_every_order():
    base = _Base({"orders": D(100), "profit": D(0), "profit_orders": D(0)}, days=30)
    assert integrate.profit_per_order(base) is None


def _env(margin_rate):
    profit = SimpleNamespace(margin_rate=margin_rate, buyer_paid_covered=D(8_000_000))
    return SimpleNamespace(
        shop_gmv_30d=D(10_000_000), shop_orders_30d=100, view=SimpleNamespace(profit=profit)
    )


def test_no_gia_von_leaves_the_plans_margin_and_profit_unknown_never_a_fallback():
    total = {"p50": {"dgmv": 500_000.0, "dorders": 5.0, "dprofit": None}}
    d = pa.result_deltas(_env(D("0.3")), total)
    assert d["bien"] is None and d["gmv"] == 500_000 and d["aov"] is not None
    unknown_orders = {"p50": {"dgmv": None, "dorders": None, "dprofit": None}}
    d = pa.result_deltas(_env(D("0.3")), unknown_orders)
    assert d == {"gmv": None, "orders": None, "aov": None, "bien": None}
    after = pa._after({"gmv_30d": 1.0, "orders_30d": 10, "margin_pct": 30.0}, d)
    assert after["gmv_30d"] is None and after["orders_30d"] is None
    assert after["margin_pct"] is None


def test_no_traffic_keeps_the_after_funnel_unknown():
    t = pa.combine_counted(
        [pa.Counted("a", {q: {"dgmv": 1.0, "dorders": 1.0, "dprofit": 1.0, "dviews": None,
                             "dclicks": None} for q in ("p10", "p50", "p90")}, 30, 0.0)]
    )  # fmt: skip
    after = pa.after_funnel({"gmv_30d": 10.0, "orders_30d": 2, "views_30d": 100,
                             "clicks_30d": 10, "profit_30d": 5.0}, t)  # fmt: skip
    assert after["views_30d"] is None and after["ctr"] is None and after["ctor"] is None


def test_the_missing_rows_state_maps_to_a_409_with_the_vietnamese_message():
    exc = RowsNotMaterialized(WINDOW, [AS_OF])
    http = common.refusal(exc)
    assert http.status_code == 409
    assert http.detail["code"] == "rows_not_materialized"
    assert http.detail["message"] == "Chưa có số liệu theo ngày cho khoảng này — đang tính lại."
    assert http.detail["missing_days"] == 1


# ------------------------------------------------------------------------------- the shop


@pytest.fixture
async def raw_shop(session):
    """The shop with its raw tables only: no stored daily row has been built."""
    seeded = await seed_reco_shop(session, materialized=False)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded


async def _view(session, shop_id, rows):
    ctx = await loaders.load_context(session, shop_id)
    return await service.load_view(session, shop_id, ctx, WINDOW, funnel=True, rows=rows)


async def test_a_screen_window_without_stored_rows_is_the_missing_state(session, raw_shop):
    with pytest.raises(RowsNotMaterialized) as caught:
        await _view(session, raw_shop.shop_id, None)  # a screen: "require"
    assert caught.value.missing and caught.value.json()["code"] == "rows_not_materialized"
    # the builder / Kế hoạch base carries it too
    with pytest.raises(RowsNotMaterialized):
        await load_env(session, raw_shop.shop_id, as_of=AS_OF)


async def test_a_comparison_window_without_rows_is_withheld_not_compared(session, raw_shop):
    view = await _view(session, raw_shop.shop_id, "soft")
    assert view.rows_missing is True and view.comparable_as_previous is False
    # the metrics rebuild still reads the raw tables
    raw = await _view(session, raw_shop.shop_id, "raw")
    assert raw.rows_missing is False and raw.metrics.read_from == "raw"


async def test_once_every_data_day_has_its_row_the_window_reads_the_rows(session, raw_shop):
    await materialize.backfill_shop(session, raw_shop.shop_id)
    await session.commit()
    view = await _view(session, raw_shop.shop_id, None)
    assert view.rows_missing is False and view.metrics.read_from == "tables"


async def test_a_plan_whose_window_lost_a_row_shows_the_state_and_no_figures(session, raw_shop):
    await materialize.backfill_shop(session, raw_shop.shop_id)
    await session.commit()
    _, planned = await _save_and_plan(session, raw_shop, _voucher(NOW.date(), 7))
    assert planned["_aggregate"]["n_cards"] == 1
    await session.execute(
        delete(ShopeeShopMetricsDaily).where(
            ShopeeShopMetricsDaily.shop_id == raw_shop.shop_id,
            # a day inside the window (the anchor itself would just move the window back)
            ShopeeShopMetricsDaily.day == AS_OF - timedelta(days=3),
        )
    )
    await session.commit()
    got = await plans.get_plan(session, raw_shop.shop_id, now=NOW)
    agg = got["aggregate"]
    assert agg["data_missing"]["code"] == "rows_not_materialized"
    assert agg["today"] is None and agg["after"] is None and agg["cost"] is None
    assert agg["cards"] == [] and agg["n_cards"] == 1
    card = got["cards"][0]
    assert card["card_id"] == planned["card_id"] and card["evaluation"] is None
    assert uuid.UUID(card["card_id"])
