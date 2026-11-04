"""P91 D-12: the seller template and import with the pack multiplier, the bill of materials and
the company VAT; the cost fallback of a listing that has a bill of materials.

Service level, against SQLite. A shop whose "Giấy ăn" variations (Combo 3 / Combo 10 / Hộp lẻ)
share one SKU, a combo listing with no SKU of its own, and two single products to build it from.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from juli_backend.services import shop_inputs, shop_rules
from juli_backend.services.shop_inputs import xlsx_io
from tests.support.builders import make_tenant
from tests.support.shop_inputs import COL, edit_workbook, seed_catalogue

SELLER = shop_inputs.Actor("seller", uuid.UUID(int=7))
T0 = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
PACK, VAT = 12, 13
HEADER_ROWS = 1

CATALOGUE = [
    ("500", "5003", "G500001", "Giấy ăn · Combo 3 hộp", 90_000, 100),
    ("500", "5010", "G500001", "Giấy ăn · Combo 10 hộp", 260_000, 100),
    ("500", "5001", "G500001", "Giấy ăn · Hộp lẻ", 30_000, 100),
    ("600", "", "", "Combo quà", 150_000, 10),
    ("700", "", "G700001", "Găng tay", 40_000, 50),
    ("701", "", "N700001", "Nước rửa", 60_000, 50),
]


@pytest.fixture
async def shop(session):
    _, shop = await make_tenant(session)
    await seed_catalogue(session, shop, CATALOGUE)
    return shop


def _c(row, index: int):
    """A cell of a read row (a row loses its trailing blank cells)."""
    return row[index] if len(row) > index else None


def _row(rows, item_id: str, variation_id: str = "") -> int:
    return next(
        i
        for i, row in enumerate(rows)
        if len(row) > 1 and row[0] == item_id and (row[1] or "") == variation_id
    )


async def _template(session, shop) -> bytes:
    return (await shop_inputs.build_template(session, shop.id)).content


def _kinds(preview) -> list[str]:
    return [r.kind for r in preview.rejections]


async def _apply(session, shop, content, reason="nhập thử"):
    result = await shop_inputs.apply_import(
        session, shop.id, content, actor=SELLER, reason=reason, now=T0
    )
    await session.commit()
    return result


# ====================================================================== the template


async def test_the_template_has_the_pack_and_vat_columns_and_the_two_new_sheets(session, shop):
    result = await shop_inputs.build_template(session, shop.id)
    sheets = xlsx_io.read_workbook(result.content)
    assert list(sheets) == ["SKU", "Mục tiêu", "Thành phần combo", "VAT"]
    header = [h.rstrip(" *") for h in sheets["SKU"][0]]
    assert header[PACK] == "số món / phân loại" and header[VAT] == "VAT (%)"
    assert [h for h in sheets["Thành phần combo"][0]] == [
        "item_id",
        "variation_id",
        "tên",
        "SKU thành phần",
        "số lượng",
    ]
    vat = sheets["VAT"]
    assert vat[0] == ["thiết lập", "giá trị"]
    assert [row[0] for row in vat[1:3]] == ["giá bán đã gồm VAT", "giá vốn đã gồm VAT"]
    assert all(_c(row, 1) is None for row in vat[1:3])  # never guessed: empty until the seller says


async def test_the_pack_default_is_read_from_the_variation_name(session, shop):
    result = await shop_inputs.build_template(session, shop.id)
    rows = xlsx_io.read_workbook(result.content)["SKU"]
    packs = {
        (row[0], row[1] or ""): _c(row, PACK)
        for row in rows[1:]
        if len(row) > 2 and row[0] and row[2] is not None
    }
    assert packs[("500", "5003")] == "3" and packs[("500", "5010")] == "10"
    assert packs[("500", "5001")] is None  # "Hộp lẻ": no pack stated, left blank (= 1)
    assert result.pack_rows == 2


async def test_a_stored_pack_beats_the_default_in_the_template(session, shop):
    await shop_inputs.write_versions(
        session,
        shop.id,
        [shop_inputs.RuleChange("pack_count", "500:5003", 4)],
        actor=SELLER,
        reason="x",
        now=T0,
    )
    await session.commit()
    rows = xlsx_io.read_workbook(await _template(session, shop))["SKU"]
    assert _c(rows[_row(rows, "500", "5003")], PACK) == "4"


async def test_an_untouched_template_changes_nothing_and_rejects_nothing(session, shop):
    preview = await shop_inputs.preview_import(session, shop.id, await _template(session, shop))
    assert preview.rejections == [] and preview.changes == []
    assert (preview.bom_rows, preview.sku_rows_rejected) == (0, 0)


# ================================================================= pack and VAT columns


async def _with_cells(session, shop, cells: dict[tuple[str, str], dict[int, object]]):
    content = await _template(session, shop)
    rows = xlsx_io.read_workbook(content)["SKU"]
    edits = {}
    for (item_id, variation_id), by_column in cells.items():
        r = _row(rows, item_id, variation_id)
        for column, value in by_column.items():
            edits[(r, column)] = value
    return edit_workbook(content, {"SKU": edits})


async def test_a_cost_and_a_pack_are_stored_per_variation(session, shop):
    content = await _with_cells(
        session,
        shop,
        {
            ("500", "5003"): {COL["cost"]: "20000"},
            ("500", "5010"): {COL["cost"]: "20000", PACK: "12"},  # the name says 10; the seller 12
            ("500", "5001"): {COL["cost"]: "10000", PACK: "2"},
        },
    )
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert preview.rejections == []
    got = {(d.scope_ref, d.field): (d.old, d.new) for d in preview.diffs}
    assert got[("500:5010", "pack")] == (10, 12) and got[("500:5001", "pack")] == (1, 2)
    assert ("500:5003", "pack") not in got  # the default already in force is not a change
    assert got[("500:5003", "cost")] == (None, 20000)
    result = await _apply(session, shop, content)
    assert result.skus_changed == 3
    current = await shop_inputs.load_current(session, shop.id)
    assert current.per_sku["500:5010"]["pack_count"] == 12
    assert "pack_count" not in current.per_sku["500:5003"]


async def test_typing_one_over_a_default_pack_is_stored_as_the_sellers_choice(session, shop):
    content = await _with_cells(session, shop, {("500", "5003"): {COL["cost"]: "20000", PACK: "1"}})
    preview = await shop_inputs.preview_import(session, shop.id, content)
    pack = next(d for d in preview.diffs if d.field == "pack")
    assert (pack.old, pack.new) == (3, 1)
    assert "×1" in pack.effect


@pytest.mark.parametrize("text", ["2,5", "0", "-1", "101", "abc"])
async def test_a_bad_pack_is_rejected_with_its_kind(session, shop, text):
    content = await _with_cells(
        session, shop, {("500", "5001"): {COL["cost"]: "20000", PACK: text}}
    )
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert _kinds(preview) == ["bad_pack"] and preview.rejections[0].column == "số món / phân loại"
    assert preview.sku_rows_rejected == 1 and preview.changes == []
    assert preview.rejections[0].kind_label == "Số món sai"


async def test_the_cost_of_a_pack_is_checked_against_the_price_of_the_pack(session, shop):
    over = await _with_cells(session, shop, {("500", "5003"): {COL["cost"]: "40000"}})
    preview = await shop_inputs.preview_import(session, shop.id, over)
    assert _kinds(preview) == ["cost_ge_price"] and "3 món" in preview.rejections[0].reason
    fine = await _with_cells(session, shop, {("500", "5003"): {COL["cost"]: "29000"}})
    assert (await shop_inputs.preview_import(session, shop.id, fine)).rejections == []
    # the same cost on the single box (price 30.000) is a loss and says so
    single = await _with_cells(session, shop, {("500", "5001"): {COL["cost"]: "30000"}})
    assert _kinds(await shop_inputs.preview_import(session, shop.id, single)) == ["cost_ge_price"]


@pytest.mark.parametrize("rate", ["0", "5", "8", "10", "8%"])
async def test_a_vat_rate_is_one_of_four(session, shop, rate):
    content = await _with_cells(session, shop, {("700", ""): {COL["cost"]: "10000", VAT: rate}})
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert preview.rejections == []
    new = next(d.new for d in preview.diffs if d.field == "vat")
    assert new == int(rate.rstrip("%"))


@pytest.mark.parametrize("rate", ["7", "8.5", "-5", "mười", "100"])
async def test_any_other_vat_rate_is_rejected(session, shop, rate):
    content = await _with_cells(session, shop, {("700", ""): {COL["cost"]: "10000", VAT: rate}})
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert _kinds(preview) == ["bad_vat"] and preview.rejections[0].column == "VAT (%)"


async def test_pack_vat_and_cost_get_versions_that_can_be_restored(session, shop):
    first = await _with_cells(
        session,
        shop,
        {("500", "5001"): {COL["cost"]: "10000", PACK: "2", VAT: "8"}},
    )
    await _apply(session, shop, first)
    second = await _with_cells(session, shop, {("500", "5001"): {PACK: "1", VAT: "10"}})
    await shop_inputs.apply_import(
        session, shop.id, second, actor=SELLER, reason="đổi", now=T0.replace(minute=5)
    )
    await session.commit()
    history = await shop_inputs.sku_history(session, shop.id, "500:5001")
    assert [s.number for s in history] == [1, 2]
    assert history[0].state["pack_count"] == 2 and history[1].state["vat_rate"] == 10
    await shop_inputs.restore_sku_version(
        session, shop.id, scope_ref="500:5001", number=1, actor=SELLER, now=T0.replace(minute=9)
    )
    current = await shop_inputs.load_current(session, shop.id)
    assert (current.per_sku["500:5001"]["pack_count"], current.per_sku["500:5001"]["vat_rate"]) == (
        2,
        8,
    )


# ============================================================ the Thành phần combo sheet

BOM = "Thành phần combo"


async def _with_bom(session, shop, lines: list[list[object]]):
    content = await _template(session, shop)
    edits = {}
    for offset, line in enumerate(lines):
        for column, value in enumerate(line):
            edits[(1 + offset, column)] = value
    return edit_workbook(content, {BOM: edits})


GOOD = [["600", None, None, "G700001", "2"], ["600", None, None, "N700001", "1"]]


async def test_a_listing_without_a_sku_gets_its_bill_of_materials(session, shop):
    content = await _with_bom(session, shop, GOOD)
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert preview.rejections == [] and preview.bom_rows == 2
    (diff,) = preview.bom_diffs
    assert (diff.field, diff.scope_ref, diff.old) == ("bom", "600", None)
    assert diff.new == [{"sku": "G700001", "qty": 2}, {"sku": "N700001", "qty": 1}]
    result = await _apply(session, shop, content)
    assert result.boms_changed == 1 and result.skus_changed == 1
    current = await shop_inputs.load_current(session, shop.id)
    assert current.per_sku["600"]["pack_components"] == diff.new


async def test_the_same_bill_again_is_no_change_and_the_template_carries_it_back(session, shop):
    content = await _with_bom(session, shop, GOOD)
    await _apply(session, shop, content)
    again = await shop_inputs.preview_import(session, shop.id, content)
    assert again.bom_diffs == [] and again.changes == []
    template = xlsx_io.read_workbook(await _template(session, shop))
    rows = template[BOM]
    assert [r[3] for r in rows[1:3]] == ["G700001", "N700001"]
    assert [r[4] for r in rows[1:3]] == ["2", "1"]
    assert (await shop_inputs.build_template(session, shop.id)).bom_rows == 2


async def test_a_changed_bill_replaces_the_whole_list(session, shop):
    await _apply(session, shop, await _with_bom(session, shop, GOOD))
    # the template carries the stored lines back: overwrite the first, blank the second
    content = await _with_bom(
        session, shop, [["600", None, None, "G700001", "5"], [None, None, None, None, None]]
    )
    preview = await shop_inputs.preview_import(session, shop.id, content)
    (diff,) = preview.bom_diffs
    assert diff.new == [{"sku": "G700001", "qty": 5}]
    assert diff.old == [{"sku": "G700001", "qty": 2}, {"sku": "N700001", "qty": 1}]


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        (["600", None, None, "KHONG-CO", "1"], "unknown_component"),
        (["600", None, None, "", "1"], "unknown_component"),
        (["600", None, None, "G700001", "0"], "bad_quantity"),
        (["600", None, None, "G700001", "1.5"], "bad_quantity"),
        (["600", None, None, "G700001", ""], "bad_quantity"),
        (["600", None, None, "G700001", "1001"], "bad_quantity"),
        (["999", None, None, "G700001", "1"], "unknown_sku"),
        (["500", "5003", None, "G500001", "1"], "bom_self"),
    ],
)
async def test_a_bad_component_line_is_rejected_with_its_kind(session, shop, line, kind):
    preview = await shop_inputs.preview_import(
        session, shop.id, await _with_bom(session, shop, [line])
    )
    assert _kinds(preview) == [kind] and preview.bom_diffs == []
    assert preview.rejections[0].sheet == BOM and preview.bom_rows_rejected == 1


async def test_a_listing_with_one_bad_line_is_applied_whole_or_not_at_all(session, shop):
    lines = [*GOOD, ["600", None, None, "KHONG-CO", "1"], ["700", None, None, "N700001", "3"]]
    preview = await shop_inputs.preview_import(
        session, shop.id, await _with_bom(session, shop, lines)
    )
    assert _kinds(preview) == ["unknown_component"]
    assert preview.bom_rows == 4 and preview.bom_rows_rejected == 3  # the whole of listing 600
    assert [d.scope_ref for d in preview.bom_diffs] == ["700"]  # the other listing is fine


async def test_a_component_listed_twice_is_rejected(session, shop):
    lines = [["600", None, None, "G700001", "1"], ["600", None, None, "g700001", "2"]]
    preview = await shop_inputs.preview_import(
        session, shop.id, await _with_bom(session, shop, lines)
    )
    assert _kinds(preview) == ["duplicate_component"] and preview.bom_diffs == []


async def test_a_bill_of_materials_can_be_restored_from_history(session, shop):
    await _apply(session, shop, await _with_bom(session, shop, GOOD))
    await shop_inputs.apply_import(
        session,
        shop.id,
        await _with_bom(
            session, shop, [["600", None, None, "G700001", "5"], [None, None, None, None, None]]
        ),
        actor=SELLER,
        reason="đổi",
        now=T0.replace(minute=5),
    )
    await shop_inputs.restore_sku_version(
        session, shop.id, scope_ref="600", number=1, actor=SELLER, now=T0.replace(minute=9)
    )
    current = await shop_inputs.load_current(session, shop.id)
    assert current.per_sku["600"]["pack_components"][0]["qty"] == 2


async def test_a_listing_with_a_complete_bill_is_not_on_the_cost_fallback(session, shop):
    before = {f.item_id for f in await shop_inputs.cost_fallbacks(session, shop.id)}
    assert "600" in before
    content = await _with_bom(session, shop, GOOD)
    await _apply(session, shop, content)
    # components still unpriced: the listing stays on the fallback
    assert "600" in {f.item_id for f in await shop_inputs.cost_fallbacks(session, shop.id)}
    priced = await _with_cells(
        session, shop, {("700", ""): {COL["cost"]: "10000"}, ("701", ""): {COL["cost"]: "20000"}}
    )
    await _apply(session, shop, priced)
    after = {f.item_id for f in await shop_inputs.cost_fallbacks(session, shop.id)}
    assert "600" not in after and "700" not in after


# ================================================================== the VAT sheet


async def _with_vat(session, shop, values: dict[int, object]):
    content = await _template(session, shop)
    return edit_workbook(content, {"VAT": {(row, 1): value for row, value in values.items()}})


async def test_the_vat_flags_are_stated_not_guessed(session, shop):
    content = await _with_vat(session, shop, {1: "Có", 2: "Không"})
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert preview.rejections == []
    got = {d.field: (d.old, d.new) for d in preview.shop_diffs}
    assert got == {"prices_include_vat": (None, True), "cost_includes_vat": (None, False)}
    assert shop_inputs.importer.is_shop_wide(preview) is True
    result = await _apply(session, shop, content)
    assert result.flags_changed == 2 and result.skus_changed == 0
    current = await shop_inputs.load_current(session, shop.id)
    assert current.flags == {"prices_include_vat": True, "cost_includes_vat": False}
    flags = {f.rule_key: f.value for f in await shop_inputs.list_versions(session, shop.id)}
    assert flags["prices_include_vat"] is True


async def test_a_flag_left_empty_keeps_the_old_value_and_a_repeat_is_no_change(session, shop):
    await _apply(session, shop, await _with_vat(session, shop, {1: "Có"}))
    template = xlsx_io.read_workbook(await _template(session, shop))["VAT"]
    assert template[1][1] == "Có" and _c(template[2], 1) is None  # carried back into the template
    again = await shop_inputs.preview_import(
        session, shop.id, await _with_vat(session, shop, {1: "có"})
    )
    assert again.shop_diffs == [] and again.changes == []


async def test_a_flag_that_is_neither_yes_nor_no_is_rejected(session, shop):
    preview = await shop_inputs.preview_import(
        session, shop.id, await _with_vat(session, shop, {1: "có lẽ"})
    )
    assert _kinds(preview) == ["invalid_value"] and preview.rejections[0].sheet == "VAT"
    assert preview.shop_diffs == []


async def test_a_file_with_only_the_new_sheets_is_a_file(session, shop):
    content = xlsx_io.write_workbook(
        [xlsx_io.SheetSpec("VAT", [["thiết lập", "giá trị"], ["giá bán đã gồm VAT", "Không"]])]
    )
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert [d.new for d in preview.shop_diffs] == [False]
    with pytest.raises(shop_inputs.ImportFileError, match="Thành phần combo"):
        await shop_inputs.preview_import(
            session, shop.id, xlsx_io.write_workbook([xlsx_io.SheetSpec("Khác", [["a"]])])
        )


async def test_a_bill_sheet_without_its_columns_is_a_file_error(session, shop):
    content = xlsx_io.write_workbook([xlsx_io.SheetSpec(BOM, [["item_id", "x"], ["600", "y"]])])
    with pytest.raises(shop_inputs.ImportFileError, match="SKU thành phần"):
        await shop_inputs.preview_import(session, shop.id, content)


# ====================================================================== rules and overview


def test_the_new_rule_keys_validate_their_values_and_scopes():
    ok = shop_rules.validate_rule
    assert ok("pack_count", "500:5003", "3") == ("500:5003", 3)
    assert ok("vat_rate", "G700001", "8") == ("G700001", 8)
    assert ok("prices_include_vat", "", True) == ("", True)
    assert ok("pack_components", "600", [{"sku": " G7 ", "qty": 2}]) == (
        "600",
        [{"sku": "G7", "qty": 2}],
    )
    bad = [
        ("pack_count", "500:5003", 0),
        ("pack_count", "500:5003", 101),
        ("pack_count", "500:5003", 2.5),
        ("pack_count", "", 3),
        ("vat_rate", "G7", 7),
        ("vat_rate", "G7", "8.5"),
        ("prices_include_vat", "", "yes"),
        ("prices_include_vat", "x", True),
        ("pack_components", "600", []),
        ("pack_components", "600", [{"sku": "G7"}]),
        ("pack_components", "600", [{"sku": "G7", "qty": 0}]),
        ("pack_components", "600", [{"sku": "G7", "qty": 1}, {"sku": "G7", "qty": 2}]),
        ("pack_components", "600", [{"sku": "G", "qty": 1}] * 21),
    ]
    for key, scope, value in bad:
        with pytest.raises(shop_rules.RuleValidationError):
            ok(key, scope, value)


async def test_the_overview_counts_packs_boms_and_the_vat_flags(session, shop):
    await _apply(session, shop, await _with_bom(session, shop, GOOD))
    await _apply(session, shop, await _with_vat(session, shop, {1: "Có"}))
    overview = await shop_inputs.build_overview(session, shop.id)
    assert overview["packs"] == {"set_by_seller": 0, "from_name": 2, "bom_listings": 1}
    assert overview["vat"]["prices_include_vat"] is True
    assert overview["vat"]["cost_includes_vat"] is None
    assert "sau VAT" in overview["vat"]["label"]
    assert overview["catalogue"]["with_cost"] == 0
