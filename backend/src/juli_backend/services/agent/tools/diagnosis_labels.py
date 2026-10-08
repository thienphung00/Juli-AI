"""Short Vietnamese labels for TikTok product-diagnosis codes (AC-8.4, P8-G).

Pure data and one lookup function, no I/O. The codes are TikTok's own
(`GET /product/202405/products/diagnoses`); the VN "Rest of World" table in
`services/optimize_product/listing_signals.py` documents the known set, and
TikTok also returns codes that table omits, so the lookup falls back by
prefix and then to a generic label rather than failing on an unknown code.

The label is what the seller sees (`tool.completed.summary`) and what the
model reads beside the raw code. It never carries vendor free text.
"""

from __future__ import annotations

import re

#: Exact code -> label. Keep each label short enough for a one-line summary.
DIAGNOSIS_CODE_LABELS_VI: dict[str, str] = {
    "TITLE_LESS_THAN_40_CHARACTERS": "Tiêu đề quá ngắn",
    "SEO_DIAGNOSTIC_ITEM": "Tiêu đề chưa tối ưu từ khoá",
    "DESC_LESS_THAN_FIVE_HUNDRED_CHARS": "Mô tả quá ngắn",
    "DESC_NO_NEW_LINE": "Mô tả chưa xuống dòng",
    "DESCRIPTION_INCLUDE_INVALID_IMAGE": "Mô tả có ảnh không hợp lệ",
    "MAIN_IMG_DUPLICATE": "Ảnh chính bị trùng",
    "MAIN_IMG_NUMBER_LESS_THAN_FIVE": "Ít hơn 5 ảnh chính",
    "MAIN_IMG_FIRST_IMG_BACKGROUND_UNTIDY": "Ảnh đầu nền lộn xộn",
    "MAIN_IMG_FIRST_IMG_BLACK_BORDER": "Ảnh đầu có viền đen",
    "MAIN_IMG_FIRST_IMG_WHITE_BORDER": "Ảnh đầu có viền trắng",
    "MAIN_IMG_FIRST_IMG_FAKE_MODEL": "Ảnh đầu dùng người mẫu giả",
    "MAIN_IMG_FIRST_IMG_INCLUDE_NON_LOCAL_LANGUAGE": "Ảnh đầu có chữ ngoại ngữ",
    "MAIN_IMG_FIRST_IMG_LOW_QUALITY": "Ảnh đầu chất lượng thấp",
    "MAIN_IMG_FIRST_IMG_MISSING_PRODUCT_SUBSTANCE": "Ảnh đầu thiếu sản phẩm",
    "MAIN_IMG_FIRST_IMG_NOT_CLEAR": "Ảnh đầu không rõ nét",
    "MAIN_IMG_FIRST_IMG_PRODUCT_SUBJECT_NOT_COMPLETE": "Ảnh đầu không đủ sản phẩm",
    "MAIN_IMG_FIRST_IMG_SPLICED_PICTURE": "Ảnh đầu ghép nhiều ảnh",
    "MAIN_IMG_FIRST_IMG_TEXT_OVERLOAD": "Ảnh đầu quá nhiều chữ",
}

#: Prefix -> label, tried when the exact code is not in the table.
_PREFIX_LABELS_VI: tuple[tuple[str, str], ...] = (
    ("TITLE_", "Tiêu đề cần cải thiện"),
    ("DESCRIPTION_", "Mô tả cần cải thiện"),
    ("DESC_", "Mô tả cần cải thiện"),
    ("MAIN_IMG_", "Ảnh chính cần cải thiện"),
    ("PRICE", "Giá cần xem lại"),
)

UNKNOWN_CODE_LABEL_VI = "Vấn đề khác TikTok nêu"

#: A diagnosis code is an upper-case machine token; anything else is not
#: echoed (a vendor string that is not a code is free text, not a code).
_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,80}$")


def is_diagnosis_code(value: object) -> bool:
    return isinstance(value, str) and _CODE_PATTERN.fullmatch(value) is not None


def diagnosis_label_vi(code: str) -> str:
    """The short Vietnamese label for one diagnosis code."""
    exact = DIAGNOSIS_CODE_LABELS_VI.get(code)
    if exact is not None:
        return exact
    for prefix, label in _PREFIX_LABELS_VI:
        if code.startswith(prefix):
            return label
    return UNKNOWN_CODE_LABEL_VI
