"""batch-1117b X2 / U2: the execution sheet is clean (Vietnamese labels, every field, real dates,
the product's own page) and "Hoàn tác" is a recorded state: a ``reverted`` event, the card's
measurement stopped and its observations kept out of calibration. Synthetic data only."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import EVENT_REVERTED, CardEvent
from juli_backend.models.shop_proposals import STATUS_EXECUTED, ShopProposal
from juli_backend.models.shopee_fill import STATUS_FILLED, ShopeeFillJob
from juli_backend.models.shopee_plans import ShopRecoChangeSet
from juli_backend.services.card_events import verification
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import (
    execution_state,
    measure,
    sheet,
    store,
)
from juli_backend.services.shopee_recommendations import service as reco
from juli_backend.services.shopee_recommendations.learning import Observation
from tests.unit import test_shopee_reco_board_sync as _board

NOW = _board.NOW
_commit = _board._commit
shop = _board.shop  # the shared fixture, re-exported for this module

NAMES = {"1001": "Sản phẩm mẫu", "1002": "Cây rửa ly", "1003": "Viên giặt"}
RAW_KEYS = ("daily_budget", "addon_item_id", "addon_price", "discount_pct", "10000000001")


def _text(steps: list[dict]) -> str:
    return " | ".join(f"{s['field']} {s['before']} {s['after']}" for s in steps)


def _no_raw(sh: dict) -> None:
    blob = _text(sh["steps"]) + _text(sh["revert_steps"])
    for raw in RAW_KEYS:
        assert raw not in blob, raw


# ------------------------------------------------------------------ the sheet, per kind (pure)


def test_a_voucher_sheet_holds_every_field_with_real_dates_and_reverts_by_deleting_it():
    sh = sheet.build_sheet(
        "min_spend_voucher",
        {"voucher_id": None},
        {},
        {"value": 1000, "min_spend": 5_000_000, "quantity": 1, "days": 2},
        {"name": "JULI TEST", "start": "2026-11-25", "end": "2026-11-26", "per_user_limit": 1},
        names=NAMES,
        items=[],
    )
    fields = {s["field"]: s["after"] for s in sh["steps"]}
    assert fields["Loại voucher"] == "Voucher toàn shop · Khuyến mãi"
    assert fields["Tên chương trình"] == "JULI TEST"
    assert fields["Mức giảm"] == "1.000đ"
    assert fields["Đơn tối thiểu"] == 5_000_000
    assert fields["Tổng lượt sử dụng"] == 1
    assert fields["Mỗi người mua dùng tối đa"] == 1
    assert fields["Thời gian sử dụng"] == "25/11/2026 – 26/11/2026"
    assert fields["Hiển thị"] == "Hiển thị nhiều nơi"
    assert sh["time_window"]["start"] == "25/11/2026 – 26/11/2026"
    assert "2026-11" not in _text(sh["steps"])
    (rev,) = sh["revert_steps"]
    assert 'Xoá hoặc kết thúc voucher "JULI TEST"' in rev["field"] and rev["action"]
    assert sh["new_object"] == "voucher"
    assert sh["page"]["deep_link"].endswith("/portal/marketing/vouchers/new?usecase=1")
    _no_raw(sh)


def test_a_combo_sheet_names_its_products_tiers_and_period_and_the_page_is_the_combo_form():
    sh = sheet.build_sheet(
        "bundle_deal",
        {"item_id": "1001"},
        {"tiers": []},
        {"tiers": [{"units": 2, "discount_pct": 2}, {"units": 3, "discount_pct": 8}]},
        {"name": "Combo thử", "start": "2026-11-25", "end": "2026-11-26", "discount_type": "pct"},
        names=NAMES,
        items=["1001", "1002"],
    )
    fields = {s["field"]: s["after"] for s in sh["steps"]}
    assert fields["Tên combo"] == "Combo thử"
    assert fields["Sản phẩm trong combo"] == "Sản phẩm mẫu, Cây rửa ly"
    assert fields["Mức ưu đãi"] == "Mua 2 giảm 2 % · Mua 3 giảm 8 %"
    assert fields["Thời gian"] == "25/11/2026 – 26/11/2026"
    assert sh["page"]["deep_link"].endswith("/portal/marketing/bundle/new")
    assert sh["revert_steps"][0]["action"] and sh["new_object"] == "combo"
    _no_raw(sh)


def test_a_deal_soc_sheet_has_no_raw_keys_and_names_main_and_add_on_products():
    sh = sheet.build_sheet(
        "add_on",
        {"item_id": "1001", "addon_item_id": "1002"},
        {"addon_price": 75_000},
        {
            "addon_item_id": "1002",
            "addon_price": 71_012,
            "discount_pct": 5,
            "addons": [{"item_id": "1002", "price": 71_012, "limit_per_order": 1}],
        },
        {"name": "JULI TEST 1711", "start": "2026-11-25", "end": "2026-11-26"},
        names=NAMES,
        items=["1001"],
    )
    fields = {s["field"]: s["after"] for s in sh["steps"]}
    assert fields["Tên chương trình"] == "JULI TEST 1711"
    assert fields["Sản phẩm chính"] == "Sản phẩm mẫu"
    assert fields["Sản phẩm mua kèm"] == "Cây rửa ly"
    assert fields["Giá mua kèm"] == 71_012 and fields["Mức giảm"] == 5
    assert fields["Giới hạn mỗi đơn"] == 1
    assert fields["Thời gian"] == "25/11/2026 – 26/11/2026"
    _no_raw(sh)


def test_a_shop_programme_shows_name_percent_period_and_the_product_name_not_its_id():
    sh = sheet.build_sheet(
        "product_discount",
        {"item_id": "10000000001"},
        {"price": 139_000, "skus": [{"sku": "s1", "price": 139_000}]},
        {
            "price": 138_600,
            "skus": [{"sku": "s1", "price": 138_600}],
            "discount_pct": 30,
            "units": 20,
        },
        {"name": "CT shop", "start": "2026-11-25", "end": "2026-11-26", "limit_per_buyer": 2},
        names={"10000000001": "Sản phẩm mẫu"},
    )
    by = {s["field"]: s for s in sh["steps"]}
    assert by["Giá bán — Sản phẩm mẫu"]["before"] == 139_000
    assert by["Giá bán — Sản phẩm mẫu"]["after"] == 138_600
    assert by["Tên chương trình"]["after"] == "CT shop"
    assert by["Mức giảm"]["after"] == 30 and by["Số lượng suất"]["after"] == 20
    assert by["Giới hạn mua mỗi người"]["after"] == 2
    assert by["Thời gian"]["after"] == "25/11/2026 – 26/11/2026"
    _no_raw(sh)


def test_a_price_sheet_links_the_product_edit_page_not_the_list_and_without_names_no_raw_id():
    sh = sheet.build_sheet(
        "price",
        {"item_id": "10000000001"},
        {"skus": [{"sku": "s1", "price": 139_000}]},
        {"skus": [{"sku": "s1", "price": 140_000}]},
        {},
    )
    assert sh["page"]["deep_link"] == "https://banhang.shopee.vn/portal/product/10000000001"
    assert sh["steps"][0]["field"] == "Giá bán"  # an unnamed product is not shown as its id
    assert sh["time_window"]["start"] == "khi bạn bấm lưu"  # no dates: only then
    _no_raw(sh)


def test_an_ads_sheet_uses_vietnamese_labels_and_drops_unlabelled_keys():
    sh = sheet.build_sheet(
        "ads_budget",
        {"campaign_id": "c1"},
        {"daily_budget": 100_000, "spend_per_day": 90_000},
        {"daily_budget": 150_000, "campaign_id": "c1", "weird_internal_key": 3},
        {"daily_budget": 150_000},
    )
    (step,) = sh["steps"]
    assert step["field"] == "Ngân sách mỗi ngày" and (step["before"], step["after"]) == (
        100_000,
        150_000,
    )
    assert "weird_internal_key" not in _text(sh["steps"])
    _no_raw(sh)


def test_a_cover_before_never_says_1_of_1_and_a_raw_image_id_is_not_the_after():
    sh = sheet.build_sheet(
        "cover_image",
        {"item_id": "1001"},
        {"cover_url": "u", "text": "Ảnh bìa hiện tại (ảnh 1 trong 1): https://x/y.jpg"},
        {"text": "vn-11134207-81ztc-mvibeyc1s6bqdc", "banner": {"kind": "corner"}},
        {},
    )
    (step,) = sh["steps"]
    assert "ảnh 1 trong 1" not in step["before"]
    assert "vn-11134207" not in str(step["after"])
    assert sh["page"]["deep_link"].endswith("/portal/product/1001")


# --------------------------------------------------------- before values (X2) from the Connector


def test_a_missing_before_is_filled_from_the_connector_capture_and_otherwise_named():
    base = sheet.build_sheet(
        "description_first_line",
        {"item_id": "1001"},
        {"first_line": None},
        {"first_line": "Dòng mới"},
        {},
    )
    assert base["revert_steps"][0]["after"] is None
    got = sheet.with_job_before(base, [{"payload": {"before_values": {"first_line": "Dòng cũ"}}}])
    assert (
        got["steps"][0]["before"] == "Dòng cũ" and got["steps"][0]["before_source"] == "connector"
    )
    assert got["revert_steps"][0]["after"] == "Dòng cũ" and got["unknown_before"] == []
    # a list shape and a job-level field are read too
    rows = [{"before_values": [{"key": "first_line", "value": "Dòng cũ 2"}]}]
    assert sheet.with_job_before(base, rows)["steps"][0]["before"] == "Dòng cũ 2"
    # nothing captured: the field is named, never invented
    none = sheet.with_job_before(base, [])
    assert none["unknown_before"] == ["Dòng đầu của Mô tả sản phẩm (giữ nguyên phần còn lại)"]
    assert none["steps"][0]["before_source"] is None


def test_the_cards_own_before_wins_over_the_connector_capture():
    base = sheet.build_sheet("title", {"item_id": "1001"}, {"title": "Cũ"}, {"title": "Mới"}, {})
    got = sheet.with_job_before(base, [{"payload": {"before_values": {"title": "Khác"}}}])
    assert got["steps"][0]["before"] == "Cũ" and got["steps"][0]["before_source"] == "card"


def test_a_new_object_has_no_unknown_before():
    base = sheet.build_sheet(
        "min_spend_voucher", {}, {}, {"value": 1000, "min_spend": 1, "quantity": 1, "days": 1}, {}
    )
    assert sheet.with_job_before(base, [])["unknown_before"] == []


def test_a_filled_job_with_fields_missing_is_not_filled():
    job = {"status": STATUS_FILLED, "kind": "voucher", "progress": {"filled": 0, "total": 10}}
    state = execution_state.derive_state([job], [])
    assert state["state"] == execution_state.STATE_WAITING and state["jobs"]["filled"] == 0
    whole = {**job, "progress": {"filled": 10, "total": 10}}
    assert execution_state.derive_state([whole], [])["state"] == execution_state.STATE_FILLED


# ----------------------------------------------------------------------- the recorded revert (DB)


async def _td1(session, shop) -> uuid.UUID:
    result = await _commit(session, shop)
    ids = {c["ref"]: uuid.UUID(c["card_id"]) for c in result.cards if c["action"] == "created"}
    return ids["TD-1"]


@pytest.mark.timeout(180)  # one import of the synthetic shop; slow under a loaded machine
async def test_reverting_is_recorded_stops_measurement_and_leaves_calibration(session, shop):
    card_id = await _td1(session, shop)
    meta = await store.card_meta(session, shop.shop_id, card_id)
    cset = await session.get(ShopRecoChangeSet, uuid.UUID(meta["change_set"]))
    assert str(card_id) in (cset.card_ids or [])
    # the Connector's captured before completes the sheet on the card page (X2)
    session.add(
        ShopeeFillJob(
            id=uuid.uuid4(),
            shop_id=shop.shop_id,
            proposal_id=card_id,
            version=1,
            kind="title",
            target={"item_id": "1001"},
            target_key="title:1001",
            seq=0,
            payload={"before_values": {"title": "Tên cũ do Connector đọc"}},
            status=STATUS_FILLED,
            created_at=datetime(2026, 10, 8),
            updated_at=datetime(2026, 10, 8),
        )
    )
    await session.flush()
    before_detail = await reco.card_detail(session, shop.shop_id, card_id, audience="seller")
    assert all("before_source" in s for s in before_detail["card"]["execution_sheet"]["steps"])
    assert before_detail["reverted"] is None
    await store.save_calibrations(
        session,
        shop.shop_id,
        {},
        [Observation("title", "views", 0.0, 0.1, 0.05, ref=str(card_id))],
        now=NOW,
    )

    out = await reco.mark_reverted(
        session, shop.shop_id, card_id, now=NOW, user_id=shop.user.id, note="đã sửa lại"
    )

    assert out["reverted"] is True and out["status"] == STATUS_EXECUTED
    events = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == card_id, CardEvent.event_type == EVENT_REVERTED
            )
        )
    ).all()
    assert len(events) == 1
    assert events[0].payload["by"] == f"user:{shop.user.id}" and events[0].payload["at"]
    assert events[0].payload["note"] == "đã sửa lại"
    # measurement stops: the card leaves its running change set and the set remembers why
    await session.refresh(cset)
    assert str(card_id) not in (cset.card_ids or [])
    assert str(card_id) in cset.result["reset_card_ids"]
    # learning: the card is excluded the way a reset card is
    assert str(card_id) in await store.reset_card_ids(session, shop.shop_id)
    await measure.run_learning(session, shop.shop_id, now=NOW, include_natural=False)
    refs = {o.ref for o in await store.load_observations(session, shop.shop_id)}
    assert str(card_id) not in refs
    # no read-back of the old value any more
    pending = await verification.pending_changes(session, shop.shop_id, NOW)
    assert card_id not in {c.card_id for c in pending}
    # the card page and Thực hiện say so; Đo lường no longer lists it
    detail = await reco.card_detail(session, shop.shop_id, card_id, audience="seller")
    assert detail["reverted"]["by"] == f"user:{shop.user.id}"
    states = await execution_state.execution_states(session, shop.shop_id, now=NOW)
    assert str(card_id) not in {c["card_id"] for c in states["cards"]}  # F1.4: leaves Thực hiện
    measured = await execution_state.measurement_states(session, shop.shop_id, now=NOW)
    assert str(card_id) not in {c["card_id"] for c in measured["cards"]}
    # confirmed once only
    with pytest.raises(ProposalError) as again:
        await reco.mark_reverted(session, shop.shop_id, card_id, now=NOW, user_id=shop.user.id)
    assert again.value.code == "reco_already_reverted" and again.value.status == 409
    # a card that is not executed has nothing to revert (never claim a revert that did not happen)
    other = (
        await session.scalars(select(ShopProposal).where(ShopProposal.status != STATUS_EXECUTED))
    ).first()
    if other is not None:
        with pytest.raises(ProposalError) as bad:
            await reco.mark_reverted(session, shop.shop_id, other.id, now=NOW, user_id=None)
        assert bad.value.code == "proposal_bad_state"
