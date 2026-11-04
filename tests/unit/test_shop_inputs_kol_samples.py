"""P91 D-9: the "Mẫu KOL" sheet - template, preview, apply, versions, restore, cost.

Service level against SQLite; synthetic shop and KOL handles only (no real creators).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from juli_backend.services import shop_inputs
from juli_backend.services.shop_inputs import kol_samples, xlsx_io
from juli_backend.services.shop_rules.rules import RuleValidationError, validate_rule
from tests.support.builders import make_tenant
from tests.support.shop_inputs import seed_catalogue

SELLER = shop_inputs.Actor("seller", uuid.UUID(int=7))
TEAM = shop_inputs.Actor("team", uuid.UUID(int=8))
T0 = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
SHEET = "Mẫu KOL"
HEADER = [h for h, _, _ in kol_samples.SAMPLE_COLUMNS]


@pytest.fixture
async def shop(session):
    _, shop = await make_tenant(session)
    await seed_catalogue(session, shop)
    return shop


async def _file(session, shop, rows: list[list[object]]) -> bytes:
    """The shop's template with the Mẫu KOL sheet rewritten to ``rows`` (header kept)."""
    content = (await shop_inputs.build_template(session, shop.id)).content
    sheet = [HEADER, *rows]
    sheets = xlsx_io.read_workbook(content)
    specs = [
        xlsx_io.SheetSpec(name, sheet if name == SHEET else grid) for name, grid in sheets.items()
    ]
    return xlsx_io.write_workbook(specs)


def test_the_sheet_is_in_the_template_and_has_the_artboard_columns():
    assert HEADER == [
        "KOL (tay cầm)",
        "Sản phẩm (mã SP hoặc SKU)",
        "Số lượng mẫu",
        "Ngày gửi",
        "Phí ship gửi mẫu",
        "Ghi chú",
    ]
    assert "phí book" in kol_samples.NOTE_SAMPLE


def test_the_rule_validates_scope_and_shipments():
    key = kol_samples.make_key("kol_alpha")
    scope = kol_samples.scope_ref(key, "2001:2001-a")
    ok = [{"handle": "kol_alpha", "qty": 3, "sent_on": "2026-11-02", "ship_fee": 25000}]
    assert validate_rule("kol_sample", scope, ok) == (scope, ok)
    assert validate_rule("kol_sample", scope, [])[1] == []
    for bad in (
        [{"handle": "x", "qty": 0, "sent_on": "2026-11-02", "ship_fee": 0}],
        [{"handle": "x", "qty": 1, "sent_on": "02/11/2026", "ship_fee": 0}],
        [{"handle": "x", "qty": 1, "sent_on": "2026-11-02", "ship_fee": -1}],
        [{"handle": "", "qty": 1, "sent_on": "2026-11-02", "ship_fee": 0}],
        [{"handle": "x", "qty": 1, "sent_on": "2026-11-02", "ship_fee": 0, "booking": 9}],
        "text",
    ):
        with pytest.raises(RuleValidationError):
            validate_rule("kol_sample", scope, bad)
    with pytest.raises(RuleValidationError):
        validate_rule("kol_sample", "1001", ok)


def test_sample_cost_is_qty_times_cost_plus_pack_plus_ship_with_the_one_third_fallback():
    shipments = [
        kol_samples.Shipment("k", 3, date(2026, 11, 2), Decimal(25000)),
        kol_samples.Shipment("k", 2, date(2026, 11, 9), Decimal(15000)),
    ]
    real = kol_samples.unit_cost(
        sku_scope="1001",
        item_id="1001",
        list_price=Decimal(74000),
        sku_cost={"1001": 40000},
        product_cost={},
        packaging={"1001": 2000},
    )
    assert real is not None and real.cogs_source == "real" and real.total == Decimal(42000)
    assert kol_samples.sample_cost(shipments, real) == Decimal(5 * 42000 + 40000)
    assumed = kol_samples.unit_cost(
        sku_scope="1001",
        item_id="1001",
        list_price=Decimal(75000),
        sku_cost={},
        product_cost={},
        packaging={},
    )
    assert assumed is not None and assumed.cogs == Decimal(25000)
    assert assumed.cogs_source == "assumed" and assumed.packaging_source == "assumed"
    assert "giả định" in assumed.label
    # the product-level cost wins over the fallback, the SKU cost over the product's
    prod = kol_samples.unit_cost(
        sku_scope="2001:2001-a",
        item_id="2001",
        list_price=None,
        sku_cost={},
        product_cost={"2001": 90000},
        packaging={},
    )
    assert prod is not None and prod.cogs == Decimal(90000)
    assert (
        kol_samples.unit_cost(
            sku_scope="x",
            item_id="x",
            list_price=None,
            sku_cost={},
            product_cost={},
            packaging={},
        )
        is None
    )
    assert kol_samples.sample_cost(shipments, None) is None


