"""P96d: the compare table tells the versions apart (owner report 2026-11-06, ORY).

Four vouchers (5k/99k, 7.500/149k, 10k/199k, 15k/300k) showed the same "Chỉ số chính" AOV after for
P1-P3 and no break-even; P4 stood on another base without saying so. Synthetic reco shop (SQLite).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import TypeAdapter

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
SPEC = TypeAdapter(sp.VersionSpec)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


async def compare(session, shop, *versions):
    await materialize.backfill_shop(session, shop.shop_id)  # P98: the stored funnel
    out = await builder.evaluate_versions(
        session, shop.shop_id, [SPEC.validate_python(v) for v in versions], as_of=AS_OF, now=NOW
    )
    return out["versions"]


def voucher(value, min_spend, **kw):
    return {
        "kind": "voucher",
        "discount_type": "amount",
        "value": value,
        "min_spend": min_spend,
        **kw,
    }


def driver_after(outcome, key="aov"):
    return next(m for m in outcome["driver"]["metrics"] if m["key"] == key)["after_p50"]


async def test_each_versions_driver_follows_its_own_size(session, shop):
    small, big = await compare(session, shop, voucher(5000, 100_000), voucher(10_000, 100_000))
    before = next(m for m in small["driver"]["metrics"] if m["key"] == "aov")["before"]
    # P98 / ADR-122 d.6, E2: the AOV driver is the reach to the minimum (the same minimum here),
    # the voucher's size is its cost -- each version carries its own
    assert driver_after(big) >= before and driver_after(small) >= before
    assert big["result"]["cost"]["total"] > small["result"]["cost"]["total"] > 0


async def test_each_version_states_its_base_and_same_base_same_today(session, shop):
    shop_a, shop_b, product = await compare(
        session,
        shop,
        voucher(5000, 100_000, scope="shop"),
        voucher(10_000, 150_000, scope="shop"),
        voucher(5000, 100_000, scope="product", item_ids=["1001"]),
    )
    assert shop_a["base"]["scope"] == "shop" and shop_a["base"]["items"] == []
    assert product["base"]["scope"] == "product" and product["base"]["items"] == ["1001"]
    for key in ("aov", "margin_pct"):
        assert shop_a["base"][key] == shop_b["base"][key]  # same base, same "hôm nay"
    assert shop_a["base"]["aov"] != product["base"]["aov"]
