"""F8 t1: the Kế hoạch export reads F7 data (card forecast + running measurement) per metric.
Made-up figures; pure functions of ``exports.collect``."""

from __future__ import annotations

from datetime import date

import pytest

from juli_backend.services.exports import collect
from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.shopee_recommendations import execution_state


def _forecast() -> dict:
    block = {"hien_tai": 1_000.0, "du_kien": 1_400.0}
    return {
        "metrics": {
            "profit": block,
            "gmv": {"hien_tai": 10_000.0, "du_kien": 12_000.0},
            "orders": {"hien_tai": 100.0, "du_kien": 120.0},
            "aov": {"hien_tai": 100.0, "du_kien": 101.0},
        }
    }


def _actual(k: int, n: int) -> dict:
    m = {
        "profit": {"thuc_te": 500.0, "delta": 150.0},
        "gmv": {"thuc_te": 5_500.0, "delta": 500.0},
        "orders": {"thuc_te": 55.0},
        "aov": {"thuc_te": None},
    }
    return {"metrics": m, "days_measured": k, "days": n}


def _row(code: str, ref: str | None = None) -> kh.CardRow:
    return kh.CardRow(
        code=code, plan_code="KH-1", status=kh.MEASURING, group="Ưu đãi", kind="Voucher",
        version=None, product_id=None, product_name=None, metrics=None,
        start=date(2026, 11, 1), end=date(2026, 11, 14), external_ref=ref,
    )  # fmt: skip


def test_measured_card_prorates_additive_metrics_to_the_measured_days():
    figs = collect.figures_of(_forecast(), _actual(7, 14))
    assert figs["profit"] == (500.0, 700.0, 500.0)  # hiện tại / dự kiến over 7 of 14 days
    assert figs["gmv"] == (5_000.0, 6_000.0, 5_500.0)
    assert figs["aov"] == (100.0, 101.0, None)  # not additive, thực tế unknown -> None


def test_unmeasured_card_has_no_thuc_te_and_a_card_without_estimate_is_all_none():
    figs = collect.figures_of(_forecast(), None)
    assert figs["profit"] == (1_000.0, 1_400.0, None)
    blank = collect.figures_of({}, None)
    assert set(blank) == {"profit", "gmv", "orders", "aov"}
    assert all(v == (None, None, None) for v in blank.values())


def test_grouped_pair_shows_the_other_cards_ma_goc_else_its_code():
    a, b = _row("A-1"), _row("B-2", ref="VC-P9")
    a.figures = collect.figures_of(_forecast(), None)
    measure = {
        "actual": _actual(14, 14), "measured_with": ["B-2", "C-3"],
        "verdict": execution_state.VERDICT_INSIDE,
    }  # fmt: skip
    collect._apply_measure(a, measure, {"B-2": b.external_ref, "C-3": None})
    assert a.measured_with == ["VC-P9", "C-3"]
    assert (a.days_measured, a.days_total, a.conclusion) == (14, 14, "Trong khoảng")
    assert a.actual_profit == 150.0
    assert a.figures["profit"] == (1_000.0, 1_400.0, 500.0)


def test_ads_card_reading_fills_cpa_roas_and_break_even_never_zero():
    own = {"option": {"ads": {
        "cpa": {"after": 20_000}, "roas_shopee": {"after": 4.0}, "break_even_cpa": 25_000,
    }}, "certain": {"break_even_roas": 3.2}}  # fmt: skip
    card = {
        "ads_readback": {"state": "read", "actual": {"spend": 90_000, "orders": 5, "roas": 4.5}}
    }
    got = collect.ads_tailored(card, own)
    assert got["CPA"] == (20_000.0, 18_000.0) and got["ROAS"] == (4.0, 4.5)
    assert got["CPA hoà vốn"] == (25_000.0, None) and got["ROAS hoà vốn"] == (3.2, None)
    assert collect.ads_tailored({}, {}) == {}
    empty = collect.ads_tailored({"ads_readback": {"state": "not_read"}}, {"option": {"ads": {}}})
    assert all(v == (None, None) for v in empty.values())


