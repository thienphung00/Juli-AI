"""P99b (owner 2026-11-10): Kế hoạch = the accumulated numbers of its cards as the expected outcome
over the next 30 days from today, recomputed live; each card counts on its own days inside that
horizon (its Δ and its cost), a card wholly outside contributes 0 and says so, and the spend cap
reads the horizon's spend. Tự tạo's figures are for the set dates and the plan card repeats them
(``result.own``). Missing data is never a number. Synthetic reco shop only (SQLite, invented
figures)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import plans, store
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p99_one_base import ADS, ITEM, _save_and_plan
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


TODAY = NOW.date()


def _voucher(start, days):
    return sp.VoucherSpec(
        kind="voucher", scope="product", item_ids=[ITEM], discount_type="amount", value=20_000,
        min_spend=60_000, usage_limit=50, start=start, end=start + timedelta(days=days - 1),
    )  # fmt: skip


async def test_a_card_after_the_horizon_counts_zero_and_says_so(session, shop):
    seeded, _ = shop
    late = _voucher(TODAY + timedelta(days=40), 7)
    _, planned = await _save_and_plan(session, seeded, late)
    r, agg = planned["result"], planned["_aggregate"]
    assert r["outside_horizon"] is True and r["counted"] is False
    assert r["reason"] == "outside_horizon" and r["message"]
    assert r["counted_days"] == 0 and r["counted_dates"] is None
    assert r["cost_horizon"] == 0 and r["cost_total"] > 0  # its own cost stays shown
    assert r["delta"]["p50"]["dgmv"] == 0
    assert r["own"]["days"] == 7  # Tự tạo's figures for its own dates are still there
    assert agg["outside_horizon_cards"] == [planned["card_id"]]
    assert agg["dgmv_month"]["total"]["p50"] == 0
    assert agg["cost"]["horizon_spend_delta"] == 0


async def test_tu_tao_and_the_plan_card_show_the_same_set_dates_figures(session, shop):
    seeded, _ = shop
    spec = _voucher(TODAY + timedelta(days=2), 14)
    out = await builder.evaluate_versions(session, seeded.shop_id, [spec], as_of=AS_OF, now=NOW)
    tu_tao = out["versions"][0]["result"]
    assert tu_tao["days"] == 14  # the set dates, never 30
    _, planned = await _save_and_plan(session, seeded, spec)
    r = planned["result"]
    own = r["own"]["delta"]["p50"]
    assert own["dgmv"] == pytest.approx(tu_tao["delta"]["gmv"]["value"], abs=0.51)
    assert own["dorders"] == pytest.approx(tu_tao["delta"]["orders"]["value"], abs=0.051)
    assert r["cost_total"] == pytest.approx(tu_tao["cost"]["total"])
    # wholly inside the 30 days: the horizon counts the same figures, not ×30/14
    assert r["counted_days"] == 14 and r["delta"]["p50"]["dgmv"] == pytest.approx(own["dgmv"])
    assert r["cost_horizon"] == pytest.approx(r["cost_total"])


async def test_the_spend_cap_reads_the_horizons_spend(session, shop):
    seeded, _ = shop
    _, planned = await _save_and_plan(session, seeded, ADS)
    cost = planned["_aggregate"]["cost"]
    r = planned["result"]
    assert cost["horizon_spend_delta"] == pytest.approx(r["cost_horizon"])
    assert cost["horizon_spend_after"] == pytest.approx(
        cost["horizon_spend_before"] + cost["horizon_spend_delta"]
    )
    if cost["horizon_cap"] is not None:
        assert cost["over_cap"] is (cost["horizon_spend_after"] > cost["horizon_cap"])


async def test_an_empty_plan_states_the_horizon_and_no_figures(session, shop):
    seeded, _ = shop
    _, planned = await _save_and_plan(session, seeded, _voucher(TODAY, 3))
    await plans.remove_card(
        session, seeded.shop_id, uuid.UUID(planned["card_id"]), actor=_actor(seeded), now=NOW
    )
    agg = (await plans.get_plan(session, seeded.shop_id, now=NOW))["aggregate"]
    assert agg["n_cards"] == 0 and agg["empty"] is True and agg["empty_note"]
    assert agg["horizon"]["from"] == TODAY.isoformat()
    assert agg["after"] is None and agg["cost"] is None and agg["deltas_p50"] is None


async def test_an_ads_card_carries_its_read_back_or_not_read_yet(session, shop):
    seeded, _ = shop
    _, planned = await _save_and_plan(session, seeded, ADS)
    got = await plans.get_plan(session, seeded.shop_id, now=NOW)
    card = next(c for c in got["cards"] if c["card_id"] == planned["card_id"])
    rb = card["ads_readback"]
    assert rb["state"] == "not_found" and rb["reason"] == "not_read_yet"
    assert rb["actual"] is None  # never zeros
    stored = {
        "state": "matched", "label": "Đã khớp", "reason": None, "reason_text": None,
        "matched_by": "item_ids", "campaign": {"name": "x", "segment": "product",
        "first_day": AS_OF.isoformat(), "item_ids": [ITEM]}, "candidates": [],
        "started_before_card": False, "actual": None,
    }  # fmt: skip
    cid = uuid.UUID(planned["card_id"])
    await store.set_meta(session, seeded.shop_id, cid, {"ads_readback": stored})
    await session.commit()
    got = await plans.get_plan(session, seeded.shop_id, now=NOW)
    card = next(c for c in got["cards"] if c["card_id"] == planned["card_id"])
    assert card["ads_readback"] == stored
    others = [c for c in got["cards"] if c["change_kind"] != "ads_new_campaign"]
    assert all("ads_readback" not in c for c in others)
