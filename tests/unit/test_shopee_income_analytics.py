"""P91 D-12 end to end on the synthetic analytics shop (SQLite): stored income rows reach the
profit, the Income coverage figure sits beside the cost coverage, the VAT flags label the profit,
and the product page shows the pack.

The data is ``tests/support/shopee_analytics.py``; the income rows are invented here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from juli_backend.models.run_changes import ShopRule
from juli_backend.models.shopee_profit import ShopeeOrderIncome
from juli_backend.services.shopee_analytics import loaders, queries
from juli_backend.services.shopee_analytics.windows import Window
from tests.support.shopee_analytics import CUR_END, CUR_START, Seeded, seed_shopee_shop

CUR = Window(CUR_START, CUR_END)
D = Decimal


async def _overview(session, seeded: Seeded):
    return await queries.overview(session, seeded.shop_id, period="7d", as_of=CUR_END)


def _income(seeded: Seeded, ref: str, **over) -> ShopeeOrderIncome:
    values = dict(
        id=uuid.uuid4(),
        shop_id=seeded.shop_id,
        platform="shopee",
        order_ref=ref,
        fee_fixed=D(12_000),
        fee_service=D(4_000),
        fee_payment=D(5_000),
        affiliate_commission=D(0),
        net_shipping_cost=D(2_500),
        source="file",
        source_rank=3,
        source_version="seller-centre-xlsx-1",
    )
    values.update(over)
    return ShopeeOrderIncome(**values)


def _delivered_refs(seeded: Seeded, count: int) -> list[str]:
    refs: list[str] = []
    for ln in seeded.lines:
        if ln.status == "delivered" and ln.paid_at and ln.order_ref not in refs:
            refs.append(ln.order_ref)
    return refs[:count]


async def test_the_overview_without_income_says_no_order_has_it(session):
    seeded = await seed_shopee_shop(session)
    body = await _overview(session, seeded)
    cov = body["profit"]["income_coverage"]
    assert cov["with_income"] == 0 and cov["orders_pct"] == 0.0
    assert body["profit"]["fees"]["income"] == 0
    assert body["profit"]["vat"]["basis"] == "before_vat"


async def test_income_rows_win_over_the_order_exports_fees_and_show_in_the_coverage(session):
    seeded = await seed_shopee_shop(session)
    before = await _overview(session, seeded)
    refs = _delivered_refs(seeded, 3)
    session.add_all([_income(seeded, ref) for ref in refs])
    await session.flush()
    after = await _overview(session, seeded)
    cov = after["profit"]["income_coverage"]
    assert (
        cov["with_income"] == 3 and cov["orders"] == before["profit"]["income_coverage"]["orders"]
    )
    assert 0 < cov["orders_pct"] < 100 and 0 < cov["revenue_pct"] < 100
    assert after["profit"]["fees"]["income"] >= 3
    assert after["profit"]["fees"]["actual"] < before["profit"]["fees"]["actual"]
    # net shipping (2.500 per order) is a cost the formula and the export never saw
    assert after["profit"]["contribution_before_ads"] < before["profit"]["contribution_before_ads"]
    # the response never carries a ref
    assert not any(ref in str(after) for ref in refs)


async def test_the_coverage_figures_sit_side_by_side_in_the_profit_block(session):
    seeded = await seed_shopee_shop(session)
    block = (await _overview(session, seeded))["profit"]
    assert {"cost_coverage", "income_coverage", "vat"} <= set(block)
    assert set(block["income_coverage"]) >= {"orders", "with_income", "orders_pct", "revenue_pct"}
    assert "pack_from_name_pct" in block["cost_coverage"]


async def test_the_income_load_reads_only_the_orders_in_the_window(session):
    seeded = await seed_shopee_shop(session)
    refs = _delivered_refs(seeded, 2)
    session.add_all([_income(seeded, refs[0]), _income(seeded, "f" * 32)])
    await session.flush()
    load = await loaders.load_order_lines(session, seeded.shop_id, CUR)
    assert set(load.income) == {refs[0]}
    assert load.income[refs[0]].fee_fixed == D(12_000)


async def _flag(session, seeded: Seeded, key: str, value, scope: str = ""):
    session.add(
        ShopRule(
            shop_id=seeded.shop_id,
            rule_key=key,
            scope_ref=scope,
            value=value,
            set_by="seller",
            set_at=datetime(2026, 10, 8),
        )
    )
    await session.flush()


async def test_a_vat_inclusive_shop_with_a_rate_per_sku_reports_profit_after_vat(session):
    seeded = await seed_shopee_shop(session)
    plain = await _overview(session, seeded)
    await _flag(session, seeded, "prices_include_vat", True)
    for sku in ("G1", "N1", "T1"):
        await _flag(session, seeded, "vat_rate", 8, sku)
    body = await _overview(session, seeded)
    assert body["profit"]["vat"]["basis"] == "after_vat"
    assert body["profit"]["net_revenue"] < plain["profit"]["net_revenue"]
    assert body["profit"]["profit_vnd"] < plain["profit"]["profit_vnd"]


async def test_a_vat_flag_without_rates_leaves_the_profit_unknown_not_at_zero_percent(session):
    seeded = await seed_shopee_shop(session)
    await _flag(session, seeded, "prices_include_vat", True)
    body = await _overview(session, seeded)
    assert body["profit"]["cost_coverage"]["unknown_pct"] == 100.0
    assert body["profit"]["vat"]["prices_include_vat"] is True


async def test_the_product_page_shows_the_pack_of_each_sku(session):
    seeded = await seed_shopee_shop(session)
    page = await queries.product_page(session, seeded.shop_id, "1001", period="7d", as_of=CUR_END)
    costs = [row["cost"] for row in page["cost_and_floor"]["skus"]]
    assert costs and all(c["pack_count"] == 1 and c["bom"] is False for c in costs)
