"""G5 (ui-refine grill 2026-11-16): the real reason a result has no estimate, as a code plus a
short Vietnamese sentence. The UI shows "—" and the sentence on hover (Alignment 1).

Codes are stable (clients may switch on them); the sentences are the hover text. A note the
evaluators wrote for a not-estimable driver is mapped to its code by :func:`code_for_note`; the
profit reasons come from what the result itself says (:func:`profit_reason`). Pure.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: code -> the sentence a person reads. Never says "thiếu phí hoặc giá vốn" unless that is true.
REASON_TEXT: dict[str, str] = {
    # -- no estimate at all (the result carries cost and break-even only) --
    "needs_trial_run": "Chưa có số liệu để ước tính; sẽ đo sau khi chạy thử.",
    "measure_after_run": "Chưa có số liệu để ước tính; sẽ đo sau khi chạy.",
    "kol_first_sample": "Chưa ước tính được; sẽ đo sau lần gửi mẫu đầu tiên.",
    "no_keyword_data": "Chưa có dữ liệu từ khoá của sản phẩm này.",
    "no_keyword_gain": "Không thêm từ khoá nào so với hiện tại nên không có thay đổi để ước tính.",
    "combo_few_orders": "Chưa đủ đơn gần đây để đo số đơn lên mức combo.",
    "combo_no_history": "Shop chưa chạy combo nên chưa đo được số đơn mua thêm để lên mức combo.",
    "set_not_cheaper": "Chưa có set nào rẻ hơn mua lẻ nên chưa ước tính được.",
    "no_pack_evidence": "Chưa có dữ liệu bán của quy cách này.",
    "pack_already_sold": "Shop đang bán quy cách này: khách chuyển sang listing mới.",
    "followers_unknown": "Chưa biết tỉ lệ người theo dõi của shop.",
    "ads_budget_unlimited": "Chiến dịch không giới hạn ngân sách nên chưa đo được mức chi mới.",
    "ads_no_history": "Chưa có lịch sử quảng cáo ở mức này để đo.",
    "ads_no_product_rows": "Chưa có báo cáo quảng cáo theo sản phẩm để tách phần của sản phẩm.",
    "ads_no_cpa": "Chưa đo được CPA của chiến dịch hoặc sản phẩm này.",
    "ads_no_incremental": "Chưa đủ ngày có và không có quảng cáo để đo số đơn tăng thêm.",
    "ads_roas_system": "Shopee tự đặt mục tiêu ROAS nên Juli không ước tính mức chi mới.",
    "attach_few_orders": "Sản phẩm chính chưa đủ 10 đơn để ước tính mua kèm.",
    "no_driver_data": "Chưa có dữ liệu của nguồn lưu lượng này để ước tính.",
    "no_estimate": "Chưa đủ số liệu của shop để ước tính phương án này.",
    # -- profit is "—" while the rest has a figure --
    "profit_no_cost_data": (
        "Chưa tính được lợi nhuận: các đơn gần đây chưa có đủ giá vốn và phí để tính."
    ),
    "profit_cost_missing": "Chưa tính được lợi nhuận: sản phẩm chưa có giá vốn.",
    "profit_after_unknown": "Chưa tính được lợi nhuận sau thay đổi dù đã có giá vốn.",
    "profit_by_design": "Thay đổi này không tác động trực tiếp lên lợi nhuận; sẽ đo sau khi chạy.",
}

#: first matching (pattern, code) wins; patterns run on the lower-cased note
_NOTE_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), c)
    for p, c in (
        (r"chưa đủ \d+ đơn để ước tính mua kèm", "attach_few_orders"),
        (r"không thêm từ khoá", "no_keyword_gain"),
        (r"từ khoá", "no_keyword_data"),
        (r"cần chạy thử", "needs_trial_run"),
        (r"sau lần gửi mẫu", "kol_first_sample"),
        (r"đo sau khi chạy", "measure_after_run"),
        (r"chưa đủ đơn để đo số đơn lên mức combo", "combo_few_orders"),
        (r"chưa chạy combo", "combo_no_history"),
        (r"set nào rẻ hơn|phân loại nào rẻ hơn", "set_not_cheaper"),
        (r"đang bán quy cách", "pack_already_sold"),
        (r"quy cách này", "no_pack_evidence"),
        (r"người theo dõi", "followers_unknown"),
        (r"không giới hạn ngân sách", "ads_budget_unlimited"),
        (r"báo cáo quảng cáo theo sản phẩm", "ads_no_product_rows"),
        (r"chưa có lịch sử ở|chưa đo được mức chi", "ads_no_history"),
        (r"đo được cpa|chưa có chi phí và đơn", "ads_no_cpa"),
        (r"ngày có và không có quảng cáo", "ads_no_incremental"),
        (r"shopee tự đặt mục tiêu", "ads_roas_system"),
        (r"chưa có dữ liệu để đòn bẩy|chưa có dữ liệu nên không tính", "no_driver_data"),
    )
)


def code_for_note(note: str | None) -> str:
    """The reason code of a not-estimable result's note (``no_estimate`` when none matches)."""
    low = (note or "").casefold()
    for rx, code in _NOTE_RULES:
        if rx.search(low):
            return code
    return "no_estimate"


def text_for(code: str | None) -> str | None:
    """The sentence of ``code``; ``None`` for no code. An unknown code gets the general sentence."""
    if code is None:
        return None
    return REASON_TEXT.get(code, REASON_TEXT["no_estimate"])


def profit_reason(result: Mapping[str, Any] | None, *, cost_known: bool) -> str:
    """Why an estimable result has no profit figure, from what the result itself shows."""
    if not cost_known:
        return "profit_cost_missing"
    before = ((result or {}).get("detail") or {}).get("before") or {}
    if before.get("profit") is None:
        return "profit_no_cost_data"
    return "profit_after_unknown"


def reason_fields(code: str | None) -> dict[str, str | None]:
    return {"reason_code": code, "reason_text": text_for(code)}
