"""One card, one number (owner, 2026-11-14): a card saved from Tự tạo shows the SAME Δ lợi nhuận,
Δ GMV and Chi phí in the builder's evaluate, the card list, the card page, Kế hoạch and the Kế hoạch
Excel rows -- every screen reads the engine result stored on the card, never the money layer.
Synthetic reco shop (SQLite, invented figures)."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from juli_backend.models.models import ActionCard
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.exports.collect import collect_ke_hoach
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import plans, result_store, store
from juli_backend.services.shopee_recommendations import service as reco
from juli_backend.services.shopee_recommendations.loader import load_env
from scripts import recompute_card_results as script
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p99_one_base import ITEM, _staff
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor

#: a voucher on the plan's own days (from today, 14 days), so its own Δ is its Δ in Kế hoạch
VOUCHER = sp.VoucherSpec(
    kind="voucher", scope="product", item_ids=[ITEM], discount_type="amount", value=20_000,
    min_spend=60_000, usage_limit=50, start=NOW.date(), end=NOW.date() + timedelta(days=13),
)  # fmt: skip


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


async def _choose(session, seeded, spec) -> uuid.UUID:
    saved = await builder.choose(
        session, seeded.shop_id, [spec], 0, primary=False, acknowledge_breaches=True,
        actor=_staff(seeded), as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    card_id = uuid.UUID(saved["id"])
    prop = await session.get(ShopProposal, card_id)
    prop.status = "sent"
    await session.commit()
    return card_id


async def test_a_builder_card_shows_one_number_on_every_screen(session, shop):
    seeded, _ = shop
    sid = seeded.shop_id
    built = await builder.evaluate_versions(session, sid, [VOUCHER], as_of=AS_OF, now=NOW)
    res = built["versions"][0]["result"]
    want = {
        "profit": res["delta"]["profit"]["value"],
        "gmv": res["delta"]["gmv"]["value"],
        "cost": res["cost"]["total"],
    }
    assert want["cost"] > 0 and want["gmv"] is not None and want["profit"] is not None
    card_id = await _choose(session, seeded, VOUCHER)

    def same(profit, gmv, cost, where):
        assert profit == pytest.approx(want["profit"], abs=1), where
        assert gmv == pytest.approx(want["gmv"], abs=1), where
        assert cost == pytest.approx(want["cost"], abs=1), where

    # the card list
    listed = await reco.list_cards(session, sid, audience="seller", queue="all", now=NOW)
    row = next(c for c in listed["cards"] if c["id"] == str(card_id))
    ps = row["predicted_summary"]
    same(ps["dprofit"]["p50"], ps["dgmv"]["p50"], row["cost"], "list")
    assert ps["not_estimable"] is False and ps["effect_days"] == 14
    assert "certain_summary" not in row
    # the card page
    detail = await reco.card_detail(session, sid, card_id, audience="seller")
    ps = detail["predicted_summary"]
    same(ps["dprofit"]["p50"], ps["dgmv"]["p50"], detail["cost"], "detail")
    option = detail["result"]["option"]
    same(option["delta"]["profit"]["value"], option["delta"]["gmv"]["value"],
         option["cost"]["total"], "detail option")  # fmt: skip
    # Kế hoạch
    out = await plans.add_card(
        session, sid, card_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    await session.commit()
    pc = next(c for c in out["aggregate"]["cards"] if c["card_id"] == str(card_id))
    own = pc["result"]["own"]
    same(own["delta"]["p50"]["dprofit"], own["delta"]["p50"]["dgmv"], own["cost_total"], "plan")
    # the Kế hoạch Excel rows
    data = await collect_ke_hoach(session, sid, shop_name="Mẫu", now=NOW, month="2026-10")
    xr = next(r for r in data.cards if r.code == row["code"])
    same(xr.profit_mid, xr.gmv_mid, xr.cost, "excel")


async def test_the_plan_reads_the_stored_result_while_it_is_fresh(session, shop, monkeypatch):
    """A fresh stored result is what Kế hoạch counts: the plan never recomputes it."""
    from juli_backend.services.shopee_recommendations import plan_aggregate as pa

    seeded, _ = shop
    card_id = await _choose(session, seeded, VOUCHER)
    called: list[str] = []
    real = pa.card_result

    def spy(*a, **k):
        called.append("x")
        return real(*a, **k)

    monkeypatch.setattr(pa, "card_result", spy)
    await plans.add_card(
        session, seeded.shop_id, card_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    assert called == []


async def test_a_not_estimable_card_says_so_with_nulls(session, shop, monkeypatch):
    seeded, _ = shop
    monkeypatch.setattr(result_store, "spec_of_version", lambda *a, **k: None)
    card_id = await _choose(session, seeded, VOUCHER)
    detail = await reco.card_detail(session, seeded.shop_id, card_id, audience="seller")
    ps = detail["predicted_summary"]
    assert ps["not_estimable"] is True and ps["reason"] == "no_spec"
    assert ps["message"] == "Chưa ước tính được"
    assert ps["dprofit"] == {"p10": None, "p50": None, "p90": None}


async def test_the_recompute_command_is_idempotent_and_keeps_the_approval_result(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    card_id = await _choose(session, seeded, VOUCHER)
    # a card made before results were stored: drop its frozen result
    from juli_backend.models.card_events import EVENT_PROPOSED, CardEvent

    ev = await session.scalar(
        select(CardEvent).where(
            CardEvent.card_id == card_id, CardEvent.event_type == EVENT_PROPOSED
        )
    )
    payload = dict(ev.payload)
    payload.pop("result", None)
    payload["versions"] = [
        {k: v for k, v in r.items() if k != "result"} for r in payload["versions"]
    ]
    ev.payload = payload
    prop = await session.get(ShopProposal, card_id)
    prop.status = "approved"
    await session.commit()
    before = await store.card_payload(session, sid, card_id)
    assert result_store.version_result(before, 1) is None

    dry = await script.recompute_shop(session, sid, now=NOW, dry_run=True)
    assert dry is not None and dry["updated"] == 1
    assert result_store.version_result(await store.card_payload(session, sid, card_id), 1) is None

    first = await script.recompute_shop(session, sid, now=NOW)
    await session.commit()
    assert first == {"cards": 1, "updated": 1, "fresh": 0, "not_estimable": 0, "failed": 0}
    after = await store.card_payload(session, sid, card_id)
    block = result_store.version_result(after, 1)
    assert block is not None and block["estimable"] is True
    meta = json.loads((await session.get(ActionCard, card_id)).metadata_json)
    assert meta[result_store.AT_APPROVAL]["inputs_hash"] == block["inputs_hash"]
    again = await script.recompute_shop(session, sid, now=NOW)
    assert again is not None and again["updated"] == 0 and again["fresh"] == 1
    print(script.line(sid, first, dry_run=False))


async def test_an_input_change_makes_the_stored_result_stale(session, shop):
    seeded, env = shop
    card_id = await _choose(session, seeded, VOUCHER)
    card = await store.card_payload(session, seeded.shop_id, card_id)
    block = result_store.version_result(card, 1)
    assert result_store.is_fresh(block, env, card)
    stale = {**block, "engine_version": "old"}
    assert not result_store.is_fresh(stale, env, card)
    moved = {**block, "inputs_hash": "x"}
    assert not result_store.is_fresh(moved, env, card)


def test_the_result_core_rebuilds_the_option_result_exactly():
    from tests.unit.test_p98_plan_results import result

    r = result(300_000, 6, 90_000, lo=40_000, hi=150_000, days=14, cost=12_345)
    back = result_store.option_of(result_store.core_of(r))
    assert back.likely == r.likely and back.low == r.low and back.before == r.before
    assert back.cost_total == r.cost_total and back.days == 14
    block = result_store.block_of(
        r, reason=None, start=date(2026, 10, 8), targets=None, as_of=date(2026, 10, 7),
        now=NOW, hash_="h",
    )  # fmt: skip
    assert block["own"]["delta"]["profit"] == {"p10": 40_000, "p50": 90_000, "p90": 150_000}
    assert block["own"]["dates"] == {"from": "2026-10-08", "to": "2026-10-21", "days": 14}
    band = result_store.metric_band(block, "gmv")
    assert band is not None and band["p50"] == pytest.approx(0.03)
    assert result_store.profit_band(block, 7)["p50"] == pytest.approx(45_000)
