"""F1 / F2 (owner 2026-11-25): one "hiện tại", one forecast.

F1: hiện tại (GMV, đơn, lượt xem, lượt nhấp) of a forecast = the real last 30 complete days of the
scope, the figure the picker shows; AOV = GMV ÷ đơn of those days; a longer window gives rates only;
a missing day is said (coverage), never scaled up.
F2: builder, stored card, plan product row, export
and Chat read one forecast; a loss is a loss. Synthetic shop only (invented figures)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine
from juli_backend.services.exports.collect import forecast_block
from juli_backend.services.shopee_analytics import channel_split, forecast_base, funnel, materialize
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder.engine.contract import Band, DriverEffect, OptionInput
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import integrate
from juli_backend.services.shopee_builder.specs import VoucherSpec
from juli_backend.services.shopee_recommendations import (
    forecast,
    manual,
    plan_aggregate,
    plans,
    result_store,
    store,
)
from juli_backend.services.shopee_recommendations import service as reco
from juli_backend.services.shopee_recommendations.evaluate import _scope_gmv_per_day
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_analytics import _line
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_funnel_engine import simple_base, voucher_option
from tests.unit.test_p99_one_base import ADS, AFFILIATE, COMBO, LISTING_COMBO, VOUCHER_NO_DATES
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor

ITEM = "1001"
#: one card of each kind the fixtures of the suite have
KINDS = {
    "voucher": VOUCHER_NO_DATES,
    "combo": COMBO,
    "listing_combo": LISTING_COMBO,
    "affiliate": AFFILIATE,
    "ads_new": ADS,
}

# ------------------------------------------------------------------------------- F1, pure

END = date(2026, 11, 20)


def _rows(*, sold: dict[int, int], days: int = 60, gap: tuple[int, ...] = ()) -> funnel.FunnelRows:
    """``sold``: days before END -> đơn of product A (100.000 đ each); 100 xem / 20 nhấp every day
    with data; ``gap``: days (before END) the shop's orders never arrived."""
    src, prod, shop = [], [], []
    for i in range(days):
        if i in gap:
            continue
        day, n = END - timedelta(days=i), sold.get(i, 0)
        gmv = D(100_000) * n
        src.append(funnel.SourceDay(day, "A", "the_san_pham_khac", 100, 20, n, gmv, None))
        src.append(funnel.SourceDay(day, None, "the_san_pham_khac", 100, 20, n + 1, gmv + 5, None))
        prod.append(funnel.ScopeDay(day, "A", n, gmv, None, 100, 20))
        shop.append(funnel.ScopeDay(day, None, n + 1, gmv + 5, None))
    return funnel.FunnelRows(
        Window(END - timedelta(days=days - 1), END), tuple(src), tuple(shop), tuple(prod)
    )


def test_volumes_are_the_real_last_30_days_whatever_window_the_rates_need():
    # 4 orders in the 30 days, 40 in the 30 days before: the rate window is 60 days
    rows = _rows(sold={3: 2, 10: 2, 40: 20, 50: 20})
    base = forecast_base.adaptive_base(rows, "s", item_ids=("A",))
    assert base.total("orders") == 4 and base.total("gmv") == 400_000
    assert base.total("views") == 3000 and base.total("clicks") == 600
    assert dict(base.windows)["aov"] == 60  # the longer window is still the rates' window
    cur = forecast_base.current_30d(rows, "s", item_ids=("A",))
    assert [(s.orders, s.gmv, s.views, s.clicks) for s in cur.sources] == [
        (s.orders, s.gmv, s.views, s.clicks) for s in base.sources
    ]
    assert (base.window_start, base.window_end) == (END - timedelta(days=29), END)


def test_a_dense_product_is_not_read_on_fourteen_days_scaled_up():
    rows = _rows(sold={i: 5 if i < 14 else 1 for i in range(60)})
    base = forecast_base.adaptive_base(rows, "s", item_ids=("A",))
    assert base.total("orders") == 14 * 5 + 16
    shop = forecast_base.adaptive_base(rows, "s")
    assert shop.total("orders") == 14 * 5 + 16 + 30


