"""Stored opportunities (batch-1124-c-data, OPP): every candidate of a run is a row with its
outcome, a rerun adds nothing, an on-demand run never replaces a daily row, and ``compare`` gives
exactly four versions. SQLite; synthetic."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_opportunities import OUTCOMES, ShopeeOpportunity
from juli_backend.services.shopee_recommendations import daily_generation as daily
from juli_backend.services.shopee_recommendations import opportunities as opp
from juli_backend.services.shopee_recommendations import service, versions
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(AS_OF.year, AS_OF.month, AS_OF.day, 3, 0) + timedelta(days=1)


@pytest.fixture(autouse=True)
def band_off(monkeypatch):
    monkeypatch.setattr("juli_backend.services.forecast.triggers.clears_band", lambda *a: True)


async def _rows(session, shop_id):
    return list(
        (
            await session.execute(
                select(ShopeeOpportunity).where(ShopeeOpportunity.shop_id == shop_id)
            )
        ).scalars()
    )


def _draft(kind, outcome, item="1001", **kw):
    return opp.Draft(
        kind=kind,
        scope="product" if item else "shop",
        item_key=item,
        variant_key="",
        item_ids=[item] if item else [],
        inputs={"x": 1},
        outcome=outcome,
        **kw,
    )


def test_keys_are_sorted_and_empty_means_shop():
    assert opp.item_key_of(["b", "a"]) == "a,b"
    assert opp.item_key_of([]) == ""
    assert opp.variant_key_of(None) == ""
    assert opp.variant_key_of("c1", {"daily_budget": 30000}) == "c1|daily_budget=30000"
    assert opp.variant_key_of(None, {"discount_pct": 8}) == "|discount_pct=8"


@pytest.mark.timeout(180)
async def test_one_row_per_outcome_and_a_rerun_adds_nothing(session):
    seeded = await seed_reco_shop(session)
    day = date(2026, 11, 25)
    drafts = [
        _draft(kind, outcome, item=str(n), delta_profit=Decimal("10.00"))
        for n, (kind, outcome) in enumerate(zip(("a", "b", "c", "d", "e"), OUTCOMES), start=1)
    ]
    for _ in range(2):
        await opp.save_drafts(session, seeded.shop_id, day, drafts, opp.DAILY, now=NOW)
    await session.commit()
    rows = await _rows(session, seeded.shop_id)
    assert sorted(r.outcome for r in rows) == sorted(OUTCOMES)
    assert all(r.derivation_version for r in rows)
    # a second identical write is a no-op (nothing counted as touched)
    again = await opp.save_drafts(session, seeded.shop_id, day, drafts, opp.DAILY, now=NOW)
    assert again == 0


@pytest.mark.timeout(180)
async def test_an_on_demand_write_never_replaces_a_daily_row(session):
    seeded = await seed_reco_shop(session)
    day = date(2026, 11, 25)
    await opp.save_drafts(
        session, seeded.shop_id, day, [_draft("k", "published")], opp.DAILY, now=NOW
    )
    await opp.save_drafts(
        session, seeded.shop_id, day, [_draft("k", "refused", reason="x")], opp.ON_DEMAND, now=NOW
    )
    (row,) = await _rows(session, seeded.shop_id)
    assert (row.outcome, row.source) == ("published", "daily")


@pytest.mark.timeout(180)
async def test_the_daily_run_stores_every_candidate_and_unknown_is_null(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    run = await daily.run_shop(session, seeded.shop_id, now=NOW)
    await session.commit()
    assert run.status == "done" and run.generated >= 1
    rows = await _rows(session, seeded.shop_id)
    published = [r for r in rows if r.outcome == "published"]
    assert len(published) == run.generated
    assert all(r.card_code for r in published)
    assert all(r.source == "daily" and r.run_date == opp.run_day(NOW) for r in rows)
    refused = [r for r in rows if r.outcome == "refused"]
    assert all(r.reason and r.delta_profit is None for r in refused)
    # the same-day rerun (generate_cards again) changes no row
    before = {(r.kind, r.item_key, r.variant_key): (r.outcome, r.card_code) for r in rows}
    await service.generate_cards(
        session, seeded.shop_id, now=NOW, cycle=daily.cycle_key(opp.run_day(NOW)), persist=True
    )
    await session.commit()
    after = {
        (r.kind, r.item_key, r.variant_key): (r.outcome, r.card_code)
        for r in await _rows(session, seeded.shop_id)
    }
    assert before.items() <= after.items()


@pytest.mark.timeout(180)
async def test_on_demand_for_a_product_equals_the_daily_row_on_identical_candidates(session):
    """Outcome and numbers match the daily run's row on the same data (rank position may not)."""
    seeded = await seed_reco_shop(session)
    await session.commit()
    await daily.run_shop(session, seeded.shop_id, now=NOW)
    await session.commit()
    daily_rows = {
        (r.kind, r.item_key, r.variant_key): r
        for r in await _rows(session, seeded.shop_id)
        if r.outcome == "published" and r.scope == "product"
    }
    assert daily_rows
    item = next(iter(daily_rows.values())).item_ids[0]
    before = len(await _rows(session, seeded.shop_id))
    got = await opp.generate_for(session, seeded.shop_id, [item], now=NOW)
    await session.commit()
    assert len(await _rows(session, seeded.shop_id)) == before  # daily rows are not replaced
    assert got
    for o in got:
        d = daily_rows.get((o.kind, ",".join(o.item_ids), o.variant_key))
        if d is not None:
            assert o.delta_profit == d.delta_profit and o.delta_gmv == d.delta_gmv
            assert (o.inputs, o.extra) == opp.split_inputs(d.inputs)


