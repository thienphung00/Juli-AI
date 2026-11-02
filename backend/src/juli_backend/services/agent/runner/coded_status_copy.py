"""Vietnamese templates for the run panel's coded status line (fast track P85, D78.2).

The copy beside ``seller_facing_copy.py``: every word the seller reads about what the
model decided comes from here, keyed by the codes ``report_status`` carries
(``coded_status.py``). The model never supplies a word of it.

Register: a third-person Juli status line (like ``agent.narration.extension_grant``),
using the decision surface's own terms -- ``decisions.reasoning`` "Lý do đề xuất" and
``decisions.estimated_impact`` "Tác động dự kiến". No Markdown, no English, no tool or
flow names. ``dictionary.md`` keys: ``agent.narration.coded_status.*``. Proven free of
the ``AGENT_OUTPUT_SCOPE`` banned patterns by ``tests/unit/test_p85_coded_narration.py``;
the tests cannot approve register or tone -- that is the owner's review.

A line never starts with "Đang chờ": the demo timeline reads that prefix as the run's
pause point.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

#: ``plan_code`` -> what Juli will do (``agent.narration.coded_status.plan.*``).
PLAN_LINES_VI: Mapping[str, str] = {
    "title": "Juli đề xuất sửa tiêu đề.",
    "description": "Juli đề xuất sửa mô tả.",
    "title_and_description": "Juli đề xuất sửa tiêu đề và mô tả.",
    "photos_needed": "Sản phẩm cần thêm ảnh; Juli không sửa tiêu đề hay mô tả.",
    "nothing_to_change": "Juli không thấy cần thay đổi gì ở trang sản phẩm.",
}

#: ``impact_code`` -> the expected effect (``agent.narration.coded_status.impact.*``);
#: ``none`` adds no sentence.
IMPACT_LINES_VI: Mapping[str, str] = {
    "fixes_flagged_issues": "Tác động dự kiến: khắc phục các điểm đã nêu.",
    "easier_to_find": "Tác động dự kiến: sản phẩm dễ được tìm thấy hơn.",
    "easier_to_read": "Tác động dự kiến: trang sản phẩm dễ đọc hơn.",
    "none": "",
}

#: ``agent.narration.coded_status.reasons`` -- the labels are ``diagnosis_labels``'
#: own Vietnamese labels, never a raw code.
REASONS_PREFIX_VI = "Lý do đề xuất:"


def _reasons(labels: Sequence[str], max_labels: int) -> str:
    unique = list(dict.fromkeys(label for label in labels if label))
    if not unique:
        return ""
    shown = ", ".join(unique[:max_labels])
    extra = len(unique) - max_labels
    more = f" và {extra} điểm khác" if extra > 0 else ""
    return f"{REASONS_PREFIX_VI} {shown}{more}."


def coded_status_line_vi(
    *, reason_labels: Sequence[str], plan_code: str, impact_code: str, max_labels: int
) -> str:
    """One status line: the plan, then the reasons Juli can back, then the impact."""
    parts = [
        PLAN_LINES_VI[plan_code],
        _reasons(reason_labels, max_labels) if plan_code != "nothing_to_change" else "",
        IMPACT_LINES_VI[impact_code],
    ]
    return " ".join(part for part in parts if part)


__all__ = [
    "IMPACT_LINES_VI",
    "PLAN_LINES_VI",
    "REASONS_PREFIX_VI",
    "coded_status_line_vi",
]
