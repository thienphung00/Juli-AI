"""P99c: Tự tạo's money layer (``cost`` / ``break_even``) covers the version's own days -- never a
30-day figure beside the set dates -- and So sánh ranks by Δ lợi nhuận per day of each version's own
dates (``sort_basis``), nulls last. Synthetic reco shop only (SQLite, invented figures)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import outcome
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p99_one_base import ADS, ITEM
from tests.unit.test_shopee_reco_plan import NOW

# ------------------------------------------------------------------------------------ pure

_MONTH = {
    "amount": 300_000,
    "period_days": 30,
    "label": "Mức giảm cho khách × số combo dự kiến trong tháng",
    "per_unit": 10_000,
    "expected_units": 30,
}


def test_a_month_cost_beside_set_dates_takes_the_results_cost_over_those_days():
    result = {"days": 14, "cost": {"total": 140_000.0, "break_even_orders": 3.0}}
    out = outcome.cost_on_days(_MONTH, result, 14)
    assert out["amount"] == 140_000 and out["period_days"] == 14
    assert out["source"] == "result" and "expected_units" not in out
    assert "trong 14 ngày" in out["label"] and out["per_unit"] == 10_000


def test_a_month_cost_without_a_result_is_null_with_a_reason():
    out = outcome.cost_on_days(_MONTH, None, 14)
    assert out["amount"] is None and out["period_days"] == 14
    assert out["reason"] == "no_result_for_days" and out["reason_text"]


def test_a_cost_already_on_the_versions_days_stays():
    out = outcome.cost_on_days(_MONTH, None, 30)
    assert out["amount"] == 300_000 and out["source"] == "money_layer"


def _v(index, *, days, value, ok=True, cost_known=True):
    result = None if days is None else {"days": days, "delta": {"profit": {"value": value}}}
    return {"index": index, "ok": ok, "cost_known": cost_known, "result": result}


def test_so_sanh_ranks_by_profit_per_own_day_nulls_last():
    versions = [
        _v(0, days=30, value=300_000),  # 10k / day, the best per 30 days in total
        _v(1, days=7, value=140_000),  # 20k / day
        _v(2, days=None, value=None),  # no result
        _v(3, days=14, value=None),  # profit unknown
        _v(4, days=14, value=-14_000),  # -1k / day
        _v(5, days=14, value=500_000, cost_known=False),  # no giá vốn: unknown
    ]
    assert builder.compare_order(versions) == [1, 0, 4, 2, 3, 5]
    assert builder.SORT_BASIS["key"] == "delta_profit_per_day"


# ------------------------------------------------------------------------------------ wired


@pytest.fixture
async def seeded(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    return seeded


COMBO_14 = sp.ComboSpec(
    kind="combo", item_ids=[ITEM], discount_type="pct",
    tiers=[sp.ComboTier(qty=2, value=5), sp.ComboTier(qty=3, value=8)],
    start=AS_OF, end=AS_OF + timedelta(days=13),
)  # fmt: skip


async def test_set_dates_cost_and_break_even_are_for_those_days_and_so_sanh_says_its_basis(
    session, seeded
):
    out = await builder.evaluate_versions(
        session, seeded.shop_id, [COMBO_14, ADS], as_of=AS_OF, now=NOW
    )
    assert out["sort_basis"]["key"] == "delta_profit_per_day" and out["sort_basis"]["label"]
    for v in out["versions"]:
        if not v["ok"]:
            continue
        days = v["dates"]["days"]
        assert days == 14
        if v["result"] is not None:
            assert v["result"]["days"] == days
        assert v["cost"]["period_days"] == days  # never a 30-day figure beside the set dates
        assert v["cost"]["amount"] is not None or v["cost"]["reason"]
        be = v["break_even"]
        if be.get("applies"):
            assert be["period_days"] == days
    ads = next(v for v in out["versions"] if v["ok"] and v["kind"] == "ads_new")
    assert ads["cost"]["amount"] == pytest.approx(ads["result"]["cost"]["total"])
    assert sorted(out["compare"]) == [0, 1]
