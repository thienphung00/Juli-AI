"""P97 D85.9 / P98 ADR-122: So sánh shows before -> after for seven metrics, laid out from the one
``result`` (every column a whole scenario, so the funnel holds in each); a metric the option does
not move says "không đổi" with the reason and carries no lift. SQLite."""

from __future__ import annotations

import pytest

from tests.support.shopee_reco import seed_reco_shop
from tests.unit.test_shopee_builder import one


@pytest.fixture
async def shop(session):
    """Synthetic reco shop, owned here so the file imports no ``shop`` name (no suppression)."""
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


KEYS = ["gmv", "margin", "orders", "aov", "ctor", "ctr", "views"]


def rows_of(version):
    ba = version["before_after"]
    return ba, {r["key"]: r for r in ba["rows"]}


def assert_flat_when_unchanged(rows):
    for r in rows.values():
        if r["unchanged"]:
            assert r["reason"]
            if r["after"] is not None:  # no invented lift: the range is the before, three times
                assert r["after"]["low"] == r["after"]["p50"] == r["after"]["high"] == r["before"]


def assert_funnel_holds(version):
    """In every column Lượt xem × CTR × CTOR = Đơn and Đơn × AOV = GMV (ADR-122 d.11.1)."""
    detail = version["result"]["detail"]
    for name in ("before", "low", "likely", "high"):
        c = detail[name]
        if c["views"]:
            assert c["views"] * c["ctr"] / 100 * c["ctor"] / 100 == pytest.approx(
                c["orders"], abs=1
            )
        if c["orders"]:
            assert c["orders"] * c["aov"] == pytest.approx(c["gmv"], abs=1)


async def test_a_voucher_moves_aov_and_ctor_and_leaves_views_ctr_unchanged(session, shop):
    v = await one(
        session, shop, kind="voucher", discount_type="amount", value=10_000, min_spend=100_000
    )
    ba, rows = rows_of(v)
    assert [r["key"] for r in ba["rows"]] == KEYS
    assert [r["label"] for r in ba["rows"]][:2] == ["GMV", "Biên lợi nhuận"]
    gmv, aov = rows["gmv"], rows["aov"]
    # ADR-122 d.6: a minimum-spend voucher drives AOV and the visible-offer CTOR, so đơn moves
    assert gmv["before"] and gmv["after"]["p50"] > gmv["before"]
    assert aov["unchanged"] is False and aov["after"]["p50"] >= aov["before"]
    assert rows["ctor"]["unchanged"] is False and rows["orders"]["unchanged"] is False
    for key in ("ctr", "views"):
        assert rows[key]["unchanged"] is True and "không bịa" in rows[key]["reason"], key
    assert_flat_when_unchanged(rows)
    assert_funnel_holds(v)


async def test_a_title_moves_views_only(session, shop):
    v = await one(
        session,
        shop,
        kind="title",
        item_id="1001",
        title="Găng tay tự hủy sinh học STAHAUS hộp 100 chiếc",
        keywords=["găng tay"],
    )
    ba, rows = rows_of(v)
    assert ba["scope"] == "product"
    views = rows["views"]
    if views["before"] is not None:
        assert views["unchanged"] is False and views["after"]["high"] > views["after"]["low"]
    # ADR-122 d.10: a title drives Lượt xem + CTR on Thẻ sản phẩm; CTOR / AOV stay
    assert rows["ctr"]["unchanged"] is False
    for key in ("ctor", "aov"):
        assert rows[key]["unchanged"] is True and rows[key]["reason"], key
    assert_flat_when_unchanged(rows)
    assert_funnel_holds(v)


async def test_a_price_cut_moves_orders_and_ctor_but_not_views_or_ctr(session, shop):
    v = await one(
        session, shop, kind="product_discount", item_id="1001", variations=[{"discount_pct": 10}]
    )
    if not v.get("ok"):
        import pytest

        pytest.skip(f"discount not buildable here: {v.get('refusal')}")
    ba, rows = rows_of(v)
    assert rows["orders"]["unchanged"] is False and rows["ctor"]["unchanged"] is False
    assert rows["orders"]["after"]["p50"] >= rows["orders"]["before"]
    for key in ("views", "ctr"):
        assert rows[key]["unchanged"] is True and "không bịa" in rows[key]["reason"], key
    assert_flat_when_unchanged(rows)
    assert_funnel_holds(v)
