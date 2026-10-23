"""P66 (D15): a write run that ends without proposing says why, from its own facts."""

from __future__ import annotations

from juli_backend.services.agent.no_proposal import no_proposal_reason_vi, proposed_a_write


def _tool(name: str, content: dict) -> dict:
    return {"role": "tool", "tool_call_id": "c", "tool_name": name, "content": content}


def _candidates(**source: object) -> dict:
    return _tool(
        "get_promotion_candidates",
        {
            "ok": True,
            "source_product_id": "1",
            "existing_promotions_read": True,
            "candidates": [{"product_id": "1", "title": {"text": "Nồi lẩu điện 3L"}, **source}],
        },
    )


def test_a_product_held_by_a_price_promotion_names_its_end_date():
    window = [
        _candidates(
            eligible=False,
            reason_vi="Sản phẩm đang có khuyến mãi giá khác đến 28/10/2026",
            existing_promotion_end="2026-10-28",
        )
    ]
    assert no_proposal_reason_vi("create_promotion", window) == (
        "Sản phẩm «Nồi lẩu điện 3L» đang có khuyến mãi giá đến 28/10 — TikTok không cho "
        "chồng hai khuyến mãi giá; Juli không tạo khuyến mãi mới."
    )


def test_an_out_of_stock_product_says_so():
    window = [_candidates(eligible=False, reason_vi="Sản phẩm đã hết hàng")]
    assert no_proposal_reason_vi("create_promotion", window) == (
        "Sản phẩm «Nồi lẩu điện 3L»: sản phẩm đã hết hàng — Juli không tạo khuyến mãi mới."
    )


def test_a_refused_check_is_quoted():
    window = [
        _candidates(eligible=True),
        _tool(
            "check_promotion_eligibility",
            {"ok": False, "summary_vi": "Mức giảm phải từ 5% đến 12%"},
        ),
    ]
    assert no_proposal_reason_vi("create_promotion", window) == (
        "Juli không tạo khuyến mãi: Mức giảm phải từ 5% đến 12%."
    )


def test_create_product_and_listing_runs_get_their_own_reason():
    refused = [
        _tool(
            "check_listing_requirements", {"ok": False, "summary_vi": "Thiếu thuộc tính bắt buộc"}
        )
    ]
    assert no_proposal_reason_vi("create_product", refused) == (
        "Juli không tạo sản phẩm mới: Thiếu thuộc tính bắt buộc."
    )
    assert no_proposal_reason_vi("optimize_product_2", []) == (
        "Juli đã đọc sản phẩm và không thấy thay đổi nào cần làm lúc này; sản phẩm giữ nguyên."
    )


def test_a_proposed_write_is_detected_from_the_call_or_its_result():
    call = {"role": "assistant", "tool_call": {"tool_name": "create_product_discount"}}
    assert proposed_a_write("create_promotion", [call])
    assert not proposed_a_write("create_promotion", [_candidates(eligible=True)])
    assert proposed_a_write("optimize_product_2", [_tool("update_product_listing", {})])
