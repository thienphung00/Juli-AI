"""P98 / ADR-122 d.3 + d.11.3: the funnel per traffic source, stored per day, and the daily check.

Synthetic data only (``tests/support/shopee_analytics``).
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update

from juli_backend.models.shopee_metrics import (
    FUNNEL_SOURCES,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
)
from juli_backend.services.shopee_analytics import funnel_check, materialize
from juli_backend.services.shopee_analytics.materialize import AdsDay, split_sources
from juli_backend.services.shopee_builder.engine.contract import SOURCES
from juli_backend.services.shopee_profit.flows import FlowRow, FlowSource, build_flow_tables
from tests.support.shopee_analytics import CUR_END, CUR_START, DAILY_SHOP_GMV, seed_shopee_shop

REPO = Path(__file__).resolve().parents[2]
RES = "chenh_lech_nguon"


def _table(*, khac=(1000, 50, 3, 200_000), trang=(100, 10, 1, 30_000), video=(40, 8, 1, 20_000)):
    """Shop traffic: Thẻ sản phẩm total (incl. Trang shop), Trang shop, Video."""
    rows = [
        FlowRow("s", FlowSource.THE_SAN_PHAM_TOTAL, khac[2], Decimal(khac[3]), khac[0], khac[1]),
        FlowRow("s", FlowSource.TRANG_SHOP, trang[2], Decimal(trang[3]), trang[0], trang[1]),
        FlowRow("s", FlowSource.VIDEO, video[2], Decimal(video[3]), video[0], video[1]),
    ]
    return build_flow_tables(rows, shop_gmv=Decimal(0)).shop


def _by(rows):
    return {r.source: r for r in rows}


# ------------------------------------------------------------------------------- pure


def test_the_model_sources_are_the_contract_sources():
    assert FUNNEL_SOURCES == SOURCES


def test_sources_keep_their_own_numbers_when_shopee_assigns_less_and_the_rest_is_residual():
    got = _by(split_sources(_table(), 6, Decimal(300_000), None))
    assert list(got) == list(SOURCES)
    assert got["the_san_pham_khac"].orders == 2 and got["the_san_pham_khac"].gmv == 170_000
    assert got["the_san_pham_khac"].views == 900 and got["the_san_pham_khac"].clicks == 40
    assert got["trang_shop"].orders == 1 and got["video"].orders == 1
    assert got[RES].orders == 2 and got[RES].gmv == 300_000 - 220_000
    assert got[RES].views is None and got[RES].clicks is None
    assert got["live"].views is None and got["live"].orders == 0
    assert not any(r.scaled for r in got.values())


@pytest.mark.parametrize(
    ("orders", "gmv"),
    [(3, Decimal(150_001)), (7, Decimal("299999.50")), (0, Decimal(0)), (1, Decimal(13))],
)
def test_sources_sum_exactly_to_the_totals(orders, gmv):
    rows = split_sources(_table(), orders, gmv, Decimal("12345.67"))
    assert sum(r.orders for r in rows) == orders
    assert sum((r.gmv for r in rows), Decimal(0)) == gmv
    assert sum((r.profit or Decimal(0) for r in rows), Decimal(0)) == Decimal("12345.67")
    assert all(r.orders >= 0 for r in rows)


def test_when_shopee_assigns_more_than_the_totals_the_sources_are_scaled_down_no_residual():
    got = _by(split_sources(_table(), 2, Decimal(110_000), None))
    assert sum(r.orders for r in got.values()) == 2
    assert got[RES].orders == 0 and got[RES].gmv == 0
    assert got["the_san_pham_khac"].scaled and got["the_san_pham_khac"].gmv < 170_000
    # views and clicks are never scaled
    assert got["the_san_pham_khac"].views == 900


def test_no_traffic_puts_everything_in_the_residual_and_views_stay_unknown():
    got = _by(split_sources(None, 4, Decimal(80_000), Decimal(9_000)))
    assert got[RES].orders == 4 and got[RES].gmv == 80_000 and got[RES].profit == 9_000
    assert all(got[s].views is None for s in SOURCES)
    assert all(got[s].orders == 0 for s in SOURCES if s != RES)


def test_profit_follows_gmv_and_none_means_not_computed():
    got = _by(split_sources(_table(), 5, Decimal(220_000), Decimal(22_000)))
    assert got["the_san_pham_khac"].profit == 17_000
    assert all(r.profit is None for r in split_sources(_table(), 5, Decimal(1), None))


def test_unknown_totals_mean_zero_not_a_crash():
    rows = split_sources(_table(), None, None, None)
    assert sum(r.orders for r in rows) == 0 and sum(r.gmv for r in rows) == 0


def test_the_row_builder_puts_the_ads_share_on_the_card_source_only():
    view_rows = materialize.source_rows(
        split_sources(_table(), 5, Decimal(220_000), None),
        shop_id=uuid.uuid4(),
        day=CUR_END,
        item_id=None,
        ads=AdsDay(2000, 40, 2, Decimal(150_000), Decimal(30_000)),
    )
    by = {r["source"]: r for r in view_rows}
    assert by["the_san_pham_khac"]["ads_views"] == 2000
    assert by["the_san_pham_khac"]["ads_spend"] == Decimal("30000.00")
    assert all(by[s]["ads_spend"] is None for s in SOURCES if s != "the_san_pham_khac")
    assert all(r["item_id"] is None for r in view_rows)


# ------------------------------------------------------------------------------ tables


@pytest.fixture
async def seeded(session):
    return await seed_shopee_shop(session)


async def _source_rows(session, shop_id, day=None):
    q = select(ShopeeSourceMetricsDaily).where(ShopeeSourceMetricsDaily.shop_id == shop_id)
    if day is not None:
        q = q.where(ShopeeSourceMetricsDaily.day == day)
    return list((await session.execute(q)).scalars())


async def test_the_rebuild_writes_six_shop_sources_per_day_summing_to_the_shop_row(session, seeded):
    await materialize.backfill_shop(session, seeded.shop_id)
    shop = {
        r.day: r
        for r in (
            await session.execute(
                select(ShopeeShopMetricsDaily).where(
                    ShopeeShopMetricsDaily.shop_id == seeded.shop_id
                )
            )
        ).scalars()
    }
    rows = [r for r in await _source_rows(session, seeded.shop_id) if r.item_id is None]
    assert shop and {r.day for r in rows} == set(shop)
    for day, s in shop.items():
        mine = _by(r for r in rows if r.day == day)
        assert set(mine) == set(SOURCES)
        assert sum(r.orders for r in mine.values()) == s.orders
        assert sum((r.gmv for r in mine.values()), Decimal(0)) == s.gmv
    end = _by(r for r in rows if r.day == CUR_END)
    assert end[RES].gmv == DAILY_SHOP_GMV - 270_000  # what Shopee's sources leave out
    assert end["the_san_pham_khac"].views == 900 and end["the_san_pham_khac"].clicks == 40
    assert end["the_san_pham_khac"].ads_views == 2000
    assert end["the_san_pham_khac"].ads_spend == 30_000 and end["video"].ads_spend is None


async def test_the_source_rebuild_is_idempotent(session, seeded):
    await materialize.backfill_shop(session, seeded.shop_id)
    first = sorted(
        (r.day, r.item_id or "", r.source, r.orders, r.gmv)
        for r in await _source_rows(session, seeded.shop_id)
    )
    await materialize.backfill_shop(session, seeded.shop_id)
    again = sorted(
        (r.day, r.item_id or "", r.source, r.orders, r.gmv)
        for r in await _source_rows(session, seeded.shop_id)
    )
    assert first == again and len(first) == len(
        {(d, i, s) for d, i, s, _, _ in first}
    )  # one row per key, NULL item included


async def test_the_ingest_hook_fills_the_source_rows(session, seeded):
    await materialize.after_ingest(
        session, seeded.shop_id, platform="shopee", dataset="traffic_overview",
        start=CUR_END, end=CUR_END,
    )  # fmt: skip
    assert {r.source for r in await _source_rows(session, seeded.shop_id, CUR_END)} == set(SOURCES)


# ------------------------------------------------------------------------- funnel check


async def test_a_fresh_rebuild_has_no_mismatch(session, seeded):
    await materialize.backfill_shop(session, seeded.shop_id)
    assert await funnel_check.check_day(session, seeded.shop_id, CUR_END) == []


async def test_sources_that_no_longer_sum_to_the_shop_are_a_mismatch_and_are_not_corrected(
    session, seeded, caplog
):
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.execute(
        update(ShopeeSourceMetricsDaily)
        .where(
            ShopeeSourceMetricsDaily.shop_id == seeded.shop_id,
            ShopeeSourceMetricsDaily.day == CUR_END,
            ShopeeSourceMetricsDaily.source == "video",
            ShopeeSourceMetricsDaily.item_id.is_(None),
        )
        .values(orders=9)
    )
    with caplog.at_level(logging.WARNING):
        got = await funnel_check.check_day(session, seeded.shop_id, CUR_END)
    assert any(m.kind == "sources_sum" and m.metric == "orders" for m in got)
    logged = [r for r in caplog.records if r.getMessage() == "shopee_funnel_mismatch"]
    assert logged and logged[0].kind == "sources_sum" and logged[0].shop_id == str(seeded.shop_id)
    still = _by(
        r for r in await _source_rows(session, seeded.shop_id, CUR_END) if r.item_id is None
    )
    assert still["video"].orders == 9  # never corrected


async def test_a_gap_above_one_percent_to_shopee_totals_or_traffic_is_a_mismatch(session, seeded):
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.execute(
        update(ShopeeShopMetricsDaily)
        .where(
            ShopeeShopMetricsDaily.shop_id == seeded.shop_id, ShopeeShopMetricsDaily.day == CUR_END
        )
        .values(gmv=DAILY_SHOP_GMV * Decimal("1.02"))
    )
    await session.execute(
        update(ShopeeSourceMetricsDaily)
        .where(
            ShopeeSourceMetricsDaily.shop_id == seeded.shop_id,
            ShopeeSourceMetricsDaily.day == CUR_END,
            ShopeeSourceMetricsDaily.source == "the_san_pham_khac",
            ShopeeSourceMetricsDaily.item_id.is_(None),
        )
        .values(views=905)  # 0.6 %: inside the tolerance
    )
    got = await funnel_check.check_day(session, seeded.shop_id, CUR_END)
    kinds = {(m.kind, m.metric) for m in got}
    assert ("shop_totals", "gmv") in kinds
    assert not any(m.kind == "traffic" for m in got)
    await session.execute(
        update(ShopeeSourceMetricsDaily)
        .where(
            ShopeeSourceMetricsDaily.shop_id == seeded.shop_id,
            ShopeeSourceMetricsDaily.day == CUR_END,
            ShopeeSourceMetricsDaily.source == "the_san_pham_khac",
            ShopeeSourceMetricsDaily.item_id.is_(None),
        )
        .values(views=950)
    )
    got = await funnel_check.check_day(session, seeded.shop_id, CUR_END)
    traffic = [m for m in got if m.kind == "traffic"]
    assert traffic and traffic[0].source == "the_san_pham_khac" and traffic[0].metric == "views"
    assert traffic[0].gap_pct is not None and traffic[0].gap_pct > 1


async def test_a_built_day_without_source_rows_is_a_mismatch(session, seeded):
    await materialize.rebuild_days(session, seeded.shop_id, [CUR_END])
    for r in await _source_rows(session, seeded.shop_id, CUR_END):
        await session.delete(r)
    await session.flush()
    got = await funnel_check.check_day(session, seeded.shop_id, CUR_END)
    assert [m.kind for m in got] == ["missing_rows"]


async def test_an_unbuilt_day_is_not_checked(session, seeded):
    assert (
        await funnel_check.check_day(session, seeded.shop_id, CUR_START - timedelta(days=30)) == []
    )


async def test_the_check_never_raises(session, seeded, monkeypatch, caplog):
    async def boom(*a, **k):
        raise RuntimeError("check down")

    monkeypatch.setattr(funnel_check, "check_day", boom)
    assert await funnel_check.check_days(session, seeded.shop_id, [CUR_END]) == []
    await materialize.after_ingest(
        session, seeded.shop_id, platform="shopee", dataset="traffic_overview",
        start=CUR_END, end=CUR_END,
    )  # fmt: skip
    assert await _source_rows(session, seeded.shop_id, CUR_END)  # the rebuild still landed


# ---------------------------------------------------------------------------- migration


def test_migration_126_is_additive_and_reversible():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    versions = REPO / "backend/src/juli_backend/database/migrations/versions"
    path = versions / "126_shopee_source_funnel.py"
    spec = importlib.util.spec_from_file_location("mig126", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "126_shopee_source_funnel" and len(mod.revision) <= 32
    assert mod.down_revision == "125_reco_plan_groups"
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([path])
    assert [f.render() for f in result.findings] == [] and result.accepted
    src = path.read_text("utf-8")
    up = src.split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("UPDATE public", "DELETE FROM", "op.drop_table", "op.drop_column"):
        assert verb not in up, verb
    assert mod.TENANT_TABLES == ("shopee_source_metrics_daily",)
    assert "ENABLE ROW LEVEL SECURITY" in src and "GRANT SELECT, INSERT, UPDATE" in src
    assert "item_id IS NULL" in src and "item_id IS NOT NULL" in src
    assert TABLE_CLASSIFICATION_MAP[("public", "shopee_source_metrics_daily")] == "tenant_direct"
    for column in ShopeeSourceMetricsDaily.__table__.columns.keys():
        assert f'"{column}"' in src, column
    for source in SOURCES:
        assert f"'{source}'" in src
    tail = versions.parent / "deferred/101_write_mode_backfill.py"
    assert 'down_revision: str | None = "127_card_content_specs"' in tail.read_text("utf-8")


async def test_product_sources_come_from_the_daily_item_traffic_and_sum_to_the_product_row(
    session, seeded
):
    from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily
    from tests.support.shopee_analytics import _daily

    item = "1001"
    session.add_all(
        [
            _daily(seeded.shop_id, CUR_END, "product_card", "all", impressions=500, clicks=25,
                   orders=1, gmv=60_000, dataset="item_traffic_sources", item_id=item),
            _daily(seeded.shop_id, CUR_END, "product_card", "shop_page", impressions=50,
                   clicks=5, orders=0, gmv=0, dataset="item_traffic_sources", item_id=item),
        ]
    )  # fmt: skip
    await session.flush()
    await materialize.rebuild_days(session, seeded.shop_id, [CUR_END])
    rows = [r for r in await _source_rows(session, seeded.shop_id, CUR_END) if r.item_id == item]
    assert {r.source for r in rows} == set(SOURCES)
    prod = (
        await session.execute(
            select(ShopeeProductMetricsDaily).where(
                ShopeeProductMetricsDaily.shop_id == seeded.shop_id,
                ShopeeProductMetricsDaily.day == CUR_END,
                ShopeeProductMetricsDaily.item_id == item,
            )
        )
    ).scalar_one()
    assert sum(r.orders for r in rows) == prod.orders
    assert sum((r.gmv for r in rows), Decimal(0)) == prod.gmv
    by = _by(rows)
    assert by["the_san_pham_khac"].views == 450 and by["trang_shop"].clicks == 5
    assert await funnel_check.check_day(session, seeded.shop_id, CUR_END) == []
