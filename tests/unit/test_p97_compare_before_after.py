"""P97 D85.9: So sánh shows before -> after with its range for seven metrics; a metric the lever
has no modelled effect on says "không đổi" with the reason and carries no lift. SQLite."""

# ruff: noqa: F811
from __future__ import annotations

from tests.unit.test_shopee_builder import one, shop  # noqa: F401, F811

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


async def test_a_voucher_moves_aov_and_leaves_the_funnel_unchanged_with_reasons(session, shop):
    v = await one(
        session, shop, kind="voucher", discount_type="amount", value=10_000, min_spend=100_000
    )
    ba, rows = rows_of(v)
    assert [r["key"] for r in ba["rows"]] == KEYS
    assert [r["label"] for r in ba["rows"]][:2] == ["GMV", "Biên lợi nhuận"]
    gmv, aov = rows["gmv"], rows["aov"]
    assert gmv["before"] and gmv["after"]["low"] <= gmv["after"]["p50"] <= gmv["after"]["high"]
    assert aov["unchanged"] is False and aov["after"]["p50"] > aov["before"]
    assert aov["after"]["low"] <= aov["after"]["p50"] <= aov["after"]["high"]
    for key in ("orders", "ctor", "ctr", "views"):
        assert rows[key]["unchanged"] is True, key
        assert "không bịa" in rows[key]["reason"] or "không tăng số đơn" in rows[key]["reason"]
    assert_flat_when_unchanged(rows)


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
    for key in ("ctor", "ctr", "aov"):
        assert rows[key]["unchanged"] is True and rows[key]["reason"], key
    assert_flat_when_unchanged(rows)


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