async def test_preview_diff_apply_and_the_cost_of_the_new_samples(session, shop):
    content = await _file(
        session,
        shop,
        [
            ["@Kol_Alpha", "GL-001", 3, "02/11/2026", 25000, ""],
            ["kol_alpha", "GL-001", 2, "09/11/2026", 15000, ""],
            ["kol_beta", "2001:2001-a", 1, "03/11/2026", 20000, "gửi hỏa tốc"],
            ["kol_gamma", "GL-001", None, None, None, ""],  # listed, nothing sent: ignored
        ],
    )
    preview = await shop_inputs.preview_import(session, shop.id, content)
    assert preview.sample_rows == 3 and preview.sample_rows_rejected == 0
    by_handle = {d.handle: d for d in preview.sample_diffs}
    assert set(by_handle) == {"Kol_Alpha", "kol_beta"}
    alpha = by_handle["Kol_Alpha"]
    assert alpha.tag == "Mới" and len(alpha.new) == 2 and alpha.old == []
    # no giá vốn imported: 1/3 of the 74.000đ list price, no packaging, labelled
    unit = (Decimal(74000) / 3).quantize(Decimal(1))
    assert alpha.new_cost == 5 * unit + 25000 + 15000
    assert "giả định" in alpha.cost_label and "Chi phí mẫu" in alpha.effect
    assert preview.changed_item_ids == ["1001", "2001"]

    result = await shop_inputs.apply_import(
        session, shop.id, content, actor=SELLER, reason="Gửi mẫu đợt 1", now=T0
    )
    await session.commit()
    assert result.samples_changed == 2 and result.versions_written == 2
    sent = await shop_inputs.load_samples(session, shop.id)
    key = kol_samples.make_key("kol_alpha")
    assert [s.qty for s in sent[(key, "1001")]] == [3, 2]
    assert sent[(key, "1001")][0].sent_on == date(2026, 11, 2)
    # unchanged on a second pass
    again = await shop_inputs.preview_import(session, shop.id, content)
    assert again.sample_diffs == [] and again.sample_rows_unchanged == 2


async def test_bad_rows_are_rejected_one_by_one_and_do_not_block_the_valid_ones(session, shop):
    content = await _file(
        session,
        shop,
        [
            ["kol_alpha", "GL-001", 3, "02/11/2026", 25000, ""],
            ["", "GL-001", 1, "02/11/2026", 0, ""],
            ["kol_alpha", "NOPE", 1, "02/11/2026", 0, ""],
            ["kol_beta", "GL-001", "x", "02/11/2026", 0, ""],
            ["kol_beta", "NR-002", 2, "not a date", 0, ""],
            ["kol_beta", "NR-002", 2, None, 5000, ""],
            ["kol_delta", "GL-001", 1, "02/11/2026", "-5", ""],
            ["kol_alpha", "BEP-S3", None, "02/11/2026", None, ""],  # date without a quantity
            ["kol_eps", "BEP-S3", 1, "05/11/2026", 0, ""],
            ["kol_eps", "BEP-S3", 4, "05/11/2026", 0, ""],  # same KOL, product, day
        ],
    )
    preview = await shop_inputs.preview_import(session, shop.id, content)
    kinds = sorted(r.kind for r in preview.rejections if r.sheet == SHEET)
    assert kinds == sorted(
        [
            "kol_missing",
            "unknown_sku",
            "invalid_value",
            "bad_date",
            "bad_date",
            "invalid_value",
            "invalid_value",
            "duplicate_sku",
        ]
    )
    assert all(r.kind_label for r in preview.rejections)
    # a pair with any rejected row (kol_beta NR-002, kol_eps BEP-S3) writes nothing
    assert [d.handle for d in preview.sample_diffs] == ["kol_alpha"]
    assert preview.sample_rows_valid == preview.sample_rows - preview.sample_rows_rejected


async def test_a_quantity_of_zero_clears_a_pair_and_restore_brings_it_back(session, shop):
    first = await _file(session, shop, [["kol_alpha", "GL-001", 3, "02/11/2026", 25000, ""]])
    await shop_inputs.apply_import(session, shop.id, first, actor=SELLER, reason="đợt 1", now=T0)
    second = await _file(session, shop, [["kol_alpha", "GL-001", 5, "02/11/2026", 25000, ""]])
    await shop_inputs.apply_import(
        session, shop.id, second, actor=TEAM, reason="Sửa số lượng", now=T0.replace(minute=5)
    )
    clear = await _file(session, shop, [["kol_alpha", "GL-001", 0, "02/11/2026", 0, ""]])
    preview = await shop_inputs.preview_import(session, shop.id, clear)
    assert [d.tag for d in preview.sample_diffs] == ["Xoá"]
    await shop_inputs.apply_import(
        session, shop.id, clear, actor=SELLER, reason="Gửi nhầm", now=T0.replace(minute=9)
    )
    key = kol_samples.make_key("kol_alpha")
    assert (key, "1001") not in await shop_inputs.load_samples(session, shop.id)
    scope = kol_samples.scope_ref(key, "1001")
    history = await shop_inputs.list_versions(
        session, shop.id, rule_key="kol_sample", scope_ref=scope
    )
    assert [(e.version, e.current) for e in history] == [(3, True), (2, False), (1, False)]
    restored = await shop_inputs.restore_version(
        session,
        shop.id,
        rule_key="kol_sample",
        scope_ref=scope,
        version=2,
        actor=SELLER,
        now=T0.replace(minute=30),
    )
    await session.commit()
    assert restored.version == 4 and restored.value[0]["qty"] == 5
    assert (await shop_inputs.load_samples(session, shop.id))[(key, "1001")][0].qty == 5


async def test_the_template_prefills_shipments_and_the_overview_lists_them(session, shop):
    content = await _file(
        session,
        shop,
        [["kol_alpha", "GL-001", 3, "02/11/2026", 25000, ""]],
    )
    await shop_inputs.apply_import(session, shop.id, content, actor=SELLER, reason="đợt 1", now=T0)
    await session.commit()
    template = await shop_inputs.build_template(session, shop.id)
    assert template.sample_rows == 1
    rows = xlsx_io.read_workbook(template.content)[SHEET]
    assert rows[1][:5] == ["kol_alpha", "GL-001", "3", "02/11/2026", "25000"]
    overview = await shop_inputs.build_overview(session, shop.id)
    assert overview["samples"]["pairs"] == 1 and overview["samples"]["shipments"] == 1
    item = overview["samples"]["items"][0]
    assert item["scope_ref"].startswith("kol:a") and item["sample_cost"] is not None
    assert item["cost_label"].startswith("giá vốn giả định")