@pytest.mark.parametrize(
    "kind",
    ["product_discount", "min_spend_voucher", "voucher_cap", "ads_budget", "ads_roas_target"],
)
def test_every_slider_kind_has_four_points(kind):
    base = {
        "product_discount": {"discount_pct": 10},
        "min_spend_voucher": {"value": 10_000, "min_spend": 200_000, "quantity": 50, "days": 7},
        "voucher_cap": {"value": 20_000, "min_spend": 100_000},
        "ads_budget": {"daily_budget": 100_000},
        "ads_roas_target": {"roas_target": 5.0},
    }[kind]
    alts = versions.alternative_inputs(kind, base, {"daily_budget": 100_000})
    assert len(alts) == 3
    assert len({tuple(sorted(a.items())) for a in [base, *alts]}) == 4


@pytest.mark.parametrize(
    ("kind", "base"),
    [
        ("product_discount", {"discount_pct": 2}),
        ("product_discount", {"discount_pct": 58}),
        ("ads_roas_target", {"roas_target": 1.0}),
        ("voucher_cap", {"value": 2000, "min_spend": 0}),
        ("ads_budget", {"daily_budget": 20_000}),
    ],
)
def test_a_point_at_a_slider_limit_is_replaced_by_a_spare_point(kind, base):
    alts = versions.alternative_inputs(kind, base, {})
    assert len(alts) == 3


