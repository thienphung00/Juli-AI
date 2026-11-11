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
        # one number per field: ratios unrounded, Lợi nhuận = ShopMetrics (d.14)
        shown = agreed(surfaces, field, tol=0.005 if field in ("profit", "aov") else 1e-4)
        # the field is not absent everywhere, and the screens that must carry it do
        assert shown, field
    # Đơn, GMV and Lượt xem are carried by at least Tổng quan, Sản phẩm, Kế hoạch and the builder
    for field in ("views", "orders", "gmv"):
        assert {"tong_quan", "ke_hoach", "builder_before"} <= set(agreed(surfaces, field, tol=0)), (
            field
        )


async def test_ctr_and_ctor_carry_full_precision_on_every_screen(session, built, monkeypatch):
    from juli_backend.services.shopee_recommendations import config

    monkeypatch.setattr(config, "HISTORY_DAYS", 7)
    surfaces, waterfalls = await collect_shop(session, built.shop_id, CUR_END, days=7)
    for field in ("ctr", "ctor"):
        shown = agreed(surfaces, field, tol=1e-4)
        assert {"tong_quan", "phan_tich"} <= set(shown), field


async def test_the_headline_profit_is_the_shop_metrics_profit_with_the_waterfall_as_detail(
    session, built, monkeypatch
):
    from juli_backend.services.shopee_analytics import queries
    from juli_backend.services.shopee_recommendations import config

    monkeypatch.setattr(config, "HISTORY_DAYS", 7)
    surfaces, waterfalls = await collect_shop(session, built.shop_id, CUR_END, days=7)
    want = next(s for s in surfaces if s.name == "tong_quan").values["profit"]
    assert want is not None
    assert waterfalls["phan_tich_ranking"] == pytest.approx(want, rel=0.005)
    ov = await queries.overview(session, built.shop_id, period="7d", as_of=CUR_END)
    block = ov["profit"]
    assert block["profit_vnd"] == pytest.approx(want, abs=0.01)
    # P100 B.5: one shop profit with its coverage line; no "ước tính theo tỉ lệ" twin
    assert block["coverage_label"].startswith("trên ")
    assert "đơn có chi phí" in block["coverage_label"]
    assert block["known_cost_orders"] == ov["shop_profit"]["orders"]
    assert "profit_estimated" not in block and "profit_waterfall_vnd" not in block
