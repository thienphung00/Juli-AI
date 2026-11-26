"""Owner #99 item 3: Tổng quan lists every ad spend. Beside DVHT Sản phẩm and DVHT Shop+, a
"Livestream" row and a "Khác" row (unknown types and spend no type explains) appear at shop level,
only when they spent something; the four rows add up to the shop's ads total. Synthetic only."""

from __future__ import annotations

from decimal import Decimal

from juli_backend.services.analytics_agent.labels import SHOPEE_SOURCES
from juli_backend.services.shopee_analytics.channel_split import AD_ROW_LABELS, split_rows
from juli_backend.services.shopee_analytics.funnel import base_from_rows
from tests.unit.test_p100c_channel_split import _TYPES, _by_key, _rows

D = Decimal
TYPES = {
    **_TYPES,
    "live_auto": {"gmv": D(500_000), "orders": D(3), "spend": D(150_000)},
    "brand_mystery": {"gmv": D(100_000), "orders": D(1), "spend": D(40_000)},
}
AD_ROWS = ("ads_product", "ads_shop", "ads_livestream", "ads_other")


def _spend(rows, key):
    # a row absent, or DVHT Shop+ without any report row ("—"), spent nothing to add
    spend = rows[key]["spend"] if key in rows else None
    return D(0) if spend is None else D(str(spend))


def test_livestream_and_other_rows_add_up_to_the_ads_total():
    total = D(2_400_000)  # 2.31 tr typed + 90k the report cannot place
    rows = split_rows(base_from_rows(_rows(), "s"), ad_types=TYPES, ads_total=total)
    r = _by_key(rows)
    assert r["ads_livestream"]["spend"] == 150_000 and r["ads_livestream"]["gmv"] == 500_000
    assert r["ads_other"]["spend"] == 40_000 + 90_000
    assert r["ads_livestream"]["label"] == "Livestream" and r["ads_other"]["label"] == "Khác"
    assert r["ads_livestream"]["parent"] == r["ads_other"]["parent"] == "ads"
    assert sum(_spend(r, k) for k in AD_ROWS) == total
    keys = [x["key"] for x in rows]
    assert keys.index("ads_shop") < keys.index("ads_livestream") < keys.index("ads_other")
    assert keys.index("ads_other") < keys.index("affiliate")


def test_no_spend_no_row():
    r = _by_key(split_rows(base_from_rows(_rows(), "s"), ad_types=_TYPES, ads_total=D(2_120_000)))
    assert "ads_livestream" not in r and "ads_other" not in r
    assert sum(_spend(r, k) for k in AD_ROWS) == D(2_120_000)


def test_a_product_has_no_ad_type_rows():
    base = base_from_rows(_rows(), "s", item_ids=("p1",))
    r = _by_key(split_rows(base, ads_total=D(1)))
    assert not set(AD_ROWS) & set(r)


def test_labels_are_the_owners_and_chat_knows_them():
    assert AD_ROW_LABELS == {"ads_livestream": "Livestream", "ads_other": "Khác"}
    assert SHOPEE_SOURCES["ads_livestream"] == "Livestream"
    assert SHOPEE_SOURCES["ads_other"] == "Khác"


async def test_seeded_shop_rows_add_up_to_cost_ads(session):
    from juli_backend.services.shopee_analytics import channel_split, materialize
    from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

    seeded = await seed_shopee_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    body = await channel_split.channel_split(session, seeded.shop_id, period="7d", as_of=CUR_END)
    r = _by_key(body["rows"])
    total = D(str(body["kpis"]["cost_ads"]))
    assert total > 0
    assert sum(_spend(r, k) for k in AD_ROWS) == total
