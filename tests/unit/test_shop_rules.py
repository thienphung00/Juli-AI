"""AC-8.3 (fast track P8-C): the per-shop rule store (ADR-109 d.12).

Service and routes against SQLite: every value records set_by (team | seller),
set_by_user_id and set_at; defaults apply until a value is set; out-of-range
values are refused with a plain message; price is never an auto lever; the CSV
cost import writes good rows and reports bad ones; one shop never reads or
writes another's rules. The two-tenant proof under RLS is
``tests/integration/test_run_changes_two_tenant.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import Shop, User
from juli_backend.services import shop_rules
from juli_backend.services.run_changes import band_breaches

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


async def _shop(session, label: str) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8492{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name=f"{label} shop", is_active=True)
    session.add_all([user, shop])
    await session.commit()
    return shop


@pytest.mark.asyncio
async def test_defaults_apply_until_a_value_is_set(session):
    shop = await _shop(session, "a")
    rules = await shop_rules.get_rules(session, shop.id)
    assert rules.max_open_cards.value == 30 and rules.max_open_cards.set_by is None
    assert rules.content_tone is None and rules.banned_terms.value == []
    assert await shop_rules.content_tone(session, shop.id) is None
    assert await shop_rules.banned_terms(session, shop.id) == []
    assert set(rules.auto_levers.value) == {"title", "description", "attributes", "image"}
    assert rules.stability_band == {} and rules.min_margin_pct is None
    assert await shop_rules.stability_bands(session, shop.id) == {}
    assert await shop_rules.configured_max_open_cards(session, shop.id) is None


@pytest.mark.asyncio
async def test_a_value_records_who_set_it_and_when_and_can_be_replaced_and_unset(session):
    shop = await _shop(session, "a")
    team_member = uuid.uuid4()
    await shop_rules.set_rule(
        session,
        shop.id,
        rule_key="stability_band",
        scope_ref="ctr",
        value=3,
        set_by="team",
        set_by_user_id=None,
        now=NOW,
    )
    rules = await shop_rules.get_rules(session, shop.id)
    band = rules.stability_band["ctr"]
    assert (band.value, band.set_by, band.set_at) == (3, "team", NOW.replace(tzinfo=None))

    await shop_rules.set_rule(
        session,
        shop.id,
        rule_key="stability_band",
        scope_ref="ctr",
        value="2.5",
        set_by="seller",
        set_by_user_id=team_member,
    )
    band = (await shop_rules.get_rules(session, shop.id)).stability_band["ctr"]
    assert (band.value, band.set_by, band.set_by_user_id) == (2.5, "seller", team_member)
    assert await shop_rules.stability_bands(session, shop.id) == {"ctr": Decimal("2.5")}

    assert await shop_rules.delete_rule(
        session, shop.id, rule_key="stability_band", scope_ref="ctr"
    )
    assert not await shop_rules.delete_rule(
        session, shop.id, rule_key="stability_band", scope_ref="ctr"
    )
    assert await shop_rules.stability_bands(session, shop.id) == {}


@pytest.mark.parametrize(
    ("rule_key", "scope_ref", "value"),
    [
        ("stability_band", "ctr", 0),
        ("stability_band", "unknown_metric", 3),
        ("stability_band", "", 3),
        ("product_cost", "p-1", -1),
        ("min_margin_pct", "", 100),
        ("max_discount_pct", "sku-1", 101),
        ("max_open_cards", "", 31),
        ("max_open_cards", "", 4),
        ("max_open_cards", "", 0),
        ("max_open_cards", "x", 10),
        ("content_tone", "", ""),
        ("content_tone", "", "x" * 301),
        ("content_tone", "", ["not text"]),
        ("content_tone", "p-1", "Thân thiện"),
        ("banned_terms", "", "not a list"),
        ("banned_terms", "", [f"từ {i}" for i in range(51)]),
        ("banned_terms", "", ["x" * 101]),
        ("auto_levers", "", ["title", "price"]),
        ("auto_levers", "", ["banner"]),
        ("protected_terms", "", "not a list"),
        ("no_such_rule", "", 1),
    ],
)
def test_out_of_range_values_are_refused(rule_key, scope_ref, value):
    with pytest.raises(shop_rules.RuleValidationError):
        shop_rules.validate_rule(rule_key, scope_ref, value)


def test_set_by_is_team_or_seller_only():
    assert shop_rules.validate_rule("max_open_cards", "", 5) == ("", 5)
    assert shop_rules.validate_rule("max_open_cards", "", 30) == ("", 30)
    with pytest.raises(shop_rules.RuleValidationError):
        shop_rules.rules._validate_set_by("juli")


@pytest.mark.asyncio
async def test_the_cost_csv_imports_good_rows_and_reports_bad_ones(session):
    shop = await _shop(session, "a")
    csv_text = '﻿product_id,cost,name\np-1,120000,Nồi\np-2,abc,Chảo\n,5000,\np-3,"1,500",x\n'
    result = await shop_rules.import_product_costs_csv(
        session, shop.id, csv_text, set_by="team", set_by_user_id=None
    )
    assert result.imported == 2
    assert [line.split(":")[0] for line in result.errors] == ["line 3", "line 4"]
    costs = (await shop_rules.get_rules(session, shop.id)).product_cost
    assert {k: v.value for k, v in costs.items()} == {"p-1": 120000, "p-3": 1500}
    assert {v.set_by for v in costs.values()} == {"team"}

    with pytest.raises(shop_rules.RuleValidationError):
        await shop_rules.import_product_costs_csv(
            session, shop.id, "sku,price\n", set_by="team", set_by_user_id=None
        )


@pytest.mark.asyncio
async def test_one_shop_never_sees_or_changes_anothers_rules(session):
    shop_a, shop_b = await _shop(session, "a"), await _shop(session, "b")
    await shop_rules.set_rule(
        session,
        shop_a.id,
        rule_key="max_open_cards",
        scope_ref=None,
        value=6,
        set_by="seller",
        set_by_user_id=shop_a.user_id,
    )
    assert await shop_rules.configured_max_open_cards(session, shop_a.id) == 6
    assert await shop_rules.configured_max_open_cards(session, shop_b.id) is None
    assert not await shop_rules.delete_rule(
        session, shop_b.id, rule_key="max_open_cards", scope_ref=None
    )
    assert await shop_rules.configured_max_open_cards(session, shop_a.id) == 6


@pytest.mark.asyncio
async def test_a_stored_open_card_value_below_five_reads_as_five(session):
    """D24.21 (2): values stored under the old 1..5 range clamp into 5..30."""
    from juli_backend.models.run_changes import ShopRule

    shop = await _shop(session, "a")
    session.add(
        ShopRule(
            shop_id=shop.id,
            rule_key="max_open_cards",
            scope_ref="",
            value=2,
            set_by="seller",
            set_at=NOW.replace(tzinfo=None),
        )
    )
    await session.commit()
    assert await shop_rules.max_open_cards(session, shop.id) == 5
    assert await shop_rules.configured_max_open_cards(session, shop.id) == 5


def test_band_breaches_skip_target_metrics_and_missing_readings():
    breaches = band_breaches(
        bands={"ctr": Decimal(3), "impressions": Decimal(3), "gmv_per_order": Decimal(3)},
        impact_pct_by_metric={
            "ctr": Decimal("-0.05"),
            "impressions": Decimal("0.5"),
            "gmv_per_order": None,
        },
        target_metrics={"impressions"},
    )
    assert [(b.metric, b.to_json()["impact_pct"]) for b in breaches] == [("ctr", -5.0)]
    assert (
        band_breaches(
            bands={"ctr": Decimal(3)},
            impact_pct_by_metric={"ctr": Decimal("0.03")},
            target_metrics=set(),
        )
        == []
    ), "exactly on the band is inside it"


# --- routes ----------------------------------------------------------------------


def _client(engine, shop: Shop, *, authenticated: bool = True) -> AsyncClient:
    from juli_backend.api.app import create_app
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    if authenticated:
        application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=shop.user_id
        )
        application.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


@pytest.mark.asyncio
async def test_the_rules_routes_read_write_and_unset(engine, session):
    shop = await _shop(session, "a")
    async with _client(engine, shop) as client:
        empty = await client.get("/v1/demo/rules")
        put = await client.put(
            "/v1/demo/rules/stability_band",
            json={"scope_ref": "ctr", "value": 3, "set_by": "team"},
        )
        cap = await client.put(
            "/v1/demo/rules/max_open_cards", json={"value": 12, "set_by": "seller"}
        )
        too_few = await client.put(
            "/v1/demo/rules/max_open_cards", json={"value": 3, "set_by": "seller"}
        )
        tone = await client.put(
            "/v1/demo/rules/content_tone",
            json={"value": "  Thân thiện, xưng mình  ", "set_by": "team"},
        )
        banned = await client.put(
            "/v1/demo/rules/banned_terms",
            json={"value": ["rẻ nhất", " ", "rẻ nhất", "cam kết"], "set_by": "seller"},
        )
        too_many = await client.put(
            "/v1/demo/rules/banned_terms",
            json={"value": [f"t{i}" for i in range(51)], "set_by": "seller"},
        )
        bad = await client.put(
            "/v1/demo/rules/auto_levers", json={"value": ["price"], "set_by": "seller"}
        )
        bad_set_by = await client.put(
            "/v1/demo/rules/max_open_cards", json={"value": 10, "set_by": "juli"}
        )
        after = await client.get("/v1/demo/rules")
        unset = await client.delete("/v1/demo/rules/stability_band", params={"scope_ref": "ctr"})
        unset_again = await client.delete(
            "/v1/demo/rules/stability_band", params={"scope_ref": "ctr"}
        )

    assert empty.status_code == 200
    data = empty.json()["data"]
    assert data["max_open_cards"]["value"] == 30 and data["max_open_cards"]["set_by"] is None
    assert data["content_tone"] is None and data["banned_terms"]["value"] == []
    assert data["stability_band"] == {}
    assert "ctr" in data["band_metrics"]

    assert put.status_code == 200, put.text
    written = put.json()["data"]
    assert (written["rule_key"], written["scope_ref"], written["value"]) == (
        "stability_band",
        "ctr",
        3,
    )
    assert written["set_by"] == "team"
    assert written["set_by_user_id"] == str(shop.user_id)
    assert written["set_at"]
    assert cap.status_code == 200
    assert too_few.status_code == 422 and "between 5 and 30" in too_few.json()["detail"]
    assert tone.status_code == 200 and tone.json()["data"]["value"] == "Thân thiện, xưng mình"
    assert banned.status_code == 200 and banned.json()["data"]["value"] == ["rẻ nhất", "cam kết"]
    assert too_many.status_code == 422
    assert bad.status_code == 422 and "price" in bad.json()["detail"]
    assert bad_set_by.status_code == 422

    data = after.json()["data"]
    assert data["stability_band"]["ctr"]["value"] == 3
    assert data["max_open_cards"]["value"] == 12 and data["max_open_cards"]["set_by"] == "seller"
    assert data["content_tone"]["value"] == "Thân thiện, xưng mình"
    assert data["content_tone"]["set_by"] == "team"
    assert data["banned_terms"]["value"] == ["rẻ nhất", "cam kết"]
    assert unset.status_code == 204
    assert unset_again.status_code == 404


@pytest.mark.asyncio
async def test_the_rules_routes_need_a_signed_in_caller(engine, session):
    shop = await _shop(session, "a")
    async with _client(engine, shop, authenticated=False) as client:
        resp = await client.get("/v1/demo/rules", headers={"X-Shop-Id": str(shop.id)})
    assert resp.status_code == 401
