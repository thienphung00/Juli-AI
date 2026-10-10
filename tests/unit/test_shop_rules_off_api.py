"""P14-F: rule fields for what no TikTok API gives Juli (contract p14-rules-and-cost.md §3).

Each field is optional and unset by default; out-of-range values are refused
with a plain message; the GET / PUT / DELETE routes carry them like every other
rule; one shop never reads another's; the typed accessor the ranking layer will
read (``shop_economics``) turns them into decimals, slots and helpers that
return ``None`` rather than guess.
"""

from __future__ import annotations

import uuid
from datetime import time
from decimal import Decimal

import pytest

from juli_backend.services import shop_rules
from juli_backend.services.shop_rules import LiveSlot, ShopEconomics
from tests.unit.test_shop_rules import _client, _shop

GOOD: list[tuple[str, str | None, object, object]] = [
    ("sku_cost", "1729700293904534135", "85000", 85000),
    ("default_gross_margin_pct", None, 35, 35),
    ("default_max_discount_pct", None, "12.5", 12.5),
    ("default_max_discount_pct", None, 0, 0),
    ("program_fee_pct", None, 4, 4),
    ("joins_platform_campaigns", None, True, True),
    (
        "platform_campaign_note",
        None,
        "  Đã đăng ký 11.11 (giảm 15 %)  ",
        "Đã đăng ký 11.11 (giảm 15 %)",
    ),
    ("target_roas", None, 6, 6),
    ("gmv_max_daily_budget", None, 500000, 500000),
    (
        "live_schedule",
        None,
        [
            {"days": ["fri", "mon", "wed"], "start": "20:00", "end": "22:00"},
            {"days": ["sat"], "start": "22:30", "end": "01:00"},
            {"days": ["mon", "wed", "fri"], "start": "20:00", "end": "22:00"},
        ],
        [
            {"days": ["mon", "wed", "fri"], "start": "20:00", "end": "22:00"},
            {"days": ["sat"], "start": "22:30", "end": "01:00"},
        ],
    ),
]

BAD: list[tuple[str, str | None, object]] = [
    ("sku_cost", None, 1000),  # needs a SKU
    ("sku_cost", "sku-1", -1),
    ("default_gross_margin_pct", None, 0),
    ("default_gross_margin_pct", None, 100),
    ("default_gross_margin_pct", "x", 30),  # shop-wide: no scope
    ("default_max_discount_pct", None, 101),
    ("program_fee_pct", None, 100),
    ("program_fee_pct", None, "abc"),
    ("joins_platform_campaigns", None, "yes"),
    ("joins_platform_campaigns", None, 1),
    ("platform_campaign_note", None, "   "),
    ("platform_campaign_note", None, "x" * 501),
    ("target_roas", None, 0),
    ("target_roas", None, 101),
    ("target_roas", None, True),
    ("gmv_max_daily_budget", None, -5),
    ("gmv_max_daily_budget", None, 10_000_000_001),
    ("live_schedule", None, "T2 20:00-22:00"),
    ("live_schedule", None, [{"days": [], "start": "20:00", "end": "22:00"}]),
    ("live_schedule", None, [{"days": ["t2"], "start": "20:00", "end": "22:00"}]),
    ("live_schedule", None, [{"days": ["mon"], "start": "24:00", "end": "22:00"}]),
    ("live_schedule", None, [{"days": ["mon"], "start": "8:00", "end": "22:00"}]),
    ("live_schedule", None, [{"days": ["mon"], "start": "20:00", "end": "20:00"}]),
    ("live_schedule", None, [{"days": ["mon"], "start": "20:00"}]),
    (
        "live_schedule",
        None,
        [{"days": ["mon"], "start": "20:00", "end": "22:00", "note": "x"}],
    ),
    (
        "live_schedule",
        None,
        [{"days": ["mon"], "start": f"{h:02d}:00", "end": "23:59"} for h in range(15)],
    ),
]


@pytest.mark.parametrize(("key", "scope", "value", "expected"), GOOD)
def test_valid_values_are_normalised(key, scope, value, expected):
    assert shop_rules.validate_rule(key, scope or "", value) == ((scope or ""), expected)


@pytest.mark.parametrize(("key", "scope", "value"), BAD)
def test_out_of_range_values_are_refused(key, scope, value):
    with pytest.raises(shop_rules.RuleValidationError):
        shop_rules.validate_rule(key, scope or "", value)


def test_every_new_key_is_a_known_rule_and_only_sku_cost_is_scoped():
    assert set(shop_rules.OFF_API_RULE_KEYS) <= set(shop_rules.RULE_KEYS)
    assert set(shop_rules.OFF_API_RULE_KEYS) & shop_rules.SCOPED_RULES == {"sku_cost"}


