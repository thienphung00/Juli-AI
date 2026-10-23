"""Why a write run ended without proposing anything -- in plain Vietnamese, from the run's
own facts (fast track P66, D15).

Live run 12d703c0 ("Tạo khuyến mãi" for «Nồi lẩu…») read the candidates, found the product
already in a running price promotion, concluded without proposing, and the reviewer saw
only "Luồng đã kết thúc. Vui lòng xem lại tại Quyết định." -- no proposal, no reason.

:func:`no_proposal_reason_vi` reads the tool results the run already holds (its
conversation window, the same facts the model saw) and names the reason: the bound
product's eligibility from ``get_promotion_candidates`` (with the end date of the price
promotion already holding it), else the last refusal a tool returned (``ok: false`` and
its ``summary_vi``), else a plain "nothing to change" line. The runner emits it as the
run's last ``workflow.status`` narration, right before ``workflow.completed`` /
``workflow.failed`` (``runner/core.py``), so the run panel shows it.

Never the model's free text: the reason is built from tool outputs Juli produced.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

#: The write each workflow exists to make (a run that never reached it "did not propose").
WRITE_TOOLS_BY_WORKFLOW: Mapping[str, str] = {
    "create_promotion": "create_product_discount",
    "create_product": "create_product",
}
#: The writes a listing run (any other workflow) may propose.
LISTING_WRITE_TOOLS = frozenset(
    {"update_product_listing", "upload_product_image", "update_product_price"}
)

_CANDIDATES_TOOL = "get_promotion_candidates"


def _tool_results(window: Sequence[Mapping[str, Any]]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for message in window:
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if isinstance(content, Mapping):
            yield str(message.get("tool_name") or ""), content


def proposed_a_write(workflow_key: str, window: Sequence[Mapping[str, Any]]) -> bool:
    """Whether the run reached (asked to confirm, or made) its write."""
    writes = (
        {WRITE_TOOLS_BY_WORKFLOW[workflow_key]}
        if workflow_key in WRITE_TOOLS_BY_WORKFLOW
        else LISTING_WRITE_TOOLS
    )
    for message in window:
        call = message.get("tool_call")
        if isinstance(call, Mapping) and call.get("tool_name") in writes:
            return True
        if message.get("role") == "tool" and message.get("tool_name") in writes:
            return True
    return False


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("text")
    return " ".join(str(value or "").split())


def _dd_mm(iso_day: Any) -> str | None:
    try:
        return date.fromisoformat(str(iso_day)).strftime("%d/%m")
    except ValueError:
        return None


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _promotion_reason(content: Mapping[str, Any]) -> str | None:
    if content.get("ok") is False:
        return None
    if content.get("existing_promotions_read") is False:
        return (
            "Juli chưa đọc được các khuyến mãi đang chạy trên TikTok nên không tạo khuyến "
            "mãi mới; vui lòng thử lại sau."
        )
    source_id = str(content.get("source_product_id") or "")
    candidates = [c for c in content.get("candidates") or [] if isinstance(c, Mapping)]
    source = next((c for c in candidates if str(c.get("product_id")) == source_id), None)
    if source is None or source.get("eligible") is not False:
        return None
    name = _text(source.get("title")) or "của thẻ"
    end = _dd_mm(source.get("existing_promotion_end"))
    reason = str(source.get("reason_vi") or "")
    if end is not None or "khuyến mãi giá" in reason:
        until = f" đến {end}" if end else ""
        return (
            f"Sản phẩm «{name}» đang có khuyến mãi giá{until} — TikTok không cho chồng hai "
            "khuyến mãi giá; Juli không tạo khuyến mãi mới."
        )
    if reason:
        return f"Sản phẩm «{name}»: {reason.rstrip('.').lower()} — Juli không tạo khuyến mãi mới."
    return None


_GIVE_UP_LEAD = {
    "create_promotion": "Juli không tạo khuyến mãi",
    "create_product": "Juli không tạo sản phẩm mới",
}


def no_proposal_reason_vi(workflow_key: str, window: Sequence[Mapping[str, Any]]) -> str:
    """The reason a ``workflow_key`` run ended without proposing its write."""
    results = list(_tool_results(window))
    if workflow_key == "create_promotion":
        for tool_name, content in reversed(results):
            if tool_name == _CANDIDATES_TOOL:
                found = _promotion_reason(content)
                if found is not None:
                    return found
                break
    lead = _GIVE_UP_LEAD.get(workflow_key, "Juli không đề xuất thay đổi")
    for _, content in reversed(results):
        summary = _text(content.get("summary_vi"))
        if content.get("ok") is False and summary:
            return _sentence(f"{lead}: {summary}")
    if workflow_key == "create_promotion":
        return (
            "Juli đã đọc sản phẩm và khuyến mãi hiện có nhưng không tìm được sản phẩm đủ "
            "điều kiện cho khuyến mãi mới; TikTok không thay đổi gì."
        )
    if workflow_key == "create_product":
        return "Juli chưa đủ thông tin bắt buộc để tạo sản phẩm mới; TikTok không thay đổi gì."
    return "Juli đã đọc sản phẩm và không thấy thay đổi nào cần làm lúc này; sản phẩm giữ nguyên."


__all__ = ["no_proposal_reason_vi", "proposed_a_write"]
