"""P98 / ADR-122 d.11.2 (SQLite variant): every screen shows the same funnel numbers.

The synthetic shop is rebuilt into the materialized tables and read through Tổng quan, Phân tích,
Sản phẩm, the Kế hoạch base and the builder "before". The Postgres twin is
``tests/integration/test_shopee_funnel_cross_screen_db.py``.
"""

from __future__ import annotations

import pytest

from juli_backend.services.shopee_analytics import materialize
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop
from tests.support.shopee_cross_screen import FIELDS, agreed, collect_shop


@pytest.fixture
async def built(session):
    seeded = await seed_shopee_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    return seeded


async def test_every_screen_shows_the_same_funnel_numbers(session, built, monkeypatch):
    from juli_backend.services.shopee_recommendations import config

    monkeypatch.setattr(config, "HISTORY_DAYS", 7)  # the plan base reads the window the others show
    surfaces, waterfalls = await collect_shop(session, built.shop_id, CUR_END, days=7)
    assert {s.name for s in surfaces} == {
        "tong_quan", "phan_tich", "san_pham", "ke_hoach", "builder_before",
    }  # fmt: skip
    for field in FIELDS:
        # Tổng quan's strip and Phân tích's cell round a ratio to 2 decimals (see the xfail below)
        shown = agreed(surfaces, field, tol=0.005, abs_tol=0.005 if field in ("ctr", "ctor") else 0)
        # the field is not absent everywhere, and the screens that must carry it do
        assert shown, field
    # Đơn, GMV and Lượt xem are carried by at least Tổng quan, Sản phẩm, Kế hoạch and the builder
    for field in ("views", "orders", "gmv"):
        assert {"tong_quan", "ke_hoach", "builder_before"} <= set(agreed(surfaces, field, tol=0)), (
            field
        )


@pytest.mark.xfail(
    strict=True,
    reason="found by d.11.2: Tổng quan's KPI strip and Phân tích's ranking cell round CTR / CTOR "
    "to 2 decimals as fractions (0.0636 -> 0.06) while Sản phẩm / Kế hoạch / the builder keep 6",
)
async def test_ctr_and_ctor_carry_full_precision_on_every_screen(session, built, monkeypatch):
    from juli_backend.services.shopee_recommendations import config

    monkeypatch.setattr(config, "HISTORY_DAYS", 7)
    surfaces, waterfalls = await collect_shop(session, built.shop_id, CUR_END, days=7)
    for field in ("ctr", "ctor"):
        agreed(surfaces, field, tol=1e-4)


@pytest.mark.xfail(
    strict=True,
    reason="found by d.11.2: Lợi nhuận has two definitions: the ShopMetrics "
    "profit (Sản phẩm, Kế hoạch) and the waterfall block / Phân tích ranking (delivered lines)",
)
async def test_the_waterfall_profit_equals_the_shop_metrics_profit(session, built, monkeypatch):
    from juli_backend.services.shopee_recommendations import config

    monkeypatch.setattr(config, "HISTORY_DAYS", 7)
    surfaces, waterfalls = await collect_shop(session, built.shop_id, CUR_END, days=7)
    want = next(s for s in surfaces if s.name == "tong_quan").values["profit"]
    for name, value in waterfalls.items():
        assert value == pytest.approx(want, rel=0.005), name
