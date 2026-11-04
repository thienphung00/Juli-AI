"""P90 step 4: the seller-input template, import, versions and the cost fallback.

Service level, against SQLite; the route tests are ``test_shop_inputs_routes.py`` and the
Postgres proof (RLS, append-only) is ``tests/integration/test_shop_inputs_db.py``.
Synthetic shops only.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from juli_backend.models.models import ActionCard
from juli_backend.models.run_changes import ShopRule, ShopRuleVersion
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services import shop_inputs, shop_rules
from juli_backend.services.shop_inputs import importer, xlsx_io
from juli_backend.services.shop_rules import economics
from tests.support.builders import make_tenant
from tests.support.shop_inputs import COL, edit_workbook, find_row, seed_catalogue, sheet_rows

SELLER = shop_inputs.Actor("seller", uuid.UUID(int=7))
TEAM = shop_inputs.Actor("team", uuid.UUID(int=8))
T0 = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)


async def _versions(session, shop, rule_key=None, scope_ref=None):
    stmt = select(ShopRuleVersion).where(ShopRuleVersion.shop_id == shop.id)
    if rule_key:
        stmt = stmt.where(ShopRuleVersion.rule_key == rule_key)
    if scope_ref is not None:
        stmt = stmt.where(ShopRuleVersion.scope_ref == scope_ref)
    return (await session.scalars(stmt.order_by(ShopRuleVersion.version))).all()


async def _template(session, shop):
    return (await shop_inputs.build_template(session, shop.id)).content


async def _preview(session, shop, content):
    return await shop_inputs.preview_import(session, shop.id, content)


@pytest.fixture
async def shop(session):
    _, shop = await make_tenant(session)
    await seed_catalogue(session, shop)
    return shop


# =========================================================================== xlsx + parsing


def test_the_workbook_writer_and_reader_round_trip_text_numbers_and_blanks():
    data = xlsx_io.write_workbook(
        [
            xlsx_io.SheetSpec(
                "SKU",
                [["a", ("b", xlsx_io.STYLE_HEADER)], [1, 2.5, None, "Đ & <x>"], []],
                protect=True,
            ),
            xlsx_io.SheetSpec("Mục tiêu", [["T12/2026", 100]]),
        ]
    )
    sheets = xlsx_io.read_workbook(data)
    assert list(sheets) == ["SKU", "Mục tiêu"]
    assert sheets["SKU"][0] == ["a", "b"]
    assert sheets["SKU"][1] == ["1", "2.5", None, "Đ & <x>"]
    assert sheets["Mục tiêu"] == [["T12/2026", "100"]]


def test_the_reader_refuses_what_is_not_a_workbook_or_is_too_large():
    with pytest.raises(xlsx_io.WorkbookUnreadable):
        xlsx_io.read_workbook(b"not a zip")
    with pytest.raises(xlsx_io.WorkbookUnreadable):
        xlsx_io.read_workbook(b"0" * (xlsx_io.MAX_FILE_BYTES + 1))


def test_the_reader_refuses_a_workbook_part_that_declares_entities():
    data = xlsx_io.write_workbook([xlsx_io.SheetSpec("SKU", [["a"]])])
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><sst>&b;</sst>'
    )
    src, out = io.BytesIO(data), io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for name in zin.namelist():
            zout.writestr(name, zin.read(name))
        zout.writestr("xl/sharedStrings.xml", bomb)
    with pytest.raises(xlsx_io.WorkbookUnreadable):
        xlsx_io.read_workbook(out.getvalue())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("104.000đ", 104000),
        ("104000", 104000),
        ("12,5", Decimal("12.5")),
        ("12.5", Decimal("12.5")),
        ("1.234.567", 1234567),
        ("1.234,5", Decimal("1234.5")),
        ("1,234.5", Decimal("1234.5")),
        ("1E5", 100000),
        (" 7% ", 7),
    ],
)
def test_numbers_are_read_the_way_a_vietnamese_sheet_writes_them(text, expected):
    assert importer.parse_number(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "1.2.3a", "NaN", "--1"])
def test_unreadable_numbers_are_refused(text):
    with pytest.raises(ValueError):
        importer.parse_number(text)


def test_dates_and_months_accept_the_forms_a_seller_types():
    assert importer.parse_date("10/11/2026").isoformat() == "2026-11-10"
    assert importer.parse_date("2026-11-10").isoformat() == "2026-11-10"
    assert importer.parse_date("46336").isoformat() == "2026-11-10"  # Excel serial
    for bad in ("31/02/2026", "10/11", "tuần sau", "2026-13-01"):
        with pytest.raises(ValueError):
            importer.parse_date(bad)
    assert importer.parse_month("T12/2026") == "2026-12"
    assert importer.parse_month("1/2027") == "2027-01"
    assert importer.parse_month("2026-12") == "2026-12"
    for bad in ("T13/2026", "12", "Tháng 12"):
        with pytest.raises(ValueError):
            importer.parse_month(bad)


def test_the_new_rule_keys_validate_their_values_and_scopes():
    ok = shop_rules.validate_rule
    assert ok("packaging_cost", "1001", "3000") == ("1001", 3000)
    assert ok("stock", "1001:7", 40) == ("1001:7", 40)
    assert ok("restock_date", "1001", "2026-11-10") == ("1001", "2026-11-10")
    assert ok("product_group", "1001", "phan_phoi") == ("1001", "phan_phoi")
    assert ok("item_status", "1001", "xa_hang") == ("1001", "xa_hang")
    assert ok("monthly_margin_target", "2026-12", "12") == ("2026-12", 12)
    bad = [
        ("packaging_cost", "1001", -1),
        ("stock", "1001", 1.5),
        ("stock", "1001", -1),
        ("restock_date", "1001", "10/11/2026"),
        ("restock_date", "1001", "2026-02-31"),
        ("product_group", "1001", "khac"),
        ("item_status", "1001", "het_hang"),
        ("monthly_gmv_target", "T12/2026", 1),
        ("monthly_gmv_target", "", 1),
        ("monthly_margin_target", "2026-12", 100),
        ("monthly_orders_target", "2026-12", 10.5),
    ]
    for key, scope, value in bad:
        with pytest.raises(shop_rules.RuleValidationError):
            ok(key, scope, value)


# =========================================================================== versions


async def test_a_write_appends_a_version_and_updates_the_projection_together(session, shop):
    rows = await shop_inputs.write_versions(
        session,
        shop.id,
        [
            shop_inputs.RuleChange("sku_cost", "1001", 36000),
            shop_inputs.RuleChange("packaging_cost", "1001", 2500),
        ],
        actor=SELLER,
        reason="Nhập lần đầu",
        import_file_hash="a" * 64,
        now=T0,
    )
    await session.commit()
    assert len(rows) == 2
    versions = await _versions(session, shop)
    assert {(v.rule_key, v.version) for v in versions} == {("sku_cost", 1), ("packaging_cost", 1)}
    for v in versions:
        assert (v.set_by, v.set_by_user_id) == ("seller", SELLER.user_id)
        assert (v.reason, v.import_file_hash) == ("Nhập lần đầu", "a" * 64)
        assert v.valid_from == T0.replace(tzinfo=None)
    rules = await shop_rules.get_rules(session, shop.id)
    assert rules.sku_cost["1001"].value == 36000 and rules.sku_cost["1001"].set_by == "seller"


async def test_the_projection_always_equals_the_latest_version(session, shop):
    for i, value in enumerate((36000, 38000, 36000, 41000), start=1):
        await shop_inputs.write_versions(
            session,
            shop.id,
            [shop_inputs.RuleChange("sku_cost", "1001", value)],
            actor=TEAM if i % 2 else SELLER,
            reason=f"lần {i}",
            now=T0.replace(minute=i),
        )
    await session.commit()
    latest = (await _versions(session, shop, "sku_cost", "1001"))[-1]
    projection = (
        await session.scalars(select(ShopRule).where(ShopRule.rule_key == "sku_cost"))
    ).one()
    assert latest.version == 4 and projection.value == latest.value == 41000
    assert projection.set_by == latest.set_by == "seller"
    assert [v.version for v in await _versions(session, shop, "sku_cost")] == [1, 2, 3, 4]


async def test_an_unchanged_value_appends_nothing_and_a_reason_is_required(session, shop):
    change = shop_inputs.RuleChange("sku_cost", "1001", 36000)
    await shop_inputs.write_versions(session, shop.id, [change], actor=SELLER, reason="a", now=T0)
    again = await shop_inputs.write_versions(
        session, shop.id, [change], actor=SELLER, reason="b", now=T0
    )
    assert again == []
    assert len(await _versions(session, shop)) == 1
    with pytest.raises(shop_inputs.VersionError):
        await shop_inputs.write_versions(
            session,
            shop.id,
            [shop_inputs.RuleChange("sku_cost", "1001", 1)],
            actor=SELLER,
            reason="  ",
        )
    with pytest.raises(shop_inputs.VersionError):
        await shop_inputs.write_versions(session, shop.id, [change], actor=SELLER, reason="x" * 501)
    with pytest.raises(shop_rules.RuleValidationError):
        await shop_inputs.write_versions(
            session,
            shop.id,
            [shop_inputs.RuleChange("sku_cost", "1001", -5)],
            actor=SELLER,
            reason="x",
        )
    assert len(await _versions(session, shop)) == 1


async def test_restore_creates_a_new_version_copying_the_old_value(session, shop):
    for i, value in enumerate((95000, 98000, 100000), start=1):
        await shop_inputs.write_versions(
            session,
            shop.id,
            [shop_inputs.RuleChange("sku_cost", "2001:2001-a", value)],
            actor=SELLER,
            reason=f"v{i}",
            now=T0.replace(minute=i),
        )
    restored = await shop_inputs.restore_version(
        session,
        shop.id,
        rule_key="sku_cost",
        scope_ref="2001:2001-a",
        version=1,
        actor=TEAM,
        now=T0.replace(minute=9),
    )
    await session.commit()
    assert (restored.version, restored.value, restored.set_by) == (4, 95000, "team")
    assert restored.reason == "Khôi phục từ v1"
    versions = await _versions(session, shop, "sku_cost")
    assert [v.value for v in versions] == [95000, 98000, 100000, 95000]  # nothing rewritten
    listed = await shop_inputs.list_versions(
        session, shop.id, rule_key="sku_cost", scope_ref="2001:2001-a"
    )
    assert [(e.version, e.current) for e in listed] == [
        (4, True),
        (3, False),
        (2, False),
        (1, False),
    ]
    assert (await shop_rules.get_rules(session, shop.id)).sku_cost["2001:2001-a"].value == 95000
    with pytest.raises(shop_inputs.VersionError):  # v4 is now current
        await shop_inputs.restore_version(
            session, shop.id, rule_key="sku_cost", scope_ref="2001:2001-a", version=4, actor=TEAM
        )
    with pytest.raises(shop_inputs.VersionNotFound):
        await shop_inputs.restore_version(
            session, shop.id, rule_key="sku_cost", scope_ref="2001:2001-a", version=9, actor=TEAM
        )


async def test_a_sku_restore_puts_every_field_back_as_one_new_change_set(session, shop):
    scope = "2001:2001-a"
    await shop_inputs.write_versions(
        session,
        shop.id,
        [
            shop_inputs.RuleChange("sku_cost", scope, 95000),
            shop_inputs.RuleChange("stock", scope, 240),
        ],
        actor=SELLER,
        reason="Nhập lần đầu",
        now=T0.replace(minute=1),
    )
    await shop_inputs.write_versions(
        session,
        shop.id,
        [
            shop_inputs.RuleChange("sku_cost", scope, 104000),
            shop_inputs.RuleChange("stock", scope, 260),
            shop_inputs.RuleChange("packaging_cost", scope, 3000),
        ],
        actor=SELLER,
        reason="Giá nhập tháng 11",
        now=T0.replace(minute=2),
    )
    history = await shop_inputs.sku_history(session, shop.id, scope)
    assert [(c.id, c.reason, c.current) for c in history] == [
        ("v1", "Nhập lần đầu", False),
        ("v2", "Giá nhập tháng 11", True),
    ]
    assert history[0].state == {"sku_cost": 95000, "stock": 240}
    assert history[1].state == {"sku_cost": 104000, "stock": 260, "packaging_cost": 3000}
    written = await shop_inputs.restore_sku_version(
        session, shop.id, scope_ref=scope, number=1, actor=TEAM, now=T0.replace(minute=5)
    )
    await session.commit()
    assert {w.rule_key for w in written} == {"sku_cost", "stock"}  # packaging had no v1 value
    history = await shop_inputs.sku_history(session, shop.id, scope)
    assert [c.id for c in history] == ["v1", "v2", "v3"]
    assert history[2].reason == "Khôi phục từ v1" and history[2].current
    assert history[2].state == {"sku_cost": 95000, "stock": 240, "packaging_cost": 3000}
    with pytest.raises(shop_inputs.VersionError):
        await shop_inputs.restore_sku_version(
            session, shop.id, scope_ref=scope, number=3, actor=TEAM
        )
    with pytest.raises(shop_inputs.VersionNotFound):
        await shop_inputs.restore_sku_version(
            session, shop.id, scope_ref=scope, number=8, actor=TEAM
        )


async def test_one_shop_never_sees_or_writes_another_shops_versions(session, shop):
    _, other = await make_tenant(session)
    await shop_inputs.write_versions(
        session, shop.id, [shop_inputs.RuleChange("sku_cost", "1001", 1)], actor=SELLER, reason="a"
    )
    assert await shop_inputs.list_versions(session, other.id) == []
    assert await shop_inputs.sku_history(session, other.id, "1001") == []
    with pytest.raises(shop_inputs.VersionNotFound):
        await shop_inputs.restore_sku_version(
            session, other.id, scope_ref="1001", number=1, actor=TEAM
        )


# =========================================================================== template


async def test_the_template_is_prefilled_one_row_per_sku(session, shop):
    await shop_inputs.write_versions(
        session,
        shop.id,
        [
            shop_inputs.RuleChange("sku_cost", "1001", 36000),
            shop_inputs.RuleChange("packaging_cost", "1001", 2500),
            shop_inputs.RuleChange("max_discount_pct", "1001", 12.5),
            shop_inputs.RuleChange("restock_date", "1001", "2026-11-10"),
            shop_inputs.RuleChange("product_group", "1001", "thuong_hieu"),
            shop_inputs.RuleChange("item_status", "1001", "ban"),
            shop_inputs.RuleChange("monthly_gmv_target", "2026-12", 320000000),
            shop_inputs.RuleChange("monthly_margin_target", "2026-12", 12),
        ],
        actor=SELLER,
        reason="seed",
    )
    await session.commit()
    result = await shop_inputs.build_template(session, shop.id)
    assert (result.sku_rows, result.item_count, result.prefilled_cost, result.goal_rows) == (
        5,
        4,
        1,
        1,
    )
    sheets = xlsx_io.read_workbook(result.content)
    assert list(sheets) == ["SKU", "Mục tiêu"]
    sku = sheets["SKU"]
    assert [h.rstrip(" *") for h in sku[0]] == [
        "item_id", "variation_id", "SKU", "tên", "giá niêm yết", "giá vốn", "đóng gói",
        "giảm tối đa (%)", "tồn kho", "ngày nhập lại", "nhóm", "trạng thái",
    ]  # fmt: skip
    row = sku[find_row(sku, "GL-001")]
    assert row[COL["item_id"]] == "1001" and row[COL["variation_id"]] in (None, "")
    assert row[COL["list_price"]] == "74000"
    assert (row[COL["cost"]], row[COL["packaging"]], row[COL["max_discount"]]) == (
        "36000",
        "2500",
        "12.5",
    )
    assert (row[COL["restock"]], row[COL["group"]], row[COL["status"]]) == (
        "10/11/2026", "Thương hiệu", "Đang bán",
    )  # fmt: skip
    assert row[COL["stock"]] == "120"  # the platform's stock until the seller sets one
    variation = sku[find_row(sku, "BEP-S5-L")]
    assert (variation[0], variation[1], variation[4]) == ("2001", "2001-b", "185000")
    assert variation[COL["cost"]] is None
    goals = sheets["Mục tiêu"]
    assert [c for c in goals[0]][:2] == ["tháng", "GMV"]
    assert goals[1][:2] == ["T12/2026", "320000000"] and goals[1][4] == "12"


async def test_an_empty_shop_gets_a_template_with_headers_only(session):
    _, empty = await make_tenant(session)
    result = await shop_inputs.build_template(session, empty.id)
    assert (result.sku_rows, result.item_count) == (0, 0)
    assert len(xlsx_io.read_workbook(result.content)["SKU"][0]) == 12


async def test_an_item_with_variations_has_a_row_per_variation_not_one_for_the_item(session, shop):
    catalogue = await shop_inputs.load_catalogue(session, shop.id)
    assert [(s.item_id, s.variation_id) for s in catalogue] == [
        ("1001", ""), ("1002", ""), ("2001", "2001-a"), ("2001", "2001-b"), ("2002", ""),
    ]  # fmt: skip
    assert [s.scope for s in catalogue] == ["1001", "1002", "2001:2001-a", "2001:2001-b", "2002"]


# =========================================================================== import


async def test_the_unedited_template_changes_nothing(session, shop):
    preview = await _preview(session, shop, await _template(session, shop))
    assert (preview.sku_rows, preview.sku_rows_rejected, preview.rejections) == (5, 0, [])
    assert preview.diffs == [] and preview.changes == []
    with pytest.raises(importer.NothingToApply):
        await shop_inputs.apply_import(
            session, shop.id, await _template(session, shop), actor=SELLER, reason="x"
        )


def _edits(content, **by_sku):
    """Cell edits for the SKU sheet: ``_edits(content, **{"GL-001": {"cost": "36000"}})``."""
    rows = sheet_rows(content, "SKU")
    edits = {}
    for sku, cells in by_sku.items():
        r = find_row(rows, sku.replace("_", "-"))
        for column, value in cells.items():
            edits[(r, COL[column])] = value
    return {"SKU": edits}


async def test_the_four_rejection_cases_of_the_artboard_and_the_rest(session, shop):
    template = await _template(session, shop)
    rows = sheet_rows(template, "SKU")
    # an unknown SKU is a new row
    extra = len(rows) + 1  # leave the note rows alone: append after them
    edits = _edits(
        template,
        **{
            "GL-001": {"cost": "74.000"},  # cost >= list price 74.000
            "NR-002": {"packaging": "3000"},  # other value, no cost, no old cost
            "BEP-S5-CB": {"cost": "100000", "max_discount": "140"},
            "BEP-S3": {"cost": "72000", "restock": "ngày mai"},
        },
    )
    edits["SKU"].update(
        {
            (extra, 0): "9999",
            (extra, 1): None,
            (extra, 2): "BEP-S5-XX",
            (extra, 5): "50000",
        }
    )
    preview = await _preview(session, shop, edit_workbook(template, edits))
    by_sku = {(r.sku, r.kind): r for r in preview.rejections}
    assert set(by_sku) == {
        ("GL-001", "cost_ge_price"),
        ("NR-002", "cost_missing"),
        ("BEP-S5-CB", "out_of_range"),
        ("BEP-S3", "bad_date"),
        ("BEP-S5-XX", "unknown_sku"),
    }
    assert by_sku[("GL-001", "cost_ge_price")].column == "giá vốn"
    assert "74.000đ" in by_sku[("GL-001", "cost_ge_price")].reason
    assert by_sku[("NR-002", "cost_missing")].value == "(trống)"
    assert by_sku[("BEP-S5-CB", "out_of_range")].column == "giảm tối đa (%)"
    assert by_sku[("BEP-S5-CB", "out_of_range")].value == "140"
    assert by_sku[("BEP-S5-XX", "unknown_sku")].row == extra + 1
    assert preview.sku_rows_rejected == 5
    # a rejected row keeps its old values: nothing of it is in the diff
    assert preview.diffs == [] and preview.changes == []
    assert {r.kind_label for r in preview.rejections} >= {
        "SKU lạ",
        "Giá vốn ≥ giá",
        "Giá vốn trống",
    }


async def test_a_sku_that_appears_twice_is_rejected_on_both_rows(session, shop):
    template = await _template(session, shop)
    rows = sheet_rows(template, "SKU")
    r = find_row(rows, "GL-001")
    dup = len(rows)
    edits = {
        "SKU": {
            (r, COL["cost"]): "36000",
            (dup, 0): "1001",
            (dup, 2): "GL-001",
            (dup, 5): "37000",
        }
    }
    preview = await _preview(session, shop, edit_workbook(template, edits))
    dups = [x for x in preview.rejections if x.kind == "duplicate_sku"]
    assert sorted(x.row for x in dups) == [r + 1, dup + 1]
    assert preview.changes == []


async def test_a_sku_text_that_does_not_match_the_product_is_rejected(session, shop):
    template = await _template(session, shop)
    rows = sheet_rows(template, "SKU")
    r = find_row(rows, "GL-001")
    edits = {"SKU": {(r, COL["sku"]): "GL-999", (r, COL["cost"]): "36000"}}
    preview = await _preview(session, shop, edit_workbook(template, edits))
    assert [x.kind for x in preview.rejections] == ["unknown_sku"]
    assert "GL-001" in preview.rejections[0].reason


async def test_round_trip_edit_and_import_a_synthetic_shop(session, shop):
    """Template -> edit -> preview diff -> apply -> the next template carries the values."""
    template = await _template(session, shop)
    edits = _edits(
        template,
        **{
            "GL-001": {"cost": "36.000đ", "packaging": 2500, "stock": 90, "group": "Thương hiệu"},
            "BEP-S5-CB": {"cost": 104000, "max_discount": "12,5", "status": "Xả hàng"},
            "NR-002": {"cost": 50000, "stock": 40, "restock": "10/11/2026"},
        },
    )
    edits["Mục tiêu"] = {
        (1, 0): "T12/2026",
        (1, 1): "320.000.000",
        (1, 2): 3600,
        (1, 3): 88900,
        (1, 4): "12",
        (1, 5): 1500000,
    }
    content = edit_workbook(template, edits)
    preview = await _preview(session, shop, content)
    assert preview.rejections == [] and preview.sku_rows_unchanged == 2
    diff = {(d.sku, d.field): (d.old, d.new) for d in preview.diffs}
    assert diff[("GL-001", "cost")] == (None, 36000)
    assert diff[("GL-001", "stock")] == (120, 90)  # old = the platform's stock
    assert diff[("BEP-S5-CB", "max_discount")] == (None, 12.5)
    assert diff[("BEP-S5-CB", "status")] == (None, "xa_hang")
    assert diff[("NR-002", "stock")] == (0, 40)
    assert diff[("NR-002", "restock")] == (None, "2026-11-10")
    assert ("BEP-S5-L", "cost") not in diff
    assert len(preview.diffs) == 10 and len(preview.goal_diffs) == 5
    assert preview.changed_scopes == ["1001", "1002", "2001:2001-a"]
    assert preview.changed_months == ["2026-12"]
    effects = {(d.sku, d.field): d.effect for d in preview.diffs}
    assert "Tính được biên gộp" in effects[("GL-001", "cost")]
    assert effects[("NR-002", "stock")] == "Hết hàng → còn hàng"

    # nothing was written by the preview
    assert await _versions(session, shop) == []

    result = await shop_inputs.apply_import(
        session, shop.id, content, actor=SELLER, reason="Giá nhập tháng 11", now=T0
    )
    await session.commit()
    assert (result.versions_written, result.skus_changed, result.months_changed) == (15, 3, 1)
    rules = await shop_rules.get_rules(session, shop.id)
    assert rules.sku_cost["1001"].value == 36000
    assert rules.sku_cost["2001:2001-a"].value == 104000
    assert rules.max_discount_pct["2001:2001-a"].value == 12.5
    versions = await _versions(session, shop)
    assert {v.import_file_hash for v in versions} == {preview.file_hash}
    assert {v.reason for v in versions} == {"Giá nhập tháng 11"}
    assert {v.valid_from for v in versions} == {T0.replace(tzinfo=None)}

    # the next template is pre-filled with what was imported, and re-importing it is a no-op
    again = await _template(session, shop)
    sku = sheet_rows(again, "SKU")
    assert sku[find_row(sku, "GL-001")][COL["cost"]] == "36000"
    assert sku[find_row(sku, "GL-001")][COL["stock"]] == "90"
    assert sku[find_row(sku, "BEP-S5-CB")][COL["status"]] == "Xả hàng"
    assert sheet_rows(again, "Mục tiêu")[1][:5] == ["T12/2026", "320000000", "3600", "88900", "12"]
    assert (await _preview(session, shop, again)).changes == []


async def test_apply_writes_valid_rows_only_and_needs_a_reason(session, shop):
    template = await _template(session, shop)
    content = edit_workbook(
        template,
        _edits(
            template,
            **{
                "GL-001": {"cost": 36000},
                "BEP-S3": {"cost": 999999},  # >= list price 129.000
            },
        ),
    )
    with pytest.raises(shop_inputs.VersionError):
        await shop_inputs.apply_import(session, shop.id, content, actor=SELLER, reason="  ")
    with pytest.raises(shop_inputs.FileMismatch):
        await shop_inputs.apply_import(
            session, shop.id, content, actor=SELLER, reason="x", expected_hash="0" * 64
        )
    assert await _versions(session, shop) == []
    result = await shop_inputs.apply_import(
        session, shop.id, content, actor=TEAM, reason="Sửa sai nhập liệu"
    )
    await session.commit()
    assert result.versions_written == 1 and len(result.preview.rejections) == 1
    scopes = {(v.scope_ref, v.rule_key) for v in await _versions(session, shop)}
    assert scopes == {("1001", "sku_cost")}
    assert "2002" not in (await shop_rules.get_rules(session, shop.id)).sku_cost


async def test_a_goal_whose_three_numbers_disagree_warns_but_is_saved(session, shop):
    template = await _template(session, shop)
    content = edit_workbook(
        template,
        {"Mục tiêu": {(1, 0): "T01/2027", (1, 1): 200000000, (1, 2): 2500, (1, 3): 130000}},
    )
    preview = await _preview(session, shop, content)
    assert len(preview.warnings) == 1 and preview.warnings[0].month == "2027-01"
    assert "lệch" in preview.warnings[0].message and "Vẫn lưu được" in preview.warnings[0].message
    assert preview.rejections == [] and len(preview.goal_diffs) == 3
    await shop_inputs.apply_import(session, shop.id, content, actor=SELLER, reason="mục tiêu")
    await session.commit()
    assert len(await _versions(session, shop, "monthly_gmv_target", "2027-01")) == 1


async def test_goal_rows_are_checked_individually(session, shop):
    template = await _template(session, shop)
    content = edit_workbook(
        template,
        {
            "Mục tiêu": {
                (1, 0): "Tháng 13", (1, 1): 1,
                (2, 0): "T02/2027", (2, 4): "100",
                (3, 0): "T03/2027", (3, 1): 5, (3, 2): 2.5,
                (4, 0): "T04/2027", (4, 1): 5000000,
                (5, 0): "T04/2027", (5, 1): 6000000,
            }
        },
    )  # fmt: skip
    preview = await _preview(session, shop, content)
    kinds = sorted((r.row, r.kind) for r in preview.rejections)
    assert (
        (2, "bad_month") in kinds and (3, "out_of_range") in kinds and (4, "invalid_value") in kinds
    )
    assert {r.kind for r in preview.rejections if r.row in (5, 6)} == {"duplicate_sku"}
    assert preview.goal_rows == 5 and preview.goal_rows_rejected == 5


async def test_a_file_without_the_sheets_or_columns_is_refused(session, shop):
    for content in (
        b"nope",
        xlsx_io.write_workbook([xlsx_io.SheetSpec("Khác", [["x"]])]),
        xlsx_io.write_workbook([xlsx_io.SheetSpec("SKU", [["item_id", "SKU"]])]),
    ):
        with pytest.raises(importer.ImportFileError):
            await _preview(session, shop, content)


# =========================================================================== recommendations


async def _proposal(session, shop, *, item_id, kind="price", status="draft", subject="item"):
    session.add(
        ShopProposal(
            id=uuid.uuid4(),
            shop_id=shop.id,
            platform="shopee",
            cycle="2026-11",
            kind=kind,
            subject_type=subject,
            item_id=item_id if subject == "item" else None,
            subject_label="x",
            change_after={},
            reason="r",
            status=status,
        )
    )


async def _card(session, shop, *, subject_id, status="active"):
    session.add(
        ActionCard(
            id=uuid.uuid4(),
            shop_id=shop.id,
            workflow_key=f"wf-{uuid.uuid4().hex[:6]}",
            subject_type="product",
            subject_id=subject_id,
            priority=1,
            severity="medium",
            title="t",
            status=status,
        )
    )


async def test_only_open_recommendations_of_the_changed_items_are_counted(session, shop):
    await _proposal(session, shop, item_id="1001")
    await _proposal(session, shop, item_id="1001", kind="title", status="sent")
    await _proposal(session, shop, item_id="1001", status="executed")  # closed
    await _proposal(session, shop, item_id="1002")  # another item
    await _proposal(session, shop, item_id=None, kind="voucher", subject="shop")
    await _card(session, shop, subject_id="1001")
    await _card(session, shop, subject_id="1001", status="dismissed")
    await _card(session, shop, subject_id="2001")
    await session.commit()
    one = await shop_inputs.affected_recommendations(session, shop.id, item_ids=["1001"])
    assert (one.proposals, one.action_cards, one.total) == (2, 1, 3)
    assert one.item_ids == ("1001",) and not one.shop_wide
    # a shop-wide target also re-runs the price / voucher kinds of every item
    wide = await shop_inputs.affected_recommendations(
        session, shop.id, item_ids=["1001"], shop_wide=True
    )
    assert wide.proposals == 4  # 1001 price, 1001 title, 1002 price, shop voucher
    none = await shop_inputs.affected_recommendations(session, shop.id, item_ids=[])
    assert none.total == 0


async def test_apply_counts_the_recommendations_and_calls_the_stale_hook(session, shop):
    await _proposal(session, shop, item_id="1001")
    await _proposal(session, shop, item_id="1002")
    await _card(session, shop, subject_id="1001")
    await session.commit()
    calls = []

    async def hook(sess, shop_id, request):
        calls.append((shop_id, request))

    shop_inputs.register_recompute_hook(hook)
    try:
        template = await _template(session, shop)
        content = edit_workbook(template, _edits(template, **{"GL-001": {"cost": 36000}}))
        preview = await _preview(session, shop, content)
        before = await shop_inputs.preview_affected(session, shop.id, preview)
        assert before.total == 2 and calls == []  # a preview marks nothing
        result = await shop_inputs.apply_import(
            session, shop.id, content, actor=SELLER, reason="Giá nhập tháng 11", now=T0
        )
    finally:
        shop_inputs.unregister_recompute_hook(hook)
    assert (result.affected.proposals, result.affected.action_cards) == (1, 1)
    assert result.affected.item_ids == ("1001",)  # only the changed item: 1002 is untouched
    assert len(calls) == 1 and calls[0][0] == shop.id
    assert calls[0][1].item_ids == ("1001",) and calls[0][1].reason == "seller_inputs_changed"
    assert calls[0][1].import_file_hash == preview.file_hash


async def test_a_target_margin_change_is_shop_wide(session, shop):
    await _proposal(session, shop, item_id="1002", kind="price")
    await _proposal(session, shop, item_id="1002", kind="title")
    await session.commit()
    template = await _template(session, shop)
    content = edit_workbook(template, {"Mục tiêu": {(1, 0): "T12/2026", (1, 4): 12}})
    result = await shop_inputs.apply_import(
        session, shop.id, content, actor=SELLER, reason="mục tiêu"
    )
    assert result.affected.shop_wide and result.affected.proposals == 1  # price, not title


# =========================================================================== the cost fallback


async def test_skus_without_an_imported_cost_are_listed_with_the_one_third_cost(session, shop):
    await shop_inputs.write_versions(
        session,
        shop.id,
        [shop_inputs.RuleChange("sku_cost", "1001", 36000)],
        actor=SELLER,
        reason="seed",
    )
    await shop_rules.set_rule(
        session, shop.id, rule_key="product_cost", scope_ref="1002", value=50000,
        set_by="seller", set_by_user_id=None,
    )  # fmt: skip
    await session.commit()
    fallbacks = await shop_inputs.cost_fallbacks(session, shop.id)
    assert [f.item_id + ":" + f.variation_id for f in fallbacks] == [
        "2001:2001-a", "2001:2001-b", "2002:",
    ]  # fmt: skip
    first = fallbacks[0]
    assert first.source == "assumed_one_third" and first.list_price == Decimal(200000)
    assert first.assumed_cost == Decimal(200000) / 3
    assert round(first.margin_pct, 1) == Decimal("66.7")
    overview = await shop_inputs.build_overview(session, shop.id)
    assert overview["cost_fallback"]["count"] == 3
    assert overview["cost_fallback"]["assumed_share"] == "1/3"
    assert overview["catalogue"] == {"sku_rows": 5, "items": 4, "with_cost": 2}


async def test_a_shop_margin_rule_replaces_the_one_third_default(session, shop):
    await shop_rules.set_rule(
        session, shop.id, rule_key="default_gross_margin_pct", scope_ref=None, value=40,
        set_by="seller", set_by_user_id=None,
    )  # fmt: skip
    await session.commit()
    fallbacks = await shop_inputs.cost_fallbacks(session, shop.id)
    assert len(fallbacks) == 5 and {f.source for f in fallbacks} == {"default_margin_rule"}
    assert fallbacks[0].assumed_cost == Decimal(74000) * Decimal("0.6")


def test_unit_cost_labelled_names_where_the_cost_came_from():
    eco = economics.ShopEconomics(sku_cost={"s1": Decimal(10)}, product_cost={"p1": Decimal(20)})
    price = Decimal(300)
    sku = eco.unit_cost_labelled(sku_id="s1", product_id="p1", unit_price=price)
    prod = eco.unit_cost_labelled(sku_id="s2", product_id="p1", unit_price=price)
    third = eco.unit_cost_labelled(sku_id="s2", product_id="p2", unit_price=price)
    assert (sku.cost, sku.source, sku.assumed) == (10, "sku", False)
    assert (prod.cost, prod.source, prod.assumed) == (20, "product", False)
    assert (third.cost, third.source, third.assumed) == (Decimal(100), "assumed_one_third", True)
    assert eco.unit_cost_labelled(sku_id=None, product_id=None, unit_price=None) is None
    margin = economics.ShopEconomics(default_gross_margin_pct=Decimal(40))
    own = margin.unit_cost_labelled(sku_id=None, product_id=None, unit_price=price)
    assert (own.cost, own.source, own.assumed) == (Decimal(180), "default_margin_rule", True)
    # the plain accessor is unchanged: no cost, no guess
    assert eco.unit_cost(sku_id="s2", product_id="p2", unit_price=price) is None


async def test_the_table_counts_are_what_the_tests_assume(session, shop):
    # guards the fixtures themselves: five SKUs, no rules, no versions
    assert (await session.scalar(select(func.count()).select_from(ShopRuleVersion))) == 0
