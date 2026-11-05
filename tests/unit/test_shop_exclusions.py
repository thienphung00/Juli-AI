"""P92 B-1: listings the shop leaves out -- the rule, the Thông số shop columns, the add / undo
service and API, and what an excluded listing no longer gets (cards, product rows, rankings,
Phân tích flags) while the shop totals keep its sales. SQLite; synthetic shops only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from juli_backend.models.run_changes import ShopRule, ShopRuleVersion
from juli_backend.services import shop_inputs
from juli_backend.services.shop_rules import rules as shop_rules
from juli_backend.services.shopee_analytics import queries
from juli_backend.services.shopee_analytics.rules_view import RuleRow, read_rules
from juli_backend.services.shopee_recommendations import generators as gen
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.builders import make_tenant
from tests.support.shop_inputs import COL, edit_workbook, find_row, seed_catalogue, sheet_rows
from tests.support.shopee_analytics import CUR_END
from tests.support.shopee_reco import AS_OF, rule, seed_reco_shop

SELLER = shop_inputs.Actor("seller", uuid.UUID(int=7))
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


# ================================================================================ the rule


def test_the_two_rule_keys_validate_bool_and_reason():
    assert shop_rules.validate_rule("excluded", "1001", True) == ("1001", True)
    assert shop_rules.validate_rule("exclude_reason", "1001", "qua_tang") == ("1001", "qua_tang")
    for key, value in (("excluded", "yes"), ("excluded", 1), ("exclude_reason", "other")):
        with pytest.raises(shop_rules.RuleValidationError):
            shop_rules.validate_rule(key, "1001", value)
    with pytest.raises(shop_rules.RuleValidationError):  # scoped to an item
        shop_rules.validate_rule("excluded", "", True)


def test_profit_rules_read_the_exclusions_and_default_the_reason():
    rules = read_rules(
        [
            RuleRow("excluded", "1001", True),
            RuleRow("exclude_reason", "1001", "phan_phoi"),
            RuleRow("excluded", "1002", True),  # no reason stored
            RuleRow("excluded", "1003", False),  # undone
            RuleRow("exclude_reason", "1003", "khac"),
        ]
    )
    assert rules.excluded == {"1001": "phan_phoi", "1002": "khac"}


# ========================================================================= the .xlsx path


@pytest.fixture
async def shop(session):
    _, shop = await make_tenant(session)
    await seed_catalogue(session, shop)
    return shop


async def _template(session, shop):
    return (await shop_inputs.build_template(session, shop.id)).content


def _cells(content, **by_sku):
    rows = sheet_rows(content, "SKU")
    edits = {}
    for sku, cells in by_sku.items():
        r = find_row(rows, sku.replace("_", "-"))
        for column, value in cells.items():
            edits[(r, COL[column])] = value
    return {"SKU": edits}


async def test_the_columns_loai_tru_and_ly_do_exclude_a_listing_with_a_diff_and_a_version(
    session, shop
):
    template = await _template(session, shop)
    rows = sheet_rows(template, "SKU")
    assert rows[0][COL["excluded"]].rstrip(" *") == "loại trừ"
    assert rows[0][COL["exclude_reason"]].rstrip(" *") == "lý do"
    edited = edit_workbook(
        template, _cells(template, **{"GL-001": {"excluded": "Có", "exclude_reason": "Quà tặng"}})
    )
    preview = await shop_inputs.preview_import(session, shop.id, edited)
    assert preview.rejections == []
    got = {(d.scope_ref, d.field): (d.old, d.new) for d in preview.diffs}
    assert got == {
        ("1001", "excluded"): (None, True),
        ("1001", "exclude_reason"): (None, "qua_tang"),
    }
    result = await shop_inputs.apply_import(
        session, shop.id, edited, actor=SELLER, reason="Quà tặng kèm", now=T0
    )
    assert result.versions_written == 2 and result.affected.item_ids == ("1001",)
    row = await session.scalar(
        select(ShopRule).where(ShopRule.shop_id == shop.id, ShopRule.rule_key == "excluded")
    )
    assert (row.scope_ref, row.value) == ("1001", True)
    version = await session.scalar(
        select(ShopRuleVersion).where(
            ShopRuleVersion.shop_id == shop.id, ShopRuleVersion.rule_key == "exclude_reason"
        )
    )
    assert (version.value, version.reason, version.set_by) == ("qua_tang", "Quà tặng kèm", "seller")
    # the template now shows it, and an untouched re-upload changes nothing
    again = await _template(session, shop)
    r = find_row(sheet_rows(again, "SKU"), "GL-001")
    assert sheet_rows(again, "SKU")[r][COL["excluded"]] == "Có"
    assert sheet_rows(again, "SKU")[r][COL["exclude_reason"]] == "Quà tặng"
    assert (await shop_inputs.preview_import(session, shop.id, again)).diffs == []


async def test_a_file_can_undo_an_exclusion_old_to_new(session, shop):
    template = await _template(session, shop)
    on = edit_workbook(
        template, _cells(template, **{"GL-001": {"excluded": "Có", "exclude_reason": "Khác"}})
    )
    await shop_inputs.apply_import(session, shop.id, on, actor=SELLER, reason="x", now=T0)
    template2 = await _template(session, shop)
    off = edit_workbook(template2, _cells(template2, **{"GL-001": {"excluded": "Không"}}))
    preview = await shop_inputs.preview_import(session, shop.id, off)
    assert [(d.field, d.old, d.new) for d in preview.diffs] == [("excluded", True, False)]


async def test_exclusion_rows_are_checked_one_answer_per_listing_and_a_reason_when_yes(
    session, shop
):
    template = await _template(session, shop)
    # no reason
    no_reason = edit_workbook(template, _cells(template, **{"GL-001": {"excluded": "Có"}}))
    p1 = await shop_inputs.preview_import(session, shop.id, no_reason)
    assert [r.kind for r in p1.rejections] == ["invalid_value"] and p1.diffs == []
    assert "lý do" in p1.rejections[0].reason.lower() and p1.rejections[0].column == "lý do"
    # two variations of one listing disagree
    split = edit_workbook(
        template,
        _cells(
            template,
            **{
                "BEP-S5-CB": {"excluded": "Có", "exclude_reason": "Khác"},
                "BEP-S5-L": {"excluded": "Không"},
            },
        ),
    )
    p2 = await shop_inputs.preview_import(session, shop.id, split)
    assert [r.sku for r in p2.rejections] == ["BEP-S5-L"]
    assert {d.scope_ref for d in p2.diffs} == {"2001"}  # the listing is excluded once
    # unreadable words
    bad = edit_workbook(
        template, _cells(template, **{"GL-001": {"excluded": "có lẽ", "exclude_reason": "Hết"}})
    )
    p3 = await shop_inputs.preview_import(session, shop.id, bad)
    assert len(p3.rejections) == 2 and {r.kind for r in p3.rejections} == {"invalid_value"}


async def test_a_listing_excluded_in_every_variation_row_is_one_change(session, shop):
    template = await _template(session, shop)
    both = edit_workbook(
        template,
        _cells(
            template,
            **{
                "BEP-S5-CB": {"excluded": "Có", "exclude_reason": "Ngừng bán"},
                "BEP-S5-L": {"excluded": "Có", "exclude_reason": "Ngừng bán"},
            },
        ),
    )
    preview = await shop_inputs.preview_import(session, shop.id, both)
    assert preview.rejections == []
    assert sorted((d.scope_ref, d.field) for d in preview.diffs) == [
        ("2001", "exclude_reason"),
        ("2001", "excluded"),
    ]


# =================================================================== the add / undo service


async def test_add_list_and_undo_are_versioned_and_idempotent(session, shop):
    out = await shop_inputs.add_exclusion(
        session, shop.id, "1001", "ngung_ban", actor=SELLER, note="Hết hàng vĩnh viễn", now=T0
    )
    assert (out.item_id, out.reason, out.reason_label, out.name) == (
        "1001",
        "ngung_ban",
        "Ngừng bán",
        "Găng tay cao su",
    )
    assert out.note == "Hết hàng vĩnh viễn" and out.set_by == "seller"
    again = await shop_inputs.add_exclusion(session, shop.id, "1001", "ngung_ban", actor=SELLER)
    assert again.reason == "ngung_ban"
    versions = (
        await session.scalars(select(ShopRuleVersion).where(ShopRuleVersion.rule_key == "excluded"))
    ).all()
    assert len(versions) == 1  # the same answer writes nothing new
    assert [e.item_id for e in await shop_inputs.list_exclusions(session, shop.id)] == ["1001"]
    assert await shop_inputs.undo_exclusion(session, shop.id, "1001", actor=SELLER, now=T0)
    assert await shop_inputs.list_exclusions(session, shop.id) == []
    history = (
        await session.scalars(
            select(ShopRuleVersion)
            .where(ShopRuleVersion.rule_key == "excluded")
            .order_by(ShopRuleVersion.version)
        )
    ).all()
    assert [(v.value, v.version) for v in history] == [(True, 1), (False, 2)]
    assert history[1].reason == "Bỏ loại trừ sản phẩm"
    assert not await shop_inputs.undo_exclusion(session, shop.id, "1001", actor=SELLER)


async def test_add_refuses_a_bad_reason_or_item(session, shop):
    with pytest.raises(shop_inputs.ExclusionError) as reason:
        await shop_inputs.add_exclusion(session, shop.id, "1001", "chan", actor=SELLER)
    with pytest.raises(shop_inputs.ExclusionError) as item:
        await shop_inputs.add_exclusion(session, shop.id, "1001:a", "khac", actor=SELLER)
    assert (
        reason.value.code == "exclusion_reason_invalid"
        and item.value.code == "exclusion_item_invalid"
    )


# ===================================================================== what exclusion changes


@pytest.fixture
async def reco(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


async def _exclude(session, seeded, item="1001", reason="qua_tang"):
    session.add(rule(seeded.shop_id, "excluded", item, True))
    session.add(rule(seeded.shop_id, "exclude_reason", item, reason))
    await session.commit()


async def test_product_rows_rankings_and_flags_drop_it_but_the_shop_totals_keep_its_sales(
    session, reco
):
    kw = {"period": "7d", "as_of": CUR_END}
    before_matrix = await queries.matrix(session, reco.shop_id, **kw)
    before_overview = await queries.overview(session, reco.shop_id, **kw)
    before_ranking = await queries.ranking(session, reco.shop_id, kind="products", **kw)
    flagged = await queries.critical(session, reco.shop_id, **kw)
    assert "product:1001:ctr:median" in {it["id"] for it in flagged["in_band"]}
    assert "1001" in {p["product_id"] for p in before_matrix["products"]}
    gmv_1001 = next(p["gmv"] for p in before_matrix["products"] if p["product_id"] == "1001")
    await _exclude(session, reco)

    matrix = await queries.matrix(session, reco.shop_id, **kw)
    assert "1001" not in {p["product_id"] for p in matrix["products"]}
    assert matrix["product_count"] == before_matrix["product_count"] - 1
    assert matrix["excluded"]["count"] == 1 and matrix["excluded"]["gmv"] == gmv_1001
    assert matrix["excluded"]["items"][0]["reason"] == "qua_tang"
    overview = await queries.overview(session, reco.shop_id, **kw)
    # the shop totals are the same, with the line "trong đó Xđ từ sản phẩm đã loại trừ"
    assert overview["gmv"]["shopee_gmv"] == before_overview["gmv"]["shopee_gmv"]
    assert overview["gmv"]["line_gmv"] == before_overview["gmv"]["line_gmv"]
    assert overview["profit"]["profit_vnd"] == before_overview["profit"]["profit_vnd"]
    assert overview["gmv"]["excluded_gmv"]["gmv"] == gmv_1001
    assert overview["gmv"]["excluded_gmv"]["count"] == 1
    ranking = await queries.ranking(session, reco.shop_id, kind="products", **kw)
    assert (before_ranking["row_count"], ranking["row_count"]) == (3, 2)
    assert ranking["closing"]["few"]["count"] == 2  # only the two listings left are ranked
    critical = await queries.critical(session, reco.shop_id, **kw)
    ids = {it["id"] for it in [*critical["items"], *critical["in_band"]]}
    assert not any(i.startswith("product:1001:") for i in ids)
    # the shop-level items stay; the product median needs three listings and now has two
    assert "shop:gmv:target" in ids


async def test_an_excluded_listing_gets_no_card_and_is_nobodys_partner(session, reco):
    from datetime import datetime

    env = await load_env(session, reco.shop_id, as_of=AS_OF)
    crit = {
        "items": [
            {
                "id": "product:1001:ctor",
                "kind": "below_shop_median",
                "kpi": "ctor",
                "level": "product",
                "product_id": "1001",
                "deviation_pct": -25.0,
                "at_stake_per_day": 1000,
                "at_stake_per_month": 30000,
                "money_basis": "confirmed",
                "cause": {"stage": "ctor", "text": ""},
                "change_kinds": ["product_discount", "min_spend_voucher"],
            }
        ]
    }
    assert any("1001" in c.items for c in gen.generate(env, crit))
    assert "1001" in env.item_ids()
    await _exclude(session, reco)
    env = await load_env(session, reco.shop_id, as_of=AS_OF, now=datetime(2026, 10, 8))
    assert env.excluded == {"1001": "qua_tang"}
    assert "1001" not in env.item_ids() and "1001" not in env.listing_item_ids()
    cands = gen.generate(env, crit)
    assert not any("1001" in c.items for c in cands)
    assert not any(
        c.extra.get("addon_item") == "1001" or c.extra.get("gift_item") == "1001" for c in cands
    )