def test_missing_days_are_said_and_never_scaled_up():
    rows = _rows(sold=dict.fromkeys(range(60), 2), gap=(4, 5, 6))
    base = forecast_base.adaptive_base(rows, "s", item_ids=("A",))
    assert base.total("orders") == 27 * 2  # not 60
    assert (base.days, base.window_days) == (27, 30)
    r = run(base, voucher_option(), seed=1)
    f = forecast.forecast_of(r, reason=None, data_through=END)
    assert f["coverage"] == {
        "days_with_data": 27,
        "window_days": 30,
        "label": "27/30 ngày có dữ liệu",
    }


def test_the_longer_window_gives_the_ctor_the_cap_uses():
    """Product traffic on few days: đơn ÷ nhấp of the 30 days is over 100 %, the measured rate is
    not; a +20 % CTOR must add orders, never take them away."""
    rows = _rows(sold=dict.fromkeys(range(60), 8))
    keep = {END - timedelta(days=i) for i in range(6)}
    thin = replace(
        rows,
        sources=tuple(
            r if r.day in keep else replace(r, views=None, clicks=None) for r in rows.sources
        ),
        product_days=tuple(
            r if r.day in keep else replace(r, views=None, clicks=None) for r in rows.product_days
        ),
    )
    base = forecast_base.adaptive_base(thin, "s", item_ids=("A",))
    assert base.total("orders") == 240 and base.total("clicks") == 120
    up = Band(D("0.2"), D("0.2"), D("0.2"))
    option = OptionInput(
        "t", "t", (DriverEffect("ctor", ("the_san_pham_khac",), "measured", lift=up),), 30
    )
    r = run(base, option, seed=1)
    assert r.likely is not None and r.likely.orders == pytest.approx(D(288))


# -------------------------------------------------------------------- F1 + F2 on the shop


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session, materialized=False)
    for i, back in enumerate((9, 12, 35, 41, 52)):  # two inside the 30 days, three before them
        day = AS_OF - timedelta(days=back)
        session.add(_line(seeded.shop_id, 8001 + i, day, "G1", original=90_000, deal=80_000))
    await session.flush()
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


async def test_the_picker_has_one_source_and_the_base_is_it(session, shop):
    seeded, env = shop
    table = await builder.products(session, seeded.shop_id, as_of=AS_OF)
    cards = await channel_split.channel_split_products(session, seeded.shop_id, as_of=AS_OF)
    gmv_of = {p["product_id"]: p["gmv"] for p in cards["products"]}
    rows = {p["item_id"]: p for p in table["products"]}
    for item, row in rows.items():
        assert row["gmv_30d"] == pytest.approx(gmv_of.get(item, 0))
        today = integrate.scope_today(env, integrate.base_for(env, [item]))
        assert today["gmv_30d"] == pytest.approx(row["gmv_30d"])
        assert today["orders_30d"] == row["orders_30d"]
        if row["orders_30d"]:
            assert today["aov"] == pytest.approx(row["gmv_30d"] / row["orders_30d"])
        assert float(_scope_gmv_per_day(env, [item]) * 30) == pytest.approx(row["gmv_30d"])


async def test_shop_today_is_one_figure_everywhere(session, shop):
    seeded, env = shop
    base = integrate.scope_today(env, integrate.base_for(env, []))
    for other in (manual.today_of(env), plan_aggregate._today(env)):
        for k in ("gmv_30d", "orders_30d", "aov"):
            assert other[k] == pytest.approx(base[k]), k
    plan = plan_aggregate._today(env)
    assert plan["views_30d"] == pytest.approx(base["views_30d"])
    assert plan["clicks_30d"] == pytest.approx(base["clicks_30d"])
    frozen = {"as_of": "2026-10-01", "gmv_30d": 1.0, "orders_30d": 2, "aov": 0.5, "margin_pct": 3.0}
    assert plan_aggregate._today(env, frozen)["gmv_30d"] == 1.0  # a frozen base does not move


