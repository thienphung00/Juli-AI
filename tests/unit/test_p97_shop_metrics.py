"""P97 D85.2: the ShopMetrics read model and its materialized daily tables. Synthetic data."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
)
from juli_backend.services.shopee_analytics import loaders, materialize, queries, service
from juli_backend.services.shopee_analytics.metrics import allocate
from juli_backend.services.shopee_analytics.stored import RowsNotMaterialized
from juli_backend.services.shopee_analytics.windows import choose_anchor
from tests.support.shopee_analytics import CUR_END, CUR_START, PREV_START, Seeded, seed_shopee_shop

DATASETS = ("shop_overview", "traffic_overview", "shop_traffic")


@pytest.fixture
async def seeded(session) -> Seeded:
    # the raw tables only: these tests build (or check) the stored rows themselves
    return await seed_shopee_shop(session, materialized=False)


# ---------------------------------------------------------------------------------- pure


def test_the_anchor_is_the_oldest_of_the_newest_days_of_the_live_datasets():
    day = date(2026, 11, 4)
    got = choose_anchor(
        {"shop_overview": day - timedelta(days=2), "traffic_overview": day}, DATASETS
    )
    assert got is not None and got.day == day - timedelta(days=2) and got.newest == day
    assert got.limited_by == "shop_overview" and "shop_overview" in got.label()


def test_a_dataset_more_than_three_days_behind_is_stale_and_does_not_hold_the_window_back():
    day = date(2026, 11, 4)
    got = choose_anchor(
        {"shop_overview": day - timedelta(days=9), "traffic_overview": day}, DATASETS
    )
    assert got is not None and got.day == day and got.stale == ("shop_overview",)


def test_no_dataset_no_anchor():
    assert choose_anchor({}, DATASETS) is None


@pytest.mark.parametrize("total", [Decimal(1_000_000), Decimal("999999.5"), Decimal(7)])
def test_the_allocation_adds_up_to_the_whole_dong(total):
    parts = {"a": Decimal(333), "b": Decimal(333), "c": Decimal(334), "d": Decimal(1)}
    out = allocate(total, parts)
    assert sum(out.values()) == total.quantize(Decimal(1), rounding="ROUND_HALF_UP")
    assert all(v == v.to_integral_value() for v in out.values())


# ------------------------------------------------------------------------------- tables


async def _shop_rows(session, shop_id):
    return list(
        (
            await session.execute(
                select(ShopeeShopMetricsDaily)
                .where(ShopeeShopMetricsDaily.shop_id == shop_id)
                .order_by(ShopeeShopMetricsDaily.day)
            )
        ).scalars()
    )


async def _product_rows(session, shop_id):
    return list(
        (
            await session.execute(
                select(ShopeeProductMetricsDaily).where(
                    ShopeeProductMetricsDaily.shop_id == shop_id
                )
            )
        ).scalars()
    )


async def test_the_rebuild_is_idempotent(session, seeded):
    first = await materialize.backfill_shop(session, seeded.shop_id)
    snap = [
        (r.day, r.gmv, r.orders, r.views, r.profit, r.complete)
        for r in await _shop_rows(session, seeded.shop_id)
    ]
    psnap = sorted(
        (p.day, p.item_id, p.gmv, p.orders, p.units)
        for p in await _product_rows(session, seeded.shop_id)
    )
    second = await materialize.backfill_shop(session, seeded.shop_id)
    assert first.days_written == second.days_written > 0
    again = [
        (r.day, r.gmv, r.orders, r.views, r.profit, r.complete)
        for r in await _shop_rows(session, seeded.shop_id)
    ]
    assert again == snap
    assert (
        sorted(
            (p.day, p.item_id, p.gmv, p.orders, p.units)
            for p in await _product_rows(session, seeded.shop_id)
        )
        == psnap
    )


async def test_the_product_rows_of_a_day_add_up_to_the_shop_row(session, seeded):
    await materialize.backfill_shop(session, seeded.shop_id)
    shop = {r.day: r for r in await _shop_rows(session, seeded.shop_id)}
    by_day: dict[date, Decimal] = {}
    for p in await _product_rows(session, seeded.shop_id):
        by_day[p.day] = by_day.get(p.day, Decimal(0)) + p.gmv
    assert shop and set(by_day) == set(shop)
    for day, row in shop.items():
        assert by_day[day] == row.gmv, day
    assert any(p.item_id == RESIDUAL_ITEM for p in await _product_rows(session, seeded.shop_id))


async def test_a_day_is_complete_only_when_shopee_posted_its_totals(session, seeded):
    await materialize.backfill_shop(session, seeded.shop_id)
    rows = {r.day: r for r in await _shop_rows(session, seeded.shop_id)}
    assert rows[CUR_END].complete is True
    assert rows[CUR_END].sources["gmv"] == "shop_totals"
    assert await loaders.default_as_of(session, seeded.shop_id) == CUR_END


# ------------------------------------------------------------------- every surface agrees


def _core(body):  # the numbers every surface must agree on
    return body


async def test_every_surface_shows_the_same_core_metrics(session, seeded, monkeypatch):
    from juli_backend.services.shopee_builder import service as builder
    from juli_backend.services.shopee_recommendations import config
    from juli_backend.services.shopee_recommendations.loader import load_env

    monkeypatch.setattr(config, "HISTORY_DAYS", 7)  # the cards' window = the 7d the others show

    kw = {"period": "7d", "as_of": CUR_END}
    # P99b: before the rows are built every screen shows the missing-rows state, never the raw
    # tables' figures; once they are built every surface reads the same rows
    with pytest.raises(RowsNotMaterialized):
        await queries.overview(session, seeded.shop_id, **kw)
    with pytest.raises(RowsNotMaterialized):
        await load_env(session, seeded.shop_id, as_of=CUR_END)
    for materialized in (True,):
        await materialize.backfill_shop(session, seeded.shop_id)
        ov = await queries.overview(session, seeded.shop_id, **kw)
        mx = await queries.matrix(session, seeded.shop_id, **kw)
        rk = await queries.ranking(session, seeded.shop_id, **kw)
        rk_aov = await queries.ranking(session, seeded.shop_id, xep_theo="aov", **kw)
        env = await load_env(session, seeded.shop_id, as_of=CUR_END)
        sm = ov["shop_metrics"]
        assert materialized and sm["read_from"] == "tables"
        gmv, orders, aov = sm["gmv"], sm["orders"], sm["aov"]
        assert gmv and orders and aov == pytest.approx(gmv / orders, abs=0.01)
        # Tổng quan
        assert ov["kpi_strip"]["gmv"]["value"] == gmv
        assert ov["kpi_strip"]["orders"]["value"] == orders
        assert ov["kpi_strip"]["aov"]["value"] == pytest.approx(aov, abs=0.01)
        assert ov["gmv"]["shopee_gmv"] == gmv and ov["gmv"]["shopee_orders"] == orders
        assert ov["gmv"]["aov_gmv"] == pytest.approx(aov, abs=0.01)
        assert ov["flows"]["chain"]["aov"] == pytest.approx(aov, abs=0.01)
        assert ov["kpi_strip"]["views"]["value"] == sm["views"]
        assert ov["kpi_strip"]["ctr"]["value"] == pytest.approx(sm["ctr"], abs=0.01)
        assert ov["kpi_strip"]["ctor"]["value"] == pytest.approx(sm["ctor"], abs=0.01)
        # Sản phẩm: the products add up to the shop (less the stored residual)
        assert mx["sums"]["gmv_shop"] == gmv
        listed = mx["sums"]["gmv_shopee_products"] + mx["excluded"]["gmv"]
        assert listed + (sm["unattributed_gmv"] or 0) == pytest.approx(gmv, abs=1)
        # Phân tích (ranking cell of the "all" source)
        cell = rk["cell"]["now"]
        assert cell == pytest.approx(gmv / 7, abs=0.01)
        assert rk_aov["cell"]["now"] == pytest.approx(aov, abs=0.01)
        # Kế hoạch / cards read the same environment
        assert env is not None
        assert int(env.metrics.gmv) == int(gmv) and env.metrics.orders == orders
        assert float(env.metrics.aov) == pytest.approx(aov, abs=0.01)
        # builder catalogue: the 90-day GMV column
        picker = await builder.products(session, seeded.shop_id, as_of=CUR_END)
        assert picker["products"]


# ---------------------------------------------------------------------------- the hook


async def test_the_ingest_hook_rebuilds_the_written_days_and_ignores_period_files(session, seeded):
    await materialize.after_ingest(
        session, seeded.shop_id, platform="shopee", dataset="shop_overview_period",
        start=CUR_START, end=CUR_END,
    )  # fmt: skip
    assert await _shop_rows(session, seeded.shop_id) == []
    await materialize.after_ingest(
        session, seeded.shop_id, platform="shopee", dataset="traffic_overview",
        start=CUR_END - timedelta(days=1), end=CUR_END,
    )  # fmt: skip
    assert [r.day for r in await _shop_rows(session, seeded.shop_id)] == [
        CUR_END - timedelta(days=1),
        CUR_END,
    ]
    await materialize.after_ingest(
        session, seeded.shop_id, platform="tiktok", dataset="traffic_overview",
        start=PREV_START, end=PREV_START,
    )  # fmt: skip
    assert len(await _shop_rows(session, seeded.shop_id)) == 2


async def test_a_failed_rebuild_never_fails_the_ingest(session, seeded, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("derived table down")

    monkeypatch.setattr(materialize, "rebuild_days", boom)
    await materialize.after_ingest(
        session, seeded.shop_id, platform="shopee", dataset="traffic_overview",
        start=CUR_END, end=CUR_END,
    )  # fmt: skip
    assert await _shop_rows(session, seeded.shop_id) == []  # nothing derived, nothing raised


async def test_the_window_is_read_from_the_tables_only_when_every_day_is_complete(session, seeded):
    await materialize.backfill_shop(session, seeded.shop_id)
    full = await service.load_period_data(
        session,
        seeded.shop_id,
        await service.resolve(session, seeded.shop_id, period="7d", as_of=CUR_END),
    )
    assert full.stored is not None and full.stored.usable
    longer = await service.load_period_data(
        session,
        seeded.shop_id,
        await service.resolve(session, seeded.shop_id, period="30d", as_of=CUR_END),
    )
    assert longer.stored is not None and not longer.stored.usable  # 16 stored days of 30
