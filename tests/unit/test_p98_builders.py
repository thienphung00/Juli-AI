"""P98 W2-G: Biên cuối per variation, combo pricing on Biên cuối, the request models and the three
read-only builder endpoints (combo / KOL / ads). Synthetic shop; SQLite."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from juli_backend.services.shopee_builder import combo_options as co
from juli_backend.services.shopee_builder import specs_p98 as sp
from juli_backend.services.shopee_builder import variations as var
from tests.support.api import authenticate, build_app, client_for
from tests.support.builders import make_shop, make_user
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_combo_options import ECO, GLOVE, cost
from tests.unit.test_shopee_builder import INFO, SCHEDULE, SNAPS
from tests.unit.test_shopee_kol import ALPHA, BETA, _seed

D = Decimal
B = "/v1/demo/shopee/builder"
RATES = var.Rates(D("0.02"), D("0.03"), D("0.05"))  # 10 % in all


# ==================== Biên cuối per variation


def _rows(**kw):
    from juli_backend.services.shopee_analytics.rules_view import ProfitRules

    rules = ProfitRules(sku_cost={"BOX": D(30_000), "BOX1": D(30_000)})
    return var.variation_rows(
        "2001", INFO, SNAPS, rules=rules, schedule=SCHEDULE, on=date(2026, 10, 7), **kw
    )


def test_final_margin_is_price_margin_less_the_measured_rates():
    rows = {r["variation_id"]: r for r in _rows(product_rates=RATES)}
    assert rows["v3"]["margin_pct"] == 55.6  # existing key, unchanged
    assert rows["v3"]["final_margin_pct"] == 45.6
    assert rows["v3"]["final_margin_basis"] == "product"
    assert rows["v3"]["final_rates"]["ads_pct"] == 5.0


def test_a_variation_with_history_uses_its_own_rates_else_the_products():
    own = var.Rates(D("0.10"), D(0), D(0))
    rows = {r["variation_id"]: r for r in _rows(product_rates=RATES, sku_rates={"BOX×3": own})}
    assert rows["v3"]["final_margin_basis"] == "variation"
    assert rows["v3"]["final_margin_pct"] == pytest.approx(rows["v3"]["margin_pct"] - 10, abs=0.1)
    assert rows["v5"]["final_margin_basis"] == "product"


def test_no_rates_or_no_cost_gives_no_final_margin():
    assert all(r["final_margin_pct"] is None and r["final_margin_basis"] is None for r in _rows())
    from juli_backend.services.shopee_analytics.rules_view import ProfitRules

    no_cost = var.variation_rows(
        "2001",
        INFO,
        SNAPS,
        rules=ProfitRules(),
        schedule=SCHEDULE,
        on=date(2026, 10, 7),
        product_rates=RATES,
    )
    assert all(r["margin_pct"] is None and r["final_margin_pct"] is None for r in no_cost)


class _Pb:
    def __init__(self, revenue, voucher, commission, excluded=None):
        self.revenue, self.voucher, self.commission = D(revenue), D(voucher), D(commission)
        self.excluded_reason = excluded


class _Ln:
    def __init__(self, sku):
        self.sku = sku


def test_measured_rates_split_by_sku_and_allocate_ads_by_revenue():
    pairs = [
        (_Ln("A"), _Pb(100, 5, 10)),
        (_Ln("B"), _Pb(300, 0, 0)),
        (_Ln("B"), _Pb(999, 99, 99, excluded="cancelled")),  # left out
    ]
    product, by_sku = var.measured_rates(pairs, D(40))
    assert product == var.Rates(D("0.0125"), D("0.025"), D("0.1"))
    assert by_sku["A"] == var.Rates(D("0.05"), D("0.1"), D("0.1"))
    assert by_sku["B"].voucher == 0 and by_sku["B"].ads == D("0.1")
    assert var.measured_rates([], D(5)) == (None, {})


# ==================== combo pricing on Biên cuối

ECO_R = co.Economics(ECO.schedule, ECO.on, {"100": RATES})
OPTS = co.generate([GLOVE], {"100": ["a"]}, co.Packs(sizes=(3,)), co.Rules())


def test_rows_expose_both_margins_and_the_floor_reads_the_final_one():
    plain = co.price(OPTS, co.PriceRule(), ECO, floor=D(0))[0]
    rated = co.price(OPTS, co.PriceRule(), ECO_R, floor=D(0))[0]
    assert plain.final_margin_pct is None and plain.floor_basis == "price"
    assert rated.price == plain.price and rated.margin_pct == plain.margin_pct
    assert rated.final_margin_pct == plain.margin_pct - 10
    assert rated.floor_basis == "final"
    # a floor between the two margins: breached on Biên cuối only
    floor = rated.margin_pct - 5
    assert co.price(OPTS, co.PriceRule(), ECO, floor=floor)[0].below_floor is False
    assert co.price(OPTS, co.PriceRule(), ECO_R, floor=floor)[0].below_floor is True


def test_target_margin_solves_for_biên_cuối():
    rule = co.PriceRule(kind="target_margin", target_margin_pct=D(30))
    final = co.price(OPTS, rule, ECO_R)[0]
    price_only = co.price(OPTS, rule, ECO)[0]
    assert final.price > price_only.price
    assert final.final_margin_pct >= D(30) and "biên cuối" in final.basis
    assert price_only.margin_pct >= D(30) and "biên cuối" not in price_only.basis


def test_a_member_without_rates_falls_back_to_the_price_margin():
    other = co.Economics(ECO.schedule, ECO.on, {"999": RATES})
    row = co.price(OPTS, co.PriceRule(), other, floor=D(0))[0]
    assert row.final_margin_pct is None and row.floor_basis == "price"
    assert row.margin_pct is not None


def test_a_member_without_cost_stays_chua_tinh_with_rates():
    nocost = co.ProductIn(
        "100", "G", (co.VariationIn("a", "S", D(100_000), cost(None), sold_30d=True),)
    )
    opts = co.generate([nocost], {"100": ["a"]}, co.Packs(sizes=(3,)), co.Rules())
    row = co.price(opts, co.PriceRule(), ECO_R)[0]
    assert row.margin_pct is None and row.final_margin_pct is None


# ==================== request models


def test_combo_request_bounds():
    ok = {"products": [{"item_id": "1001", "variation_ids": [""]}]}
    assert sp.ComboRequest(**ok).pack_sizes == [3, 5, 10]
    bad = [
        {**ok, "pack_sizes": [1]},
        {**ok, "pack_sizes": [101]},
        {**ok, "pack_sizes": []},
        {"products": []},
        {"products": [{"item_id": "1001", "variation_ids": []}]},
        {**ok, "rules": {"max_options": 0}},
        {**ok, "rules": {"max_options": 201}},
        {**ok, "price_rule": {"kind": "target_margin"}},
        {**ok, "price_rule": {"kind": "target_margin", "target_margin_pct": 100}},
        {**ok, "price_rule": {"kind": "per_box"}},
        {**ok, "price_rule": {"round_to": 7}},
        {**ok, "floor_pct": 101},
        {**ok, "overrides": {"k": 0}},
        {**ok, "bundles": [{"items": [{"item_id": "1001", "quantity": 1}]}]},
        {
            **ok,
            "bundles": [
                {"items": [{"item_id": "1001", "quantity": 1}, {"item_id": "9", "quantity": 1}]}
            ],
        },
        {**ok, "extra": 1},
    ]
    for body in bad:
        with pytest.raises(ValidationError):
            sp.ComboRequest(**body)


def test_kol_request_bounds():
    base = {"kol_key": "k", "item_ids": ["1001"], "commission_pct": 10}
    sp.KolRequest(kols=[base])
    sp.KolRequest(kols=[{**base, "sample": {"item_id": "1001", "qty": 2, "ship_fee": 20_000}}])
    for bad in (
        {**base, "commission_pct": 51},
        {**base, "commission_pct": -1},
        {**base, "item_ids": []},
        {**base, "item_ids": ["1", "1"]},
        {**base, "sample": {"item_id": "9", "qty": 1}},
        {**base, "sample": {"item_id": "1001", "qty": 0}},
        {**base, "sample": {"item_id": "1001", "qty": 51}},
        {**base, "sample": {"item_id": "1001", "qty": 1, "ship_fee": -1}},
    ):
        with pytest.raises(ValidationError):
            sp.KolRequest(kols=[bad])
    with pytest.raises(ValidationError):
        sp.KolRequest(kols=[base, base])


def test_ads_request_bounds():
    base = {
        "campaign": "group",
        "item_ids": ["1001", "1002"],
        "daily_budget": 100_000,
        "start_date": "2026-10-10",
    }
    sp.AdsRequest(setups=[base])
    sp.AdsRequest(
        setups=[
            {
                **base,
                "campaign": "single",
                "item_ids": ["1001"],
                "roas": {"mode": "custom", "target": 3.5},
                "end_date": "2026-10-20",
            }
        ]
    )
    for bad in (
        {**base, "daily_budget": 99_999},
        {**base, "campaign": "single"},  # two products
        {**base, "roas": {"mode": "custom"}},
        {**base, "roas": {"mode": "system", "target": 3}},
        {**base, "roas": {"mode": "custom", "target": 51}},
        {**base, "end_date": "2026-10-09"},
        {**base, "end_date": "2028-01-01"},
        {**base, "item_ids": []},
        {**base, "campaign": "x"},
    ):
        with pytest.raises(ValidationError):
            sp.AdsRequest(setups=[bad])


# ==================== routes


@pytest.fixture
async def reco(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


@pytest.fixture
async def seller(session, reco):
    app = build_app(session)
    authenticate(app, user=reco.user, shop=reco.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


COMBO = {
    "products": [{"item_id": "1001", "variation_ids": [""]}],
    "pack_sizes": [3, 5],
    "as_of": AS_OF.isoformat(),
}


async def test_combo_end_to_end_counts_rows_both_margins_and_inputs(seller):
    r = await seller.post(f"{B}/combo/options", json={**COMBO, "floor_pct": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == {
        "total": 2,
        "kept": 2,
        "over_cap": 0,
        "by_form": {"multi_pack": 2, "bundle": 0},
    }
    assert [row["units"] for row in body["rows"]] == [3, 5]
    row = body["rows"][0]
    assert row["margin_pct"] is not None and row["final_margin_pct"] is not None
    assert row["final_margin_pct"] <= row["margin_pct"]
    assert row["floor_basis"] == "final" and row["final_rates"]["ads_pct"] >= 0
    assert row["inputs"]["item_ids"] == ["1001"] and row["inputs"]["members"][0]["cogs_per_unit"]
    assert body["variations"]["1001"][0]["final_margin_basis"] in ("variation", "product")
    assert body["warnings"] == [] and "Biên cuối" in body["margin_basis"]["final"]


async def test_combo_rules_target_margin_override_and_cap(seller):
    r = await seller.post(
        f"{B}/combo/options",
        json={
            **COMBO,
            "pack_sizes": [3, 5, 10],
            "rules": {"max_options": 2},
            "price_rule": {"kind": "target_margin", "target_margin_pct": 20},
        },
    )
    body = r.json()
    assert body["count"]["total"] == 3 and body["count"]["over_cap"] == 1 and len(body["rows"]) == 2
    assert all(row["final_margin_pct"] >= 20 for row in body["rows"])
    key = body["rows"][0]["key"]
    manual = (
        await seller.post(f"{B}/combo/options", json={**COMBO, "overrides": {key: 123_000}})
    ).json()
    first = manual["rows"][0]
    assert first["overridden"] is True and first["price"] == 123_000


async def test_combo_errors(seller):
    unknown = await seller.post(
        f"{B}/combo/options",
        json={**COMBO, "products": [{"item_id": "nope", "variation_ids": [""]}]},
    )
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "product_not_found"
    novar = await seller.post(
        f"{B}/combo/options",
        json={**COMBO, "products": [{"item_id": "1001", "variation_ids": ["zzz"]}]},
    )
    assert novar.status_code == 404 and novar.json()["detail"]["code"] == "variation_not_found"
    assert (
        await seller.post(f"{B}/combo/options", json={**COMBO, "pack_sizes": [1]})
    ).status_code == 422
    assert (await seller.post(f"{B}/combo/options", json={})).status_code == 422


async def test_ads_setup_returns_measured_facts_and_refuses_low_budget(seller):
    setup = {
        "campaign": "group",
        "item_ids": ["1001", "1002"],
        "daily_budget": 150_000,
        "roas": {"mode": "custom", "target": 3.5},
        "start_date": "2026-10-10",
        "end_date": "2026-10-16",
    }
    r = await seller.post(f"{B}/ads/setup", json={"setups": [setup], "as_of": AS_OF.isoformat()})
    assert r.status_code == 200, r.text
    s = r.json()["setups"][0]
    assert (
        s["days"] == 7
        and s["total_budget"] == 1_050_000
        and s["campaign_label"] == "Chiến dịch nhóm"
    )
    assert {p["item_id"] for p in s["products"]} == {"1001", "1002"}
    assert all("roas_direct" in p and "break_even_roas" in p for p in s["products"])
    low = await seller.post(f"{B}/ads/setup", json={"setups": [{**setup, "daily_budget": 50_000}]})
    assert low.status_code == 422
    ghost = await seller.post(f"{B}/ads/setup", json={"setups": [{**setup, "item_ids": ["nope"]}]})
    assert ghost.status_code == 404


async def test_kol_setup_facts_and_errors(session):
    seeded = await _seed(session)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        table = (
            await client.get("/v1/demo/shopee/kols", params={"as_of": AS_OF.isoformat()})
        ).json()
        alpha = next(r["kol_key"] for r in table["rows"] if r["handle"] == ALPHA)
        body = {
            "as_of": AS_OF.isoformat(),
            "kols": [
                {
                    "kol_key": alpha,
                    "item_ids": ["1001", "1003"],
                    "commission_pct": 12,
                    "sample": {"item_id": "1001", "qty": 2, "ship_fee": 20_000},
                }
            ],
        }
        r = await client.post(f"{B}/kol/setup", json=body)
        assert r.status_code == 200, r.text
        s = r.json()["setups"][0]
        measured = {p["item_id"]: p["measured"] for p in s["products"]}
        assert measured["1001"]["orders"] > 0 and measured["1003"] is None
        assert s["sample"]["cost"] == 2 * s["sample"]["unit_cost"] + 20_000
        assert s["inputs"]["commission_pct"] == 12
        gone = await client.post(
            f"{B}/kol/setup",
            json={"kols": [{"kol_key": "nobody", "item_ids": ["1001"], "commission_pct": 5}]},
        )
        assert gone.status_code == 404 and gone.json()["detail"]["code"] == "kol_not_found"
        bad = await client.post(
            f"{B}/kol/setup",
            json={"kols": [{"kol_key": alpha, "item_ids": ["1001"], "commission_pct": 90}]},
        )
        assert bad.status_code == 422
    app.dependency_overrides.clear()
    assert BETA


async def test_routes_need_the_active_shop_and_stay_in_their_tenant(session, reco):
    anon = build_app(session)
    async with client_for(anon) as client:
        for path, payload in (("combo/options", COMBO), ("kol/setup", {}), ("ads/setup", {})):
            assert (await client.post(f"{B}/{path}", json=payload)).status_code in (401, 403)
    other_user = await make_user(session)
    other_shop = await make_shop(session, other_user)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=other_user, shop=other_shop)
    async with client_for(app) as client:
        r = await client.post(f"{B}/combo/options", json=COMBO)
        assert r.status_code in (404, 409), r.text  # no numbers of its own; never the other shop's
        assert "1001" not in r.text or r.status_code != 200
    app.dependency_overrides.clear()
