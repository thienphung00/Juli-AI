"""P96b: Phân tích replaces Xếp hạng (owner, 2026-11-06).

- The product table ranks every KPI by its own number: Lượt xem / CTR / CTOR come from the
  traffic sources (L1: a "Lượt xem" click used to show ₫ GMV / ngày).
- A product whose GMV per day fell materially against the previous window is "cần chú ý" (M1:
  ORY showed "0 chỉ số cần chú ý" with GMV −10,5 % and one product at −132.192đ / ngày).
- A product a hair under the shop median is not flagged (M2: "▼ 0,0 %").
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from juli_backend.services.shopee_analytics import critical, queries
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop


@pytest.fixture
async def seeded(session):
    return await seed_shopee_shop(session)


# =========================================================================== L1: funnel measures


async def test_views_rank_per_day_and_add_up_to_the_shops_views(session, seeded):
    body = await queries.ranking(
        session, seeded.shop_id, xep_theo="views", period="7d", as_of=CUR_END
    )
    assert body["supported"] is True and body["xep_theo"]["additive"] is True
    assert body["adds_up"] is True
    assert body["xep_theo"]["label"] == "Lượt xem / ngày"
    assert body["cell"]["now"] is not None and body["cell"]["now"] > 0
    # not the đồng figure the GMV ranking shows
    gmv = await queries.ranking(session, seeded.shop_id, period="7d", as_of=CUR_END)
    assert body["cell"]["now"] != gmv["cell"]["now"]


@pytest.mark.parametrize("xep", ["ctr", "ctor"])
async def test_ctr_and_ctor_rank_as_ratios_of_the_traffic_sources(session, seeded, xep):
    body = await queries.ranking(session, seeded.shop_id, xep_theo=xep, period="7d", as_of=CUR_END)
    assert body["supported"] is True and body["adds_up"] is None
    now = body["cell"]["now"]
    assert now is not None and 0 < now < 1


async def test_funnel_measures_are_refused_for_a_price_lever_with_the_reason(session, seeded):
    body = await queries.ranking(
        session, seeded.shop_id, source="voucher", xep_theo="ctr", period="7d", as_of=CUR_END
    )
    assert body["supported"] is False and body["reason"] == "not_split_by_lever"
    assert "không tách được theo mức ưu đãi" in body["message"]


# =========================================================================== M1: previous window


def _ory_like_ranking(**over):
    rows = [
        {
            "id": "26107129526",
            "product_id": "26107129526",
            "label": "Combo 3, 5,10 Hộp 100 Găng Tay",
            "now": 257_958.0,
            "before": 390_150.0,
            "delta": -132_192.0,
            "confidence": "Rõ",
        },
        {  # a 4 % dip is noise, not "cần chú ý"
            "id": "2",
            "product_id": "2",
            "label": "Túi",
            "now": 96_000.0,
            "before": 100_000.0,
            "delta": -4_000.0,
            "confidence": "Rõ",
        },
    ]
    return {"supported": True, "down": rows, "up": [], **over}


def test_a_material_fall_against_the_previous_window_is_an_item_with_that_fall_at_stake():
    items = critical.previous_items(_ory_like_ranking(), {"26107129526": "ctor"})
    assert [it["product_id"] for it in items] == ["26107129526"]
    it = items[0]
    assert it["kind"] == "below_previous" and it["kpi"] == "gmv"
    assert it["reference"]["type"] == "previous" and it["reference"]["value"] == 390_150.0
    assert it["at_stake_per_day"] == 132_192
    assert it["deviation_pct"] == pytest.approx(-33.9, abs=0.1)
    assert it["cause"]["stage"] == "ctor" and "CTOR giảm" in it["cause"]["text"]
    assert it["ranking_link"] == {"kpi": "gmv", "src": "all", "focus": "26107129526"}


def test_no_previous_items_when_the_table_is_refused():
    assert critical.previous_items({"supported": False, "reason": "previous_period_thin"}) == []


def test_the_stage_that_fell_most_is_named():
    now = {"views": Decimal(900), "ctr": Decimal("0.03"), "ctor": Decimal("0.05"), "aov": None}
    before = {"views": Decimal(1000), "ctr": Decimal("0.03"), "ctor": Decimal("0.08"), "aov": None}
    assert critical.drop_stage(now, before) == "ctor"
    assert critical.drop_stage({}, {}) == "gmv_drop"


async def test_the_critical_list_carries_the_previous_window_items(session, seeded, monkeypatch):
    def fake_ranking(now, before, **kw):
        return {
            "supported": True,
            "up": [],
            "down": [
                {
                    "id": "1001",
                    "product_id": "1001",
                    "label": "Găng tay",
                    "now": 50_000.0,
                    "before": 120_000.0,
                    "delta": -70_000.0,
                    "confidence": "Rõ",
                }
            ],
        }

    monkeypatch.setattr(critical, "build_ranking", fake_ranking)
    body = await queries.critical(session, seeded.shop_id, period="7d", as_of=CUR_END)
    drops = [it for it in body["items"] if it["kind"] == "below_previous"]
    assert len(drops) == 1 and drops[0]["product_id"] == "1001"
    assert drops[0]["rank"] == 1 and drops[0]["at_stake_per_day"] == 70_000
    assert (
        "price_min" in drops[0] and "margin_basis" in drops[0]
    )  # B-9 block like every product item


# =========================================================================== M2: median gap


def test_a_hair_under_the_median_is_not_material():
    assert critical.material_gap(Decimal("0.0328"), Decimal("0.03281")) is False
    assert critical.material_gap(Decimal("0.0300"), Decimal("0.0328")) is True
    assert critical.material_gap(Decimal(1), Decimal(0)) is False
