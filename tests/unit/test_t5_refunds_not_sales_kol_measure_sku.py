"""T9 / owner 2026-11-18: a refund status is no sale, also on the KOL tab, the KOL pool, the KOL
card measurement, the per-item card measurement days and the SKU export. A ``refunded_accepted``
line inside the window must not raise orders, GMV or units anywhere here.

SQLite flows on the synthetic reco shop with the invented creators of ``test_shopee_kol``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from juli_backend.services.ingest.kol_key import kol_key
from juli_backend.services.shopee_analytics import kol, queries
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_analytics import CUR_START, _line
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_kol import ALPHA, _kol_line, _row, _seed

REFUND = "refunded_accepted"


@pytest.fixture
async def shop(session):
    return await _seed(session)


async def _add_alpha_refund(session, shop) -> None:
    session.add(
        _kol_line(
            shop.shop_id, 901, CUR_START, "G1", ALPHA, "Shopee Video", deal=90_000, status=REFUND
        )
    )
    await session.commit()


async def test_the_kol_table_row_leaves_a_refund_out_of_orders_units_and_gmv(shop, session):
    await _add_alpha_refund(session, shop)
    body = await queries.kol_table(session, shop.shop_id, as_of=AS_OF)
    a = _row(body, ALPHA, "1001")
    assert (a["orders"], a["units"], a["gmv"]) == (12, 12, 1_080_000)
    assert a["pair_orders"] == 12


async def test_the_kol_pool_pair_and_product_leave_a_refund_out(shop, session):
    await _add_alpha_refund(session, shop)
    env = await load_env(session, shop.shop_id, as_of=AS_OF)
    assert env is not None and env.kol is not None
    pair = env.kol.pairs[(kol_key(ALPHA), "1001")]
    assert (pair.orders, pair.units, pair.gmv) == (12, 12, Decimal(1_080_000))
    assert env.kol.kols[kol_key(ALPHA)].line_orders == 14  # 12 G1 + 2 N1, not the refund


async def test_the_kol_card_measurement_skips_a_refund(shop, session):
    await _add_alpha_refund(session, shop)
    series = await kol.pair_daily(
        session, shop.shop_id, kol_key(ALPHA), "sku:G1", date(2026, 10, 1), date(2026, 10, 7)
    )
    assert series[date(2026, 10, 1)] == {"orders": 12, "units": 12, "gmv": Decimal(1_080_000)}


async def test_the_item_measurement_days_skip_a_refund(session):
    from juli_backend.services.shopee_recommendations.measure import load_item_days

    seeded = await seed_reco_shop(session)
    before = await load_item_days(session, seeded.shop_id, CUR_START, CUR_START)
    session.add(_line(seeded.shop_id, 902, CUR_START, "G1", status=REFUND))
    await session.flush()
    after = await load_item_days(session, seeded.shop_id, CUR_START, CUR_START)
    was, now = before["1001"][CUR_START], after["1001"][CUR_START]
    assert (now.orders, now.gmv) == (was.orders, was.gmv)


async def test_the_sku_export_skips_a_refund_in_units_and_revenue(session):
    from juli_backend.services.exports.sku import sku_figures
    from juli_backend.services.shopee_analytics import loaders, service
    from juli_backend.services.shopee_analytics.windows import Window

    seeded = await seed_reco_shop(session)
    window = Window(CUR_START, CUR_START)
    ctx = await loaders.load_context(session, seeded.shop_id)

    async def g1() -> tuple[int, Decimal]:
        view = await service.load_view(session, seeded.shop_id, ctx, window)
        figs = await sku_figures(session, seeded.shop_id, view, window)
        rows = [f for (item, _, _), f in figs.items() if item == "1001"]
        return sum(f.units for f in rows), sum((f.revenue for f in rows), Decimal(0))

    before = await g1()
    session.add(_line(seeded.shop_id, 903, CUR_START, "G1", status=REFUND))
    await session.flush()
    assert await g1() == before
