"""G5: a no-estimate result carries the real reason code and its sentence."""

from __future__ import annotations

from decimal import Decimal as D

from juli_backend.services.shopee_builder import reasons
from juli_backend.services.shopee_builder.engine_families import common

NOTES = {
    common.NOTE_ADS_NOT_ESTIMABLE: "needs_trial_run",
    common.NOTE_NO_KEYWORD_DATA: "no_keyword_data",
    common.NOTE_NO_GAIN: "no_keyword_gain",
    common.NOTE_MEASURE_AFTER: "measure_after_run",
    common.NOTE_KOL_NOT_ESTIMABLE: "kol_first_sample",
    common.NOTE_NO_PACK_EVIDENCE: "no_pack_evidence",
    common.NOTE_FOLLOWER: "followers_unknown",
    common.NOTE_COMBO_REACH: "combo_few_orders",
    common.NOTE_COMBO_NO_HISTORY: "combo_no_history",
    common.NOTE_SET_NOT_CHEAPER: "set_not_cheaper",
    common.NOTE_PACK_SOLD: "pack_already_sold",
}


def test_every_family_note_maps_to_its_code() -> None:
    for note, code in NOTES.items():
        assert reasons.code_for_note(note) == code
        assert reasons.text_for(code)


def test_unknown_note_gets_the_general_code() -> None:
    assert reasons.code_for_note(None) == "no_estimate"
    assert reasons.code_for_note("???") == "no_estimate"
    assert reasons.text_for(None) is None


def test_profit_reason_is_the_real_one_when_costs_exist() -> None:
    no_orders = {"detail": {"before": {"profit": None}}}
    assert reasons.profit_reason(no_orders, cost_known=True) == "profit_no_cost_data"
    known = {"detail": {"before": {"profit": 100.0}}}
    assert reasons.profit_reason(known, cost_known=True) == "profit_after_unknown"
    assert reasons.profit_reason(known, cost_known=False) == "profit_cost_missing"
    for code in ("profit_no_cost_data", "profit_after_unknown"):
        assert "thiếu phí hoặc giá vốn" not in (reasons.text_for(code) or "")


def test_texts_are_short_and_complete() -> None:
    for code, text in reasons.REASON_TEXT.items():
        assert text.strip() and len(text) <= 100, code


def test_g8_discount_given_replaces_the_no_extra_cost_line() -> None:
    from juli_backend.services.shopee_builder.outcome import with_discount_given

    result = {"cost": {"total": 0.0, "text": "Không có chi phí thêm · hoà vốn khi thêm ≥ 3 đơn"}}
    card = {"change_kind": "flash_sale", "certain": {"discount_given": 120_000}}
    out, info = with_discount_given(result, card)
    assert out is not None and info is not None
    assert out["cost"]["text"] == "Tiền giảm cho khách ~120.000 đ · hoà vốn khi thêm ≥ 3 đơn"
    assert info == {"amount": 120_000, "text": "Tiền giảm cho khách ~120.000 đ"}
    same, none = with_discount_given(result, {"change_kind": "price", "certain": {}})
    assert same == result and none is None


def test_g7_price_display_default_is_per_measure_or_empty() -> None:
    from juli_backend.services.shopee_profit.pack import price_per_measure

    per, label = price_per_measure(D(50_000), 1, "Nước rửa chén 500ml") or (None, None)
    assert per == D(10_000) and label == "100 ml"
    kilo = price_per_measure(D(90_000), 1, "Hạt 1kg")
    assert kilo is not None and kilo[0] == D(9_000) and kilo[1] == "100 g"
    assert price_per_measure(D(90_000), 1, "Găng tay Size M") is None