def test_card_without_an_estimate_exports_empty_cells_and_a_live_formula():
    row = _row("N-1")
    row.figures = collect.figures_of({}, None)
    data = kh.KeHoachData(date(2026, 11, 1), date(2026, 11, 30), ["Shop A"], [row])
    ws = kh.build(data)[kh.SHEET_HISTORY]
    assert [ws.cell(4, c).value for c in (16, 17, 18)] == [None, None, None]
    assert ws["S4"].value == '=IF(OR(Q4="",R4=""),"",R4-Q4)'
    assert ws.cell(4, 34).value is None  # Đã đo, one column after Loại dự kiến
    with pytest.raises(KeyError) as exc:
        kh.build(data)["Quảng cáo"]
    assert "Quảng cáo" in str(exc.value)


def _history_col(ws, title: str) -> int:
    head = [c.value for c in ws[3]]
    return head.index(title) + 1


def test_history_and_kind_sheets_print_the_forecast_type_once():
    """Batch 2 row IF: the Excel column prints "ước tính" / "dữ liệu shop" / "Juli".

    The type sits beside the amounts, once per card. Nguồn stays the card's origin.
    A missing type and any other word are an empty cell.
    """
    shop = _row("A-1")
    shop.source = "Tự tạo"
    shop.prediction_type = "dữ liệu shop"
    shop.figures = {"profit": (1000.0, 1400.0, None)}
    shop.kind_key, shop.family = "min_spend_voucher", "voucher"
    prior = _row("B-2")
    prior.prediction_type = "ước tính"
    prior.figures = {"profit": (1.0, 1.0, None)}
    prior.kind_key, prior.family = "min_spend_voucher", "voucher"
    blank = _row("C-3")
    blank.prediction_type = "pooled"  # not one of the three words
    blank.figures = {"profit": (1.0, 1.0, None)}
    blank.kind_key, blank.family = "min_spend_voucher", "voucher"
    data = kh.KeHoachData(date(2026, 11, 1), date(2026, 11, 30), ["Shop A"], [shop, prior, blank])
    wb = kh.build(data)
    for name in (kh.SHEET_HISTORY, "Voucher"):
        ws = wb[name]
        head = [c.value for c in ws[3]]
        assert head.count("Loại dự kiến") == 1
        assert head[head.index("Loại dự kiến") - 1] == "AOV chênh lệch"
        assert head[head.index("Loại dự kiến") + 1] == "Chi phí"
        col = _history_col(ws, "Loại dự kiến")
        assert [ws.cell(r, col).value for r in (4, 5, 6)] == ["dữ liệu shop", "ước tính", None]
    history = wb[kh.SHEET_HISTORY]
    assert history.cell(4, _history_col(history, "Nguồn")).value == "Tự tạo"


def test_card_row_reads_the_forecast_type_and_keeps_it_when_measured():
    card = {
        "code": "A-1",
        "change_kind": "min_spend_voucher",
        "family": "voucher",
        "origin": "manual",
        "forecast": {"prediction_type": "Juli", "metrics": _forecast()["metrics"]},
    }
    row = collect._card_row(
        card, "KH-1", kh.MEASURING, None, {}, shop="Shop A", platform="Shopee", proposed=None
    )
    assert row.source == "Tự tạo"
    assert row.prediction_type == "Juli"
    collect._apply_measure(
        row,
        {"actual": _actual(14, 14), "measured_with": [], "verdict": execution_state.VERDICT_INSIDE},
        {},
    )
    assert row.prediction_type == "Juli"
    assert row.figures["profit"][2] == 500.0

    unknown = {**card, "forecast": {"prediction_type": "pooled", "metrics": {}}}
    assert (
        collect._card_row(
            unknown, None, kh.DRAFT, None, {}, shop="Shop A", platform="Shopee", proposed=None
        ).prediction_type
        is None
    )
    missing = {**card, "forecast": {"metrics": {}}}
    assert (
        collect._card_row(
            missing, None, kh.DRAFT, None, {}, shop="Shop A", platform="Shopee", proposed=None
        ).prediction_type
        is None
    )
