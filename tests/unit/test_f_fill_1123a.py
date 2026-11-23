"""batch-1123-a Track F: the fill queue for Giá, Chương Trình Của Shop, Flash Sale Của Shop,
Mua Kèm Deal Sốc / Mua Để Nhận Quà, Ảnh bìa and Phân loại hàng, their undo jobs and read-back
marking. Pure: cards are plain dicts, synthetic ids, no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from juli_backend.models.shopee_fill import (
    STATUS_CANCELLED,
    STATUS_FILLED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import fill_queue, revert_fill
from tests.unit import test_p97_fill_queue as _p97

#: 23/11/2026 10:00 GMT+7
NOW = datetime(2026, 11, 23, 3, 0, tzinfo=UTC)
P = SimpleNamespace(code="JC-2611-0007")
CATALOG = {
    "v1": {"name": "Hộp 1", "selling": 100_000, "listed": 120_000},
    "v2": {"name": "Hộp 3", "selling": 270_000, "listed": 300_000},
    "v3": {"name": "Hộp 3", "selling": 280_000, "listed": 300_000},  # same name as v2
}


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    async def fake(session, shop_id, item_id):
        return {k: dict(v) for k, v in CATALOG.items()}

    monkeypatch.setattr(fill_queue, "catalog_variations", fake)


def _card(change_kind, spec=None, inputs=None, items=("1001",), extra=None):
    card = {
        "change_kind": change_kind,
        "scope": {"level": "product", "product_ids": list(items)},
        "inputs": inputs or {},
        "versions": [{"version": 1, "spec": spec or {}, "extra": extra or {}}],
    }
    return card


async def _one(card):
    jobs = await fill_queue.build_jobs(None, uuid.uuid4(), P, card, 1, None, NOW)
    assert len(jobs) == 1, jobs
    return jobs[0]


def _row(kind, payload, **kw):
    return ShopeeFillJob(
        id=uuid.uuid4(), kind=kind, payload=payload, target=kw.pop("target", {}),
        target_key=kw.pop("key", f"{kind}:1"), seq=1, version=1,
        status=kw.pop("status", STATUS_SAVED), captured_ref=kw.pop("ref", None),
        updated_at=kw.pop("updated_at", NOW.replace(tzinfo=None)),
    )  # fmt: skip


# ------------------------------------------------------------------------------------ F2 Giá


async def test_an_approved_price_card_queues_one_job_with_a_price_per_variation():
    spec = {
        "kind": "price",
        "item_id": "1001",
        "variations": [
            {"variation_id": "v1", "final_price": 95_000},
            {"variation_id": "v2", "change_pct": 10},
        ],
    }
    job = await _one(_card("price", spec))
    assert job["kind"] == "price" and job["status"] == "queued" and job["error"] is None
    p = job["payload"]
    assert p["open_path"] == "/portal/product/1001"
    assert [(v["variation_id"], v["price"]) for v in p["variations"]] == [
        ("v1", 95_000),
        ("v2", 297_000),
    ]
    # a name only where it is unique on the item (v2 shares "Hộp 3" with v3)
    assert p["variations"][0]["name"] == "Hộp 1" and "name" not in p["variations"][1]
    assert p["old_prices"] == [
        {"variation_id": "v1", "price": 100_000, "name": "Hộp 1"},
        {"variation_id": "v2", "price": 270_000},
    ]


async def test_the_price_revert_holds_the_old_prices():
    fwd = _row(
        "price",
        {
            "item_id": "1001",
            "variations": [{"variation_id": "v1", "price": 95_000, "name": "Hộp 1"}],
            "old_prices": [{"variation_id": "v1", "price": 100_000}],
        },
        target={"item_id": "1001"},
    )
    spec = revert_fill._revert_spec(fwd, {})
    assert spec["kind"] == "price" and spec["error"] is None
    assert spec["target_key"] == "revert:price:1001"
    assert spec["payload"]["mode"] == "revert"
    assert spec["payload"]["variations"] == [
        {"variation_id": "v1", "price": 100_000, "name": "Hộp 1"}
    ]
    # what the Connector read on the page before it wrote wins over the catalogue
    fwd.payload = {**fwd.payload, "before_values": {"price_v1": "99.000"}}
    assert revert_fill._revert_spec(fwd, {})["payload"]["variations"][0]["price"] == 99_000


async def test_a_product_without_variations_or_a_price_is_a_failed_job_with_a_reason():
    no_var = await _one(_card("price", {"variations": [{"variation_id": "", "final_price": 9}]}))
    assert no_var["status"] == "failed" and no_var["error"] == fill_queue.ERR_NO_VARIATION
    unknown = await _one(_card("price", {"variations": [{"variation_id": "v9", "change_pct": 5}]}))
    assert unknown["error"] == fill_queue.ERR_PRICE
    assert len(fill_queue.ERR_NO_VARIATION) <= 64


# -------------------------------------------------------------- F3 Chương Trình Của Shop


async def test_a_shop_programme_carries_its_name_dates_and_one_value_per_variation():
    spec = {
        "kind": "product_discount",
        "name": "Sale cuối tháng",
        "item_id": "1001",
        "variations": [
            {"variation_id": "v1", "final_price": 90_000},
            {"variation_id": "v2", "discount_pct": 12},
        ],
        "start": "2026-11-25",
        "start_hour": 9,
        "end": "2026-11-28",
        "end_hour": 21,
        "per_buyer_limit": 3,
    }
    job = await _one(_card("product_discount", spec))
    p = job["payload"]
    assert job["kind"] == "product_discount" and job["error"] is None
    assert p["open_path"] == "/portal/marketing/discount/create"
    assert p["name"] == "Sale cuối tháng"
    assert (p["starts_at"], p["ends_at"]) == ("09:00 25-11-2026", "21:00 28-11-2026")
    assert p["variations"] == [
        {"variation_id": "v1", "final_price": 90_000, "name": "Hộp 1"},
        {"variation_id": "v2", "discount_pct": 12},
    ]
    assert p["per_buyer_limit"] == 3 and "promo_qty" not in p


async def test_an_engine_discount_card_is_one_percent_for_every_variation():
    job = await _one(_card("product_discount", None, {"discount_pct": 15}))
    assert job["payload"]["all_pct"] == 15 and job["payload"]["variations"] == []
    assert job["payload"]["name"] == "JC-2611-0007 V1"


async def test_a_programme_shorter_than_an_hour_is_refused():
    spec = {"start": "2026-11-25", "start_hour": 9, "end": "2026-11-25", "end_hour": 9}
    job = await _one(_card("product_discount", spec, {"discount_pct": 10}))
    assert job["status"] == "failed" and job["error"] == fill_queue.ERR_WINDOW


# ------------------------------------------------------------------ F4 Flash Sale Của Shop


def test_the_slot_is_a_day_and_shopees_label_never_an_id():
    slot, err = fill_queue.flash_slot("2026-11-30T21:00", NOW)
    assert err is None
    assert slot == {
        "day": "2026-11-30",
        "label": "21:00:00 - 00:00:00",
        "starts_at": "21:00 30-11-2026",
        "hours": 3,
    }
    assert fill_queue.flash_slot("2026-11-25 02:00", NOW)[0]["hours"] == 7  # 02-09


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (None, fill_queue.ERR_FLASH_NO_SLOT),
        ("2026-11-25T10:00", fill_queue.ERR_FLASH_BAD_SLOT),  # not a slot start
        ("2026-11-25T12:30", fill_queue.ERR_FLASH_BAD_SLOT),
        ("2026-11-23T21:00", fill_queue.ERR_FLASH_DAY),  # today: not bookable
        ("2026-12-01T12:00", fill_queue.ERR_FLASH_DAY),  # 8 days ahead
        ("hôm nay", fill_queue.ERR_FLASH_BAD_SLOT),
    ],
)
def test_a_slot_outside_shopees_list_or_week_is_refused_in_vietnamese(raw, error):
    slot, err = fill_queue.flash_slot(raw, NOW)
    assert slot is None and err == error and len(err) <= 64


async def test_a_flash_sale_job_writes_price_and_stock_and_refuses_a_bad_slot():
    spec = {
        "kind": "flash_sale",
        "item_id": "1001",
        "variations": [{"variation_id": "v1", "discount_pct": 20}],
        "units": 50,
        "slot_start": "2026-11-26T12:00",
    }
    job = await _one(_card("flash_sale", spec))
    p = job["payload"]
    assert job["error"] is None and p["open_path"] == "/portal/marketing/shop-flash-sale/create"
    assert p["slot"]["label"] == "12:00:00 - 15:00:00" and p["slot"]["day"] == "2026-11-26"
    assert p["variations"] == [
        {"variation_id": "v1", "discount_pct": 20, "name": "Hộp 1", "stock": 50}
    ]
    assert "purchase_limit" not in p
    bad = await _one(_card("flash_sale", {**spec, "slot_start": "2026-11-26T13:00"}))
    assert bad["status"] == "failed" and bad["error"] == fill_queue.ERR_FLASH_BAD_SLOT
    pct = await _one(
        _card("flash_sale", {**spec, "variations": [{"variation_id": "v1", "discount_pct": 3}]})
    )
    assert pct["error"] == fill_queue.ERR_FLASH_PCT


# ------------------------------------------------------- F5 Mua Kèm Deal Sốc / Mua Để Nhận Quà


async def test_an_add_on_deal_fills_step_one_and_names_the_products():
    spec = {
        "kind": "add_on",
        "name": "Mua kèm tháng 12",
        "main_item_id": "1001",
        "addons": [{"item_id": "2001", "pct": 10}, {"item_id": "2002", "price": 15_000}],
        "addon_limit": 2,
        "start": "2026-11-25",
        "end": "2026-11-30",
    }
    job = await _one(_card("add_on", spec))
    p = job["payload"]
    assert job["error"] is None and p["deal_type"] == "add_on"
    assert p["open_path"] == "/portal/marketing/add-on-deal/create"
    assert p["main_product_ids"] == ["1001"] and p["addon_product_ids"] == ["2001", "2002"]
    assert p["addon_limit"] == 2 and p["name"] == "Mua kèm tháng 12"
    assert (p["starts_at"], p["ends_at"]) == ("00:00 25-11-2026", "23:59 30-11-2026")


async def test_a_deal_name_over_25_characters_is_refused_on_the_card_and_by_the_fill():
    long = "Mua kèm siêu tiết kiệm tháng 12"
    assert len(long) > 25
    with pytest.raises(ValidationError) as card:
        sp.AddOnSpec(
            kind="add_on", name=long, main_item_id="1", addons=[{"item_id": "2", "pct": 5}]
        )
    assert "25" in str(card.value)
    with pytest.raises(ValidationError) as gift:
        sp.GiftSpec(
            kind="gift",
            name=long,
            gift={"item_id": "3"},
            trigger={"type": "min_spend", "amount": 1},
        )
    assert "25" in str(gift.value)
    job = await _one(
        _card("add_on", {"name": long, "main_item_id": "1001", "addons": [{"item_id": "2001"}]})
    )
    assert job["status"] == "failed" and job["error"] == fill_queue.ERR_DEAL_NAME


async def test_a_gift_needs_a_listed_gift_and_a_spend_amount():
    spec = {
        "kind": "gift",
        "name": "Quà 12.12",
        "gift": {"item_id": "3001", "qty": 2},
        "trigger": {"type": "min_spend", "amount": 300_000},
    }
    job = await _one(_card("gift", spec, items=()))
    p = job["payload"]
    assert job["error"] is None and p["deal_type"] == "gift"
    assert (p["min_spend"], p["gift_qty"], p["gift_product_ids"]) == (300_000, 2, ["3001"])
    unsold = await _one(_card("gift", {**spec, "gift": {"unit_cost": 5000, "qty": 1}}, items=()))
    assert unsold["error"] == fill_queue.ERR_GIFT_UNSOLD
    by_item = await _one(
        _card("gift", {**spec, "trigger": {"type": "buy_item", "item_id": "1001"}})
    )
    assert by_item["error"] == fill_queue.ERR_GIFT_SPEND


def _deal(status, step1=True, **kw):
    checks = [
        {"key": fill_queue.DEAL_STEP1_KEY, "ok": step1, "seen": "đã lưu" if step1 else "chưa"}
    ]
    return _row("add_on", {"name": "Mua kèm", "fill_check": checks}, status=status, **kw)


def test_an_abandoned_deal_after_step_one_shows_an_empty_programme_notice():
    stale = (NOW - timedelta(hours=30)).replace(tzinfo=None)
    assert fill_queue.job_json(_deal(STATUS_CANCELLED))["notice"] == fill_queue.DEAL_ABANDONED
    assert (
        fill_queue.job_json(_deal(STATUS_FILLED, updated_at=stale))["notice"]
        == fill_queue.DEAL_ABANDONED
    )
    # still being worked on, never saved at step 1, or finished: no notice
    assert (
        fill_queue.job_json(
            _deal(STATUS_FILLED, updated_at=datetime.now(UTC).replace(tzinfo=None))
        )["notice"]
        is None
    )
    assert fill_queue.job_json(_deal(STATUS_CANCELLED, step1=False))["notice"] is None
    assert fill_queue.job_json(_deal(STATUS_SAVED))["notice"] is None


def test_programme_undos_end_the_row_by_id_else_by_what_the_list_shows():
    deal = revert_fill._revert_spec(_deal(STATUS_SAVED, ref="555"), {})
    assert deal["kind"] == "deal_end" and deal["error"] is None
    assert deal["payload"] == {
        "mode": "revert",
        "open_path": "/portal/marketing/list/discount",
        "name": "Mua kèm",
        "deal_type": "add_on",
        "id": "555",
    }
    disc = revert_fill._revert_spec(_row("product_discount", {"name": "Sale"}), {})
    assert disc["kind"] == "discount_end" and disc["payload"]["name"] == "Sale"
    flash = revert_fill._revert_spec(
        _row(
            "flash_sale",
            {"slot": {"day": "2026-11-30", "label": "21:00:00 - 00:00:00", "hours": 3}},
        ),
        {},
    )
    assert flash["kind"] == "flash_sale_end"
    assert flash["payload"]["open_path"] == "/portal/marketing/shop-flash-sale/list"
    assert flash["payload"]["slot"] == {"day": "2026-11-30", "label": "21:00:00 - 00:00:00"}
    assert (
        revert_fill._revert_spec(_row("product_discount", {}), {})["error"]
        == "revert_target_unknown"
    )


# ------------------------------------------------------- F6 Ảnh bìa / F7 Phân loại hàng


async def test_a_cover_job_keeps_the_old_cover_address_for_the_undo():
    extra = {"cover_url": "https://cf.example.test/old.jpg"}
    job = await _one(_card("cover_image", extra=extra))
    assert job["kind"] == "cover_image" and job["payload"]["old_cover_url"] == extra["cover_url"]
    undo = revert_fill._revert_spec(_row("cover_image", job["payload"]), {})
    assert undo["payload"]["old_cover_url"] == extra["cover_url"] and undo["error"] is None
    missing = await _one(_card("cover_image"))
    assert missing["error"] == fill_queue.ERR_COVER


async def test_a_variation_set_job_names_the_new_options_and_keeps_the_old_ones():
    inputs = {"variations": [{"name": "Set 3", "price": 280_000, "sku": "S3", "stock": 10}]}
    extra = {"current_variations": [{"name": "Hộp 1", "price": 100_000, "sku": "S1", "stock": 4}]}
    job = await _one(_card("variation_restructure", None, inputs, extra=extra))
    assert job["kind"] == "variation_set" and job["error"] is None
    assert job["payload"]["options"] == [
        {"name": "Set 3", "price": 280_000, "sku": "S3", "stock": 10}
    ]
    assert job["payload"]["old_variations"] == extra["current_variations"]
    undo = revert_fill._revert_spec(_row("variation_set", job["payload"]), {})
    assert undo["payload"]["remove_options"] == ["Set 3"] and undo["kind"] == "variation_set"


# ---------------------------------------------------------------- F1 / F9 voucher, read-back


async def test_a_product_level_voucher_queues_the_product_scope():
    card = _card("min_spend_voucher", None, {"value": 5000, "min_spend": 100_000, "quantity": 20})
    job = await _one(card)
    assert job["payload"]["usecase"] == 2 and job["payload"]["product_ids"] == ["1001"]
    card["scope"] = {"level": "shop", "product_ids": []}
    shop = await _one(card)
    assert shop["payload"]["usecase"] == 1 and shop["payload"]["product_ids"] == []


def test_only_voucher_and_combo_and_text_kinds_have_a_readback_the_rest_are_unsupported():
    for kind in ("voucher", "combo", "title"):
        assert fill_queue.job_json(_row(kind, {}))["readback"] != "unsupported"
    for kind in (
        "price",
        "product_discount",
        "flash_sale",
        "add_on",
        "gift",
        "cover_image",
        "variation_set",
    ):
        assert fill_queue.job_json(_row(kind, {}))["readback"] == "unsupported"
        assert revert_fill._readback_of_change(kind, {"item_id": "1"}) is None


def test_every_new_job_kind_is_queued_from_its_card_kind():
    card_kinds = (
        "price",
        "product_discount",
        "flash_sale",
        "add_on",
        "gift",
        "cover_image",
        "variation_restructure",
    )
    assert {fill_queue._KIND_OF[k] for k in card_kinds} == set(fill_queue._PROMO_KINDS)


# ------------------------------------------------- owner 23/11: Flash Sale Giới hạn đặt hàng


async def test_a_flash_sale_purchase_limit_rides_from_the_spec_to_the_fill():
    spec = sp.FlashSaleSpec(
        kind="flash_sale",
        item_id="1001",
        variations=[{"variation_id": "v1", "discount_pct": 20}],
        units=50,
        slot_start="2026-11-26T12:00",
        purchase_limit=2,
    )
    job = await _one(_card("flash_sale", sp.as_json(spec)))
    assert job["error"] is None and job["payload"]["purchase_limit"] == 2
    for bad in (0, 1001):
        with pytest.raises(ValidationError) as exc:
            sp.FlashSaleSpec(kind="flash_sale", item_id="1", units=1, purchase_limit=bad)
        assert "purchase_limit" in str(exc.value)


async def test_add_on_rows_carry_the_price_or_percent_and_limit_for_step_three():
    spec = {
        "name": "Mua kèm",
        "main_item_id": "1001",
        "addons": [
            {"item_id": "2001", "pct": 10, "limit_per_order": 2},
            {"item_id": "2002", "price": 15_000},
        ],
    }
    job = await _one(_card("add_on", spec))
    assert job["payload"]["addons"] == [
        {"item_id": "2001", "pct": 10, "limit": 2},
        {"item_id": "2002", "price": 15_000},
    ]
    both = {**spec, "addons": [{"item_id": "2001", "pct": 10, "price": 9}]}
    assert (await _one(_card("add_on", both)))["error"] == fill_queue.ERR_DEAL_ADDONS


async def test_a_cover_card_with_a_juli_image_carries_its_address_for_the_upload():
    card = _card("cover_image", extra={"cover_url": "https://cf.example.test/old.jpg"})
    card["execution_sheet"] = {
        "downloads": [{"label": "Tải ảnh", "url": "https://img.example.test/new.png"}]
    }
    job = await _one(card)
    assert job["payload"]["new_cover_url"] == "https://img.example.test/new.png"
    card["execution_sheet"] = {"downloads": [{"url": "http://insecure.example.test/x.png"}]}
    assert "new_cover_url" not in (await _one(card))["payload"]


# ------------------------------------------------------------- F7 locked by a promotion (DB)

shop = _p97.shop
_flag_on = _p97._flag_on


async def test_a_locked_product_page_ends_the_job_with_the_vietnamese_reason(session, shop):
    seeded, ids = shop
    await _p97._approve(session, seeded, ids[2])  # any job: the lock check is the same for all
    (job,) = [j for j in await _p97._jobs(session, seeded) if j.kind == "affiliate_commission"]
    out = await fill_queue.report(
        session,
        seeded.shop_id,
        job.id,
        status="opened",
        field_checks=[{"key": "promotion_lock", "ok": False, "seen": fill_queue.PROMOTION_LOCKED}],
    )
    assert out["status"] == "failed" and out["error"] == fill_queue.PROMOTION_LOCKED
    assert not fill_queue.promotion_locked([{"key": "promotion_lock", "ok": True}])


# ------------------------------------------- decision #13: each Shopee form's own name limit


def _add_on(n):
    return sp.AddOnSpec(
        kind="add_on", name=n, main_item_id="1", addons=[{"item_id": "2", "pct": 5}]
    )


def _gift(n):
    trigger = {"type": "min_spend", "amount": 1}
    return sp.GiftSpec(kind="gift", name=n, gift={"item_id": "3"}, trigger=trigger)


def _combo(n):
    tiers = [{"qty": 2, "value": 5}]
    return sp.ComboSpec(kind="combo", name=n, item_ids=["1"], discount_type="pct", tiers=tiers)


def _discount(n):
    rows = [{"variation_id": "v1", "discount_pct": 5}]
    return sp.ProductDiscountSpec(kind="product_discount", name=n, item_id="1", variations=rows)


def _title(n):
    return sp.TitleSpec(kind="title", item_id="1", title=n)


@pytest.mark.parametrize(
    ("make", "limit", "what"),
    [
        (_add_on, 25, "Tên Deal Sốc"),
        (_gift, 25, "Tên Deal Sốc"),
        (_combo, 25, "Tên Combo Khuyến Mãi"),
        (_discount, 150, "Tên chương trình khuyến mãi"),
        (_title, 120, "Tên sản phẩm"),
    ],
)
def test_a_card_name_over_its_forms_limit_is_refused_in_vietnamese(make, limit, what):
    make("x" * limit)  # at the limit: accepted
    with pytest.raises(ValidationError) as exc:
        make("x" * (limit + 1))
    assert f"{what} tối đa {limit} ký tự." in str(exc.value)


async def test_the_fill_refuses_an_over_limit_name_naming_the_limit():
    combo = _card("bundle_deal", None, {"name": "c" * 26, "tiers": [{"qty": 2, "value": 5}]})
    job = await _one(combo)
    assert job["status"] == "failed" and job["error"] == "Tên Combo Khuyến Mãi tối đa 25 ký tự"
    discount = await _one(_card("product_discount", {"name": "d" * 151}, {"discount_pct": 10}))
    assert discount["error"] == "Tên chương trình khuyến mãi tối đa 150 ký tự"
    title = _card("title")
    title["execution_sheet"] = {
        "changes": [{"change_kind": "title", "expected": {"title": "t" * 121}}]
    }
    assert (await _one(title))["error"] == "Tên sản phẩm tối đa 120 ký tự"
    deal = await _one(
        _card(
            "add_on",
            {"name": "n" * 26, "main_item_id": "1", "addons": [{"item_id": "2", "pct": 1}]},
        )
    )
    assert deal["error"] == "Tên Deal Sốc tối đa 25 ký tự"