@pytest.mark.asyncio
async def test_unset_by_default_and_the_accessor_returns_nothing_to_guess_with(session):
    shop = await _shop(session, "d")
    rules = await shop_rules.get_rules(session, shop.id)
    assert rules.sku_cost == {}
    for key in shop_rules.OFF_API_RULE_KEYS:
        if key != "sku_cost":
            assert getattr(rules, key) is None, key
    economics = await shop_rules.shop_economics(session, shop.id)
    assert economics == ShopEconomics()
    assert economics.unit_cost(sku_id="s", product_id="p", unit_price=Decimal(100)) is None
    assert economics.break_even_roas(sku_id="s", product_id="p", unit_price=Decimal(100)) is None
    assert economics.max_discount_pct("s") is None


@pytest.mark.asyncio
async def test_the_accessor_types_every_field_and_its_precedence(session):
    shop = await _shop(session, "e")
    other = await _shop(session, "f")
    user = uuid.uuid4()
    writes = [
        ("product_cost", "p1", 60000),
        ("sku_cost", "s1", 50000),
        ("max_discount_pct", "s1", 10),
        ("min_margin_pct", None, 20),
        ("default_gross_margin_pct", None, 40),
        ("default_max_discount_pct", None, 15),
        ("program_fee_pct", None, 5),
        ("joins_platform_campaigns", None, False),
        ("platform_campaign_note", None, "Chưa đăng ký"),
        ("target_roas", None, "4.5"),
        ("gmv_max_daily_budget", None, 300000),
        ("live_schedule", None, [{"days": ["tue"], "start": "21:00", "end": "23:00"}]),
    ]
    for key, scope, value in writes:
        await shop_rules.set_rule(
            session,
            shop.id,
            rule_key=key,
            scope_ref=scope,
            value=value,
            set_by="seller",
            set_by_user_id=user,
        )
    await session.commit()

    e = await shop_rules.shop_economics(session, shop.id)
    assert e.sku_cost == {"s1": Decimal(50000)} and e.product_cost == {"p1": Decimal(60000)}
    assert (e.default_gross_margin_pct, e.min_margin_pct) == (Decimal(40), Decimal(20))
    assert e.program_fee_pct == Decimal(5) and e.joins_platform_campaigns is False
    assert e.platform_campaign_note == "Chưa đăng ký"
    assert (e.target_roas, e.gmv_max_daily_budget) == (Decimal("4.5"), Decimal(300000))
    assert e.live_schedule == (LiveSlot(days=("tue",), start=time(21), end=time(23)),)

    price = Decimal(100000)
    # SKU cost beats product cost beats the default margin.
    assert e.unit_cost(sku_id="s1", product_id="p1", unit_price=price) == Decimal(50000)
    assert e.unit_cost(sku_id="s2", product_id="p1", unit_price=price) == Decimal(60000)
    assert e.unit_cost(sku_id="s2", product_id="p2", unit_price=price) == Decimal(60000)
    # margin = (100k − 50k − 5 % fee) / 100k = 0.45; break-even ROAS = 1 / 0.45.
    assert e.gross_margin(sku_id="s1", product_id="p1", unit_price=price) == Decimal("0.45")
    assert e.break_even_roas(sku_id="s1", product_id="p1", unit_price=price) == 1 / Decimal("0.45")
    assert e.max_discount_pct("s1") == Decimal(10)
    assert e.max_discount_pct("s9") == Decimal(15)

    assert await shop_rules.shop_economics(session, other.id) == ShopEconomics()


@pytest.mark.asyncio
async def test_the_routes_carry_the_new_fields(engine, session):
    shop = await _shop(session, "r")
    async with _client(engine, shop) as client:
        empty = (await client.get("/v1/demo/rules")).json()["data"]
        puts = [
            await client.put(
                "/v1/demo/rules/sku_cost",
                json={"scope_ref": "1729700293904534135", "value": 85000, "set_by": "seller"},
            ),
            await client.put(
                "/v1/demo/rules/joins_platform_campaigns",
                json={"value": True, "set_by": "team"},
            ),
            await client.put(
                "/v1/demo/rules/live_schedule",
                json={
                    "value": [{"days": ["sun", "sat"], "start": "19:30", "end": "21:00"}],
                    "set_by": "seller",
                },
            ),
        ]
        bad = await client.put("/v1/demo/rules/target_roas", json={"value": 0, "set_by": "seller"})
        after = (await client.get("/v1/demo/rules")).json()["data"]
        unset = await client.delete("/v1/demo/rules/joins_platform_campaigns")
        final = (await client.get("/v1/demo/rules")).json()["data"]

    assert empty["sku_cost"] == {} and empty["weekdays"][0] == "mon"
    for key in shop_rules.OFF_API_RULE_KEYS:
        if key != "sku_cost":
            assert empty[key] is None, key
    assert [p.status_code for p in puts] == [200, 200, 200], [p.text for p in puts]
    assert bad.status_code == 422 and "target_roas" in bad.json()["detail"]
    assert after["sku_cost"]["1729700293904534135"]["value"] == 85000
    assert after["joins_platform_campaigns"]["value"] is True
    assert after["joins_platform_campaigns"]["set_by"] == "team"
    assert after["live_schedule"]["value"] == [
        {"days": ["sat", "sun"], "start": "19:30", "end": "21:00"}
    ]
    assert unset.status_code == 204 and final["joins_platform_campaigns"] is None