async def _seed_and_run(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    await daily.run_shop(session, seeded.shop_id, now=NOW)
    await session.commit()
    return seeded


@pytest.mark.timeout(180)
async def test_shop_wide_kinds_are_shop_scope_rows_never_needs_a_product(session):
    seeded = await _seed_and_run(session)
    rows = [r for r in await _rows(session, seeded.shop_id) if r.scope == "shop"]
    by_kind = {r.kind: r for r in rows}
    assert set(opp.SHOP_KIND_REFUSALS) <= set(by_kind) | {"min_spend_voucher"}
    for kind in ("flash_sale", "program_registration"):
        assert by_kind[kind].outcome == "refused"
        assert by_kind[kind].reason == opp.REASON_NEEDS_PRODUCT
        assert by_kind[kind].delta_profit is None  # no invented estimate
    assert all(r.item_key == "" and r.item_ids == [] for r in rows)
    assert "needs_a_product" not in {r.reason for r in rows}


@pytest.mark.timeout(180)
async def test_compare_gives_exactly_four_options_each_with_figures_or_a_reason(session):
    seeded = await _seed_and_run(session)
    from juli_backend.services.shopee_recommendations.loader import load_env

    env = await load_env(session, seeded.shop_id, now=NOW)
    seen = 0
    for kind in ("min_spend_voucher", "product_discount"):
        res = await opp.compare(session, seeded.shop_id, kind, now=NOW, env=env)
        if res.reason is not None:  # the kind has no candidate on the fixture: it says why
            assert res.options == [] and res.reason
            continue
        seen += 1
        assert len(res.options) == 4 and res["options"] == res.options
        assert [o.option for o in res.options] == [1, 2, 3, 4]
        assert {o.lever for o in res.options} == {kind}
        for o in res.options:
            assert (o.delta_profit is not None) or o.reason
            assert o.status in {"ok", "floor_breach", "spend_breach", "refused"}
            if o.status == "floor_breach":
                assert o.reason == "floor_breach" and o.breaches
    assert seen >= 1


@pytest.mark.timeout(180)
async def test_compare_with_the_sellers_own_points(session):
    seeded = await _seed_and_run(session)
    rows = [r for r in await _rows(session, seeded.shop_id) if r.kind == "product_discount"]
    if not rows:
        pytest.skip("no product_discount candidate on the fixture")
    item = rows[0].item_ids[0]
    res = await opp.compare(
        session,
        seeded.shop_id,
        "product_discount",
        item_id=item,
        points=[{"discount_pct": 5}, {"discount_pct": 10}, {"discount_pct": 15}],
        now=NOW,
    )
    assert len(res.options) == 4
    assert [o.inputs.get("discount_pct") for o in res.options[1:]] == [5, 10, 15]


@pytest.mark.timeout(180)
async def test_engine_card_reads_the_stored_opportunity_and_has_no_generator_shortcut(session):
    from contextlib import asynccontextmanager

    from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine

    seeded = await _seed_and_run(session)
    rows = [
        r
        for r in await _rows(session, seeded.shop_id)
        if r.outcome == "published" and r.item_ids and not r.kind.startswith("affiliate_")
    ]
    assert rows
    r = rows[0]

    @asynccontextmanager
    async def factory():
        yield session

    eng = ServiceCardEngine(factory, seeded.shop_id)
    as_of = opp.run_day(NOW)
    out = await eng.engine_card(r.kind, r.item_ids[0], as_of)
    assert out["ok"], out
    assert out["source"] == "opportunity"
    gone = await eng.engine_card("title", "no-such-item", as_of)
    assert gone == {"ok": False, "reason": opp.REASON_NO_OPPORTUNITY}
    import inspect

    assert "GENERATORS[" not in inspect.getsource(ServiceCardEngine.engine_card)


def test_card_margin_scope_is_contribution_before_ads_and_aff():
    """L1: Σ organic contribution ÷ Σ covered doanh thu thực, never the ads-deducted margin."""
    from types import SimpleNamespace as NS

    from juli_backend.services.shopee_builder.outcome import scope_contribution_margin_pct

    def row(paid, contribution, aff, margin_pct):
        return NS(
            buyer_paid_covered=Decimal(paid),
            organic_contribution=Decimal(contribution) + Decimal(aff),
            margin_pct=margin_pct,
        )

    profit = NS(
        products={"a": row(1000, 200, 20, Decimal("1.0")), "b": row(500, 50, 0, Decimal("2.0"))},
        buyer_paid_covered=Decimal(1500),
        organic_contribution=Decimal(270),
    )
    assert scope_contribution_margin_pct(profit, ["a"]) == Decimal("22.0")
    assert scope_contribution_margin_pct(profit, ["a", "b"]) == Decimal("18.0")
    assert scope_contribution_margin_pct(profit, []) == Decimal("18.0")
    assert scope_contribution_margin_pct(profit, ["zzz"]) is None


def test_stored_inputs_keep_the_candidate_extra():
    inputs, extra = opp.split_inputs({"inputs": {"a": 1}, "extra": {"kol": {"key": "k"}}})
    assert (inputs, extra) == ({"a": 1}, {"kol": {"key": "k"}})
    assert opp.split_inputs({"a": 1}) == ({"a": 1}, {})  # a row from before the wrapper


@pytest.mark.timeout(180)
async def test_kol_and_title_cards_draft_from_a_stored_row_after_the_daily_run(session):
    """The run's own cards lock their products, so the engine no longer yields the candidate:
    the stored row (inputs + extra) is what drafts it."""
    seeded = await _seed_and_run(session)
    rows = [
        r
        for r in await _rows(session, seeded.shop_id)
        if r.outcome == "published" and split(r)[1] and r.kind.startswith(("affiliate_", "title"))
    ]
    assert rows, "the fixture publishes a kol card with extra"
    for r in rows[:2]:
        out = await opp.draft_card(session, seeded.shop_id, r.id, now=NOW)
        assert out["ok"], out
        assert out["card"]["change_kind"] == r.kind
        assert "margin_split" not in out["card"]  # #75: one combined Biên đóng góp, no split


def split(row):
    return opp.split_inputs(row.inputs)


@pytest.mark.timeout(180)
async def test_on_demand_rows_persist_through_the_write_factory(session):
    from contextlib import asynccontextmanager

    from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine

    seeded = await seed_reco_shop(session)
    await session.commit()

    @asynccontextmanager
    async def factory():
        yield session

    eng = ServiceCardEngine(factory, seeded.shop_id, write_factory=factory)
    await eng.engine_card("min_spend_voucher", None, opp.run_day(NOW))
    rows = await _rows(session, seeded.shop_id)
    assert rows and all(r.source == "on_demand" for r in rows)
    session.expire_all()  # a rollback after the answer must not lose them
    assert await _rows(session, seeded.shop_id)


def test_ke_hoach_goal_minus_baseline_is_the_sum_of_net_deltas(monkeypatch):
    """L2: baseline = the known-cost profit (Ròng: after ads and AFF); every card's Δ is Δ đóng góp
    minus its OWN cost (an ads card's spend, an affiliate card's commission + samples, a price
    card's offer), so goal - baseline = Σ net Δ for an ads + a price + an AFF card."""
    from datetime import date as d_
    from types import SimpleNamespace as NS

    from juli_backend.services.shopee_builder.engine.contract import (
        AddedTraffic,
        DriverEffect,
        OptionInput,
    )
    from juli_backend.services.shopee_recommendations import month_plan, plan_aggregate
    from tests.unit.test_p_card_basis import AOV, RATE, D, _run, point

    ppo = RATE * AOV
    added = AddedTraffic(point(1000), D("0.1"), D("0.05"), AOV, point(1), ppo)  # 5 orders
    ads = OptionInput(
        "ads_new_campaign",
        "ads",
        (DriverEffect("views", ("the_san_pham_khac",), "measured", added=added),),
        30,
        fixed_cost=D(100000),
    )
    aff = OptionInput(
        "affiliate_sample",
        "aff",
        (DriverEffect("views", ("the_san_pham_khac",), "measured", added=added),),
        30,
        fixed_cost=D(40000),  # commission x GMV + samples
    )
    price = OptionInput(
        "bundle_deal",
        "price",
        (DriverEffect("aov", ("the_san_pham_khac",), "measured", lift=point("0.10")),),
        30,
    )
    nets = []
    for opt in (ads, aff, price):
        r = _run(opt)
        nets.append(float(r.likely.profit - r.before.profit))
    assert nets[0] == pytest.approx(5 * float(ppo) - 100000, abs=1.0)
    assert nets[1] == pytest.approx(5 * float(ppo) - 40000, abs=1.0)
    cards = [
        {
            "card_id": f"c{i}",
            "result": {
                "own": {
                    "dates": {"from": "2026-10-01", "to": "2026-10-30"},
                    "days": 30,
                    "delta": {"p50": {"dgmv": 0.0, "dprofit": n}},
                }
            },
        }
        for i, n in enumerate(nets)
    ]
    _gmv, uplift, counted = month_plan.uplift_in_month(cards, d_(2026, 10, 1), d_(2026, 10, 31))
    baseline = 1_000_000.0
    assert counted == 3
    assert (baseline + uplift) - baseline == pytest.approx(sum(nets))
    # the baseline is the one known-cost profit figure
    monkeypatch.setattr(
        plan_aggregate,
        "shop_profit_of",
        lambda view: NS(json=lambda: {"profit": baseline, "margin_pct": 5.0}),
    )
    env = NS(
        as_of=d_(2026, 10, 30),
        shop_gmv_30d=1.0,
        shop_orders_30d=1,
        metrics=NS(aov=None, views=None, clicks=None, ctr=None, ctor=None),
        view=None,
    )
    assert plan_aggregate._today(env)["profit_30d"] == baseline


def test_card_margin_is_all_the_products_purchases_together():
    """#75: Biên đóng góp = Σ contribution ÷ Σ doanh thu thực covered, over every purchase of the
    product (with a discount, without, and discount-unknown lines together)."""
    from types import SimpleNamespace as NS

    from juli_backend.services.shopee_builder.outcome import scope_contribution_margin_pct

    lines = [  # (doanh thu thực covered, contribution before ads and AFF): with / without / unknown
        (Decimal(400), Decimal(72)),
        (Decimal(600), Decimal(240)),
        (Decimal(100), Decimal(20)),
    ]
    paid = sum(p for p, _ in lines)
    contribution = sum(c for _, c in lines)
    row = NS(buyer_paid_covered=paid, organic_contribution=contribution)
    profit = NS(products={"p": row}, buyer_paid_covered=paid, organic_contribution=contribution)
    got = scope_contribution_margin_pct(profit, ["p"])
    assert got == (contribution / paid * 100).quantize(Decimal("0.1"))  # 332 / 1100 = 30.2
    assert got == Decimal("30.2")
    assert got != Decimal("18.0") and got != Decimal("40.0")  # neither side alone