async def test_voucher_qualifying_orders_are_of_the_pickers_orders(session, shop):
    seeded, env = shop
    out = await builder.evaluate_versions(
        session, seeded.shop_id, [VOUCHER_NO_DATES], as_of=AS_OF, now=NOW
    )
    d = out["versions"][0]["details"]
    assert d["total_orders"] == env.metrics.split(ITEM).orders
    assert 0 <= d["qualifying_orders"] <= d["total_orders"]


async def test_the_voucher_aovs_are_the_shops_and_the_products_whatever_the_scope(session, shop):
    """Owner #87 (E132): shop voucher = shop AOV, product voucher = product AOV, F1's 30 days."""
    seeded, env = shop
    whole = VoucherSpec(kind="voucher", discount_type="amount", value=10_000, min_spend=100_000)
    item = env.metrics.split(ITEM)
    shop_aov = pytest.approx(float(env.shop_gmv_30d / env.shop_orders_30d))
    product_aov = pytest.approx(float(item.gmv / item.orders))
    for specs, want in (
        ([VOUCHER_NO_DATES], product_aov),
        ([whole], None),
        ([whole, VOUCHER_NO_DATES], product_aov),  # mixed scopes
    ):
        out = await builder.evaluate_versions(session, seeded.shop_id, specs, as_of=AS_OF, now=NOW)
        assert out["today"]["shop_aov"] == shop_aov
        assert out["today"]["product_aov"] == want


def _close(a, b, what):
    if a is None or b is None:
        assert a == b, what
    else:
        assert a == pytest.approx(b, abs=0.51), what


