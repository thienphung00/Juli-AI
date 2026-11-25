"""Decision #39, M3: Chat's product day rows return the stored product ad cost and None when
every day has no basis. The rows are `query(group_by="day", scope=products)` over the stored
`product_metrics_daily` (the registry rounds money to whole dong). Postgres."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from juli_backend.services.analytics_agent.data_service import ServiceData
from tests.integration.analytics_agent import test_service_data_pg as base
from tests.support.postgres import requires_postgres

pytestmark = requires_postgres
AS_OF = base.AS_OF
world = base.world  # the same synthetic shop and rollback-only connection


async def test_item_daily_returns_the_stored_product_ad_cost(world: Any) -> None:
    sid, f = world
    rows = await ServiceData(f, sid).shop_daily(AS_OF, "1001")
    async with f() as s:
        stored = {
            r.day: r.ads_spend
            for r in (
                await s.execute(
                    text(
                        "select day, sum(ads_spend) ads_spend from product_metrics_daily "
                        "where shop_id = :s and order_type = 'confirmed' and item_id = '1001' "
                        "group by day"
                    ),
                    {"s": sid},
                )
            ).all()
        }
    got = {r["day"]: r["ads_spend"] for r in rows}
    assert any(v is not None for v in stored.values())  # the seed has a basis for the product
    for day, value in got.items():
        want = stored.get(day)
        if want is None:
            assert value is None  # no basis is not 0
        else:
            assert value is not None and abs(value - float(want)) < 1  # whole dong


async def test_item_daily_is_none_on_every_day_when_the_product_has_no_basis(world: Any) -> None:
    sid, f = world
    rows = await ServiceData(f, sid).shop_daily(AS_OF, "no-such-item")
    assert rows and all(r["ads_spend"] is None for r in rows)
    assert all(r["gmv"] is None and not r["complete"] for r in rows)  # missing, never 0
