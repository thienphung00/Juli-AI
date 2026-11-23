"""batch-1123-a2 Track S: K1 ids vs typed codes, the combo read-back, the read-back compare
(S-E110), the card's current job (K3 / K4) and the combo's minutes. Pure: synthetic data."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from juli_backend.models.shopee_fill import ShopeeFillJob
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import (
    fill_queue,
    fill_refs,
    job_view,
    readback_compare,
    revert_fill,
)
from juli_backend.services.shopee_recommendations.kinds import FAMILY_LABELS

NOW = datetime(2026, 11, 23, 3, 0, tzinfo=UTC)


def _job(kind, key="x", status="queued", payload=None, seq=1, version=1, target=None):
    return ShopeeFillJob(
        id=uuid.uuid4(), proposal_id=uuid.uuid4(), kind=kind, target=target or {},
        target_key=key, seq=seq, version=version, payload=payload or {}, status=status,
        created_at=datetime(2026, 11, 23), updated_at=datetime(2026, 11, 23),
    )  # fmt: skip


# ------------------------------------------------------------------------------- K1


def test_a_typed_value_is_an_id_only_when_it_is_all_digits():
    assert fill_refs.split_ref("1234567") == ("1234567", None)
    assert fill_refs.split_ref(" oryvab12c ") == (None, "ORYVAB12C")
    assert fill_refs.split_ref("") == (None, None)


def test_a_voucher_code_target_keeps_the_full_code_and_the_suffix_without_the_shop_prefix():
    t = fill_refs.voucher_target(None, "ORYVAB12C", "Tên")
    assert t == {"voucher_code": "ORYVAB12C", "code_suffix": "AB12C", "code": "ORYVAB12C"}
    assert "voucher_id" not in t
    assert fill_refs.voucher_target("77", "ORYVAB12C", None) == {"voucher_id": "77"}
    assert fill_refs.voucher_suffix("AB12C") == "AB12C"  # already without the prefix


def test_combo_and_programme_targets_use_the_id_else_the_name():
    assert fill_refs.object_target("combo_id", "combo_name", "9", "A") == {"combo_id": "9"}
    assert fill_refs.object_target("combo_id", "combo_name", None, "Combo A") == {
        "combo_name": "Combo A"
    }
    assert fill_refs.object_target("id", "name", None, "Chương trình") == {"name": "Chương trình"}


def test_the_voucher_undo_never_puts_a_code_in_voucher_id():
    fwd = _job("voucher", payload={"name": "V", "code_suffix": "AB12C"})
    spec = revert_fill._revert_spec(fwd, {}, "ORYVAB12C")
    assert spec["error"] is None
    assert "voucher_id" not in spec["payload"] and spec["payload"]["code"] == "ORYVAB12C"
    assert spec["target"]["voucher_code"] == "ORYVAB12C"
    by_id = revert_fill._revert_spec(fwd, {}, "555")
    assert by_id["payload"]["voucher_id"] == "555" and by_id["target"] == {"voucher_id": "555"}


def test_the_combo_undo_ignores_a_non_numeric_captured_ref_and_falls_back_to_the_name():
    fwd = _job("combo", payload={"name": "Combo A"})
    fwd.captured_ref = "not-a-number"
    spec = revert_fill._revert_spec(fwd, {})
    assert spec["target"] == {"name": "Combo A"} and "combo_id" not in spec["payload"]


# --------------------------------------------------------------------------- S-E118


def test_a_voucher_without_an_id_is_read_back_by_its_code_then_its_name():
    by_code = revert_fill._readback_of_change(
        "voucher", {"voucher_code": "ORYVAB12C", "code_suffix": "AB12C"}
    )
    assert by_code["key"] == "readback:voucher:ORYVAB12C"
    assert by_code["target"]["code_suffix"] == "AB12C"
    by_name = revert_fill._readback_of_change("voucher", {"name": "Tên mã"})
    assert by_name["key"] == "readback:voucher:Tên mã"
    assert revert_fill._readback_of_change("voucher", {}) is None


def test_a_combo_and_a_programme_have_no_readback_job_but_keep_their_k1_target():
    for kind in ("bundle_deal", "product_discount", "flash_sale", "add_on", "gift"):
        assert revert_fill._readback_of_change(kind, {"combo_id": "9", "name": "x"}) is None


def test_a_saved_combo_or_programme_says_it_was_not_read_back():
    for kind in ("combo", "product_discount", "add_on"):
        saved = job_view.view(_job(kind, status="saved"), {})
        assert saved["status_label"] == "Đã lưu trên Shopee · chưa đọc lại"
        assert saved["readback"] == {"result": None, "diffs": []}
        done = job_view.view(_job(kind, status="filled"), {}, executed=True)
        assert done["status_label"] == "Đã lưu trên Shopee · chưa đọc lại"
    assert job_view.view(_job("combo", status="filled"), {})["status_label"] == (
        "Đã điền · chờ bạn lưu"
    )
    assert job_view.view(_job("voucher", status="saved"), {})["status_label"] == (
        "Đã lưu · chờ xác minh"
    )  # a voucher keeps its read-back


# --------------------------------------------------------------------------- S-E110


def _voucher_payload(**kw):
    base = {
        "starts_at": "00:00 01-03-2027", "ends_at": "23:59 07-03-2027",
        "discount": {"type": "percent", "value": 10}, "min_spend": 100000, "usage_total": 50,
        "product_ids": ["1", "2"],
    }  # fmt: skip
    return {**base, **kw}


def _promo(**kw):
    extra = {
        "discount_percent": 10, "min_spend": 100000, "usage_limit": 50, "product_count": 2,
        **kw.pop("extra", {}),
    }  # fmt: skip
    return SimpleNamespace(
        starts_at=kw.pop("starts_at", datetime(2027, 3, 1, 0, 0)),
        ends_at=kw.pop("ends_at", datetime(2027, 3, 7, 23, 59)),
        extra=extra,
    )


def test_a_voucher_that_matches_the_card_is_a_match():
    got = readback_compare.compare(
        readback_compare.expected_of("voucher", _voucher_payload()),
        readback_compare.observed_of("voucher", _promo()),
    )
    assert got == {"result": "match", "diffs": []}


def test_a_start_date_typed_as_03_01_instead_of_01_03_is_a_mismatch_on_thoi_gian():
    seen = _promo(starts_at=datetime(2027, 1, 3, 0, 0))  # 03/01/2027, the card says 01/03/2027
    got = readback_compare.compare(
        readback_compare.expected_of("voucher", _voucher_payload()),
        readback_compare.observed_of("voucher", seen),
    )
    assert got["result"] == "mismatch"
    (diff,) = got["diffs"]
    assert diff["label_vi"] == "Thời gian" and diff["field"] == "time"
    assert "01/03/2027" in diff["card_value"] and "03/01/2027" in diff["seen_value"]
    assert set(diff) == {"field", "label_vi", "card_value", "seen_value"}


def test_amount_min_order_uses_and_product_count_are_compared_too():
    seen = _promo(extra={"min_spend": 50000, "usage_limit": 10, "product_count": 3})
    got = readback_compare.compare(
        readback_compare.expected_of("voucher", _voucher_payload()),
        readback_compare.observed_of("voucher", seen),
    )
    assert [d["label_vi"] for d in got["diffs"]] == [
        "Đơn tối thiểu", "Lượt sử dụng tối đa", "Số sản phẩm",
    ]  # fmt: skip


def test_a_field_the_list_does_not_show_is_never_a_mismatch_and_nothing_read_is_none():
    bare = SimpleNamespace(starts_at=datetime(2027, 3, 1), ends_at=None, extra={})
    got = readback_compare.compare(
        readback_compare.expected_of("voucher", _voucher_payload()),
        readback_compare.observed_of("voucher", bare),
    )
    assert got == {"result": "match", "diffs": []}  # only the start was shown, and it agrees
    assert readback_compare.compare({"time": (None, None)}, {})["result"] is None


def test_combo_tiers_and_dates_are_compared_with_the_minutes_of_the_card():
    payload = {
        "starts_at": "09:30 01-03-2027", "ends_at": "21:15 07-03-2027", "discount_type": "pct",
        "tiers": [{"qty": 2, "value": 5}, {"qty": 3, "value": 10}], "product_ids": ["1"],
    }  # fmt: skip
    seen = SimpleNamespace(
        starts_at=datetime(2027, 3, 1, 9, 30),
        ends_at=datetime(2027, 3, 7, 21, 15),
        extra={"discount_type": "pct", "tiers": [{"qty": 3, "value": 10}, {"qty": 2, "value": 5}]},
    )
    want = readback_compare.expected_of("combo", payload)
    assert (
        readback_compare.compare(want, readback_compare.observed_of("combo", seen))["result"]
        == "match"
    )
    off = SimpleNamespace(
        starts_at=datetime(2027, 3, 1, 9, 0), ends_at=seen.ends_at, extra=seen.extra
    )
    got = readback_compare.compare(want, readback_compare.observed_of("combo", off))
    assert [d["label_vi"] for d in got["diffs"]] == ["Thời gian"]


# ------------------------------------------------------------------- K3 / K4 job view


def test_status_words_follow_the_job_status_and_the_read_back_result():
    f = job_view.status_label
    assert f("forward", "queued", None) == "Chờ điền" == f("forward", "opened", None)
    assert f("forward", "filled", None) == "Đã điền · chờ bạn lưu"
    assert f("forward", "saved", None) == "Đã lưu · chờ xác minh"
    assert f("readback", "captured", "match") == "Khớp"
    assert f("readback", "captured", "mismatch") == "Lệch"
    assert f("readback", "queued", None) == "Đã lưu · chờ xác minh"


def test_a_saved_combo_never_reads_0_of_8():
    j = _job("combo", status="saved", payload={"progress": {"filled": 0, "total": 8}})
    v = job_view.view(j, {})
    assert (v["filled"], v["total"]) == (8, 8) and v["status_label"] == (
        "Đã lưu trên Shopee · chưa đọc lại"
    )
    queued = job_view.view(_job("combo", payload={"progress": {"filled": 2, "total": 8}}), {})
    assert (queued["filled"], queued["total"]) == (2, 8)


def test_the_undo_job_wins_over_a_finished_forward_job_and_has_its_own_page():
    fwd = _job("voucher", key="voucher:1", status="captured", payload={"open_path": "/new"})
    undo = _job(
        "voucher_end", key="revert:voucher:1", seq=2,
        payload={"open_path": "/portal/marketing/vouchers/list"},
    )  # fmt: skip
    got = job_view.pick([fwd, undo])
    assert got is undo
    v = job_view.view(got, {})
    assert v["role"] == "revert" and v["kind"] == "voucher_end"
    assert v["open_path"] == "/portal/marketing/vouchers/list"
    assert set(v) == {
        "job_id", "role", "kind", "status", "status_label", "open_path", "filled", "total",
        "readback",
    }  # fmt: skip
    assert v["readback"] == {"result": None, "diffs": []}


def test_a_finished_forward_job_with_a_readback_shows_the_readback_job():
    fwd = _job("voucher", key="voucher:1", status="saved")
    back = _job("readback", key="readback:voucher:1", seq=2, status="captured")
    assert job_view.pick([fwd, back]) is back
    assert job_view.pick([_job("combo", key="combo:1", status="filled")]).status == "filled"
    cancelled = _job("combo", status="cancelled")
    assert job_view.pick([cancelled]) is None


# ------------------------------------------------------------------ minutes and labels


def _combo(**kw):
    base = {
        "kind": "combo", "item_ids": ["1"], "discount_type": "pct",
        "tiers": [{"qty": 2, "value": 5}], "start": date(2027, 3, 1), "end": date(2027, 3, 2),
    }  # fmt: skip
    return sp.ComboSpec(**{**base, **kw})


def test_a_combo_keeps_its_minutes_and_the_fill_window_uses_them():
    spec = _combo(start_hour=9, start_minute=30, end_hour=21, end_minute=15)
    assert (spec.start_minute, spec.end_minute) == (30, 15)
    inputs = {
        "start": "2027-03-01", "end": "2027-03-02", "start_hour": 9, "start_minute": 30,
        "end_hour": 21, "end_minute": 15,
    }  # fmt: skip
    assert fill_queue._combo_window(inputs, NOW) == ("09:30 01-03-2027", "21:15 02-03-2027")
    # no hours: the whole days as before
    assert fill_queue._combo_window({"start": "2027-03-01", "end": "2027-03-02"}, NOW) == (
        "00:00 01-03-2027",
        "23:59 02-03-2027",
    )


def test_a_combo_minute_needs_its_hour_and_the_end_must_follow_the_start():
    with pytest.raises(ValidationError):
        _combo(start_minute=30)
    with pytest.raises(ValidationError):
        _combo(start=date(2027, 3, 1), end=date(2027, 3, 1), start_hour=9, start_minute=45,
               end_hour=9, end_minute=30)  # fmt: skip
    ok = _combo(start=date(2027, 3, 1), end=date(2027, 3, 1), start_hour=9, start_minute=0,
                end_hour=9, end_minute=45)  # fmt: skip
    assert ok.minutes == 45


def test_the_card_header_uses_shopees_names():
    assert FAMILY_LABELS["voucher"] == "Mã Giảm Giá"
    assert FAMILY_LABELS["combo"] == "Combo Khuyến Mãi"
    assert FAMILY_LABELS["sale"] == "Flash Sale Của Shop"


async def test_product_names_line_up_with_product_ids_in_voucher_and_combo_jobs(monkeypatch):
    async def fake(session, shop_id, ids):
        known = {"1001": "Găng tay", "1003": "Hộp 3"}
        return [known.get(i) for i in ids]

    monkeypatch.setattr(fill_queue, "product_names_of", fake)
    jobs = [
        {"kind": "voucher", "payload": {"product_ids": ["1001", "1002", "1003"]}},
        {"kind": "combo", "payload": {"product_ids": ["1003"]}},
        {"kind": "voucher", "payload": {"product_ids": []}},  # a shop voucher: nothing to name
    ]
    await fill_queue._add_product_names(None, uuid.uuid4(), jobs)
    first, second, shop_wide = (j["payload"] for j in jobs)
    assert first["product_names"] == ["Găng tay", None, "Hộp 3"]
    assert len(first["product_names"]) == len(first["product_ids"])
    assert second["product_names"] == ["Hộp 3"]
    assert "product_names" not in shop_wide


async def test_without_a_session_every_name_is_unknown_but_the_arrays_still_line_up():
    assert await fill_queue.product_names_of(None, uuid.uuid4(), ["1", "2"]) == [None, None]