@pytest.mark.parametrize("kind", sorted(KINDS))
async def test_contract_every_surface_shows_one_forecast(session, shop, kind):
    seeded, env = shop
    sid, spec = seeded.shop_id, KINDS[kind]
    out = await builder.evaluate_versions(session, sid, [spec], as_of=AS_OF, now=NOW)
    version = out["versions"][0]
    assert version["ok"], version.get("refusal")
    want = version["result"]["forecast"]
    assert want["schema"] == "forecast/2"
    for key in ("cost", "evidence", "reason_code", "within_noise", "coverage", "data_through"):
        assert key in want
    wm = want["metrics"]
    today = version["today"]
    if want["days"] == 30:
        for m, k in (("gmv", "gmv_30d"), ("orders", "orders_30d"), ("aov", "aov")):
            _close(wm[m]["hien_tai"], today[k], f"builder today {m}")

    actor = manual.Actor("staff", seeded.user.id, seeded.user.id)
    saved = await builder.choose(
        session, sid, [spec], 0, primary=False, acknowledge_breaches=True, actor=actor,
        as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    card_id = uuid.UUID(saved["id"])
    prop = await session.get(ShopProposal, card_id)
    prop.status = "sent"
    await session.commit()
    detail = await reco.card_detail(session, sid, card_id, audience="seller")
    card = await store.card_payload(session, sid, card_id)
    surfaces = {"card": detail["forecast"], "excel": forecast_block(card, None)}

    @asynccontextmanager
    async def factory():
        yield session

    item = next(iter(integrate.scope_items(spec)), None) if kind != "ads_new" else ITEM
    chat = await ServiceCardEngine(factory, sid).engine_card(card["change_kind"], item, AS_OF)
    assert chat["ok"] and chat["source"] == "stored_card", chat
    surfaces["chat"] = chat["card"]["forecast"]
    for name, got in surfaces.items():
        for m in ("gmv", "orders", "aov", "profit"):
            for f in ("hien_tai", "du_kien", "delta"):
                _close(got["metrics"][m][f], wm[m][f], f"{name} {m} {f}")
        assert got["cost"] == pytest.approx(want["cost"]), name

    plan = await plans.add_card(
        session, sid, card_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    agg = plan["aggregate"]
    block = next((p for p in agg["products"] if p["product_id"] == ITEM), None)
    if block is None or not block.get("today") or len(today["items"]) != 1:
        return  # a card over several products has no product row of its own
    _close(block["today"]["gmv_30d"], today["gmv_30d"], "plan gmv")
    _close(block["today"]["orders_30d"], today["orders_30d"], "plan orders")
    if want["estimable"] and want["days"] == 30:
        _close(block["after"]["gmv_30d"], wm["gmv"]["du_kien"], "plan after gmv")
        _close(block["after"]["orders_30d"], wm["orders"]["du_kien"], "plan after orders")


# ----------------------------------------------------------------------------- F2


def test_a_negative_mid_profit_is_a_loss_not_noise():
    base = replace(
        simple_base(),
        daily=(
            ("gmv", tuple([1e9, 0.0] * 15)),
            ("orders", tuple([1e6, 0.0] * 15)),
            ("profit", tuple([1e9, 0.0] * 15)),
        ),
    )
    r = run(base, voucher_option(), seed=3)
    assert r.likely is not None and r.likely.profit is not None
    flagged = "profit" in r.within_noise
    assert flagged is (r.likely.profit >= r.before.profit and r.likely.profit >= 0)
    costly = replace(voucher_option(), fixed_cost=D(10_000_000))
    loss = run(base, costly, seed=3)
    assert "profit" not in loss.within_noise
    wire = loss.json()
    assert (
        wire["delta"]["profit"]["value"] < 0 and wire["forecast"]["metrics"]["profit"]["delta"] < 0
    )


async def test_an_old_stored_forecast_stays_readable_and_the_job_recomputes_it(session, shop):
    seeded, env = shop
    actor = manual.Actor("staff", seeded.user.id, seeded.user.id)
    saved = await builder.choose(
        session, seeded.shop_id, [VOUCHER_NO_DATES], 0, primary=False, acknowledge_breaches=True,
        actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    cid = uuid.UUID(saved["id"])
    card = await store.card_payload(session, seeded.shop_id, cid)
    old = dict(result_store.version_result(card, 1))
    prop = await session.get(ShopProposal, cid)
    prop.status = "sent"
    old["engine_version"] = "2026-11-24.2+card-result/1"
    old["forecast"] = {**old["forecast"], "schema": "forecast/1"}
    await result_store.save(session, seeded.shop_id, cid, card, {1: old}, status="sent")
    await session.commit()
    detail = await reco.card_detail(session, seeded.shop_id, cid, audience="seller")
    assert detail["forecast"]["schema"] == "forecast/1"  # readable until the job has run
    counts = await result_store.refresh_shop(session, seeded.shop_id, env, now=NOW)
    assert counts.updated == 1
    detail = await reco.card_detail(session, seeded.shop_id, cid, audience="seller")
    assert detail["forecast"]["schema"] == "forecast/2"


async def test_an_approved_card_keeps_the_forecast_it_was_approved_with(session, shop):
    seeded, env = shop
    actor = manual.Actor("staff", seeded.user.id, seeded.user.id)
    saved = await builder.choose(
        session, seeded.shop_id, [VOUCHER_NO_DATES], 0, primary=False, acknowledge_breaches=True,
        actor=actor, as_of=AS_OF, now=NOW,
    )  # fmt: skip
    await session.commit()
    cid = uuid.UUID(saved["id"])
    card = await store.card_payload(session, seeded.shop_id, cid)
    first = dict(card["forecast"])
    await result_store.freeze_at_approval(session, seeded.shop_id, cid, card, 1)
    moved = dict(result_store.version_result(card, 1))
    moved["forecast"] = {**first, "data_through": "2030-01-01"}
    prop = await session.get(ShopProposal, cid)
    prop.status = "approved"
    await result_store.save(session, seeded.shop_id, cid, card, {1: moved}, status="approved")
    await session.commit()
    detail = await reco.card_detail(session, seeded.shop_id, cid, audience="seller")
    assert detail["forecast"]["data_through"] == first["data_through"]
    again = await store.card_payload(session, seeded.shop_id, cid)
    assert forecast_block(again, None)["data_through"] == first["data_through"]
