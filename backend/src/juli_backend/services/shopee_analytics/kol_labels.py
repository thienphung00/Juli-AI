"""Display labels for the affiliate line's ``channel`` and ``campaign_type`` (P100, 2026-11-13).

Both fields hold what the Juli Connector posted from Shopee's affiliate conversion report:

- ``channel``: the order's ``traffic_type``. Older posts carry the code (``"0"`` = outside Shopee:
  Facebook, Zalo, Chia sẻ mã, websites, others; ``"1"`` = inside Shopee, Video or Live; ``"2"`` =
  not confirmed, assumed inside-Shopee Live). Newer posts carry the report's own text
  (``"Shopeevideo"``, ``"Facebook"``, ``"Code Sharing"`` ...). Both are labelled; anything else
  (an order-export text such as ``"TikTok"``) is shown as it came.
- ``campaign_type``: a code; ``"5"`` = Seller Open Campaign (Chiến dịch mở). Text (the order
  export's ``Loại chiến dịch``) is shown as it came; an unknown code reads "Loại chiến dịch {code}".

Pure; the raw values stay in every payload beside the labels.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

#: legacy ``traffic_type`` codes
CHANNEL_CODES: dict[str, str] = {
    "0": "Ngoài Shopee (chưa rõ kênh)",
    "1": "Trong Shopee (Video/Live)",
    "2": "Trong Shopee (Live)",
}
#: the report's own channel texts, matched without case, spaces, ``_`` or ``-``
CHANNEL_TEXTS: dict[str, str] = {
    "shopeevideo": "Shopee Video",
    "shopeelive": "Shopee Live",
    "facebook": "Facebook",
    "zalo": "Zalo",
    "codesharing": "Chia sẻ mã",
    "website": "Website",
    "websites": "Website",
    "other": "Khác",
    "others": "Khác",
}
CAMPAIGN_CODES: dict[str, str] = {"5": "Chiến dịch mở"}
NO_CAMPAIGN_TYPE = "Không rõ loại chiến dịch"

_FOLD = re.compile(r"[\s_\-]+")


def _fold(text: str) -> str:
    return _FOLD.sub("", text.casefold())


def channel_label(raw: str | None) -> str | None:
    """The seller's word for a channel value: legacy code, known report text, else as is."""
    if raw is None:
        return None
    value = raw.strip()
    if value in CHANNEL_CODES:
        return CHANNEL_CODES[value]
    return CHANNEL_TEXTS.get(_fold(value), raw)


def campaign_type_label(raw: str | None) -> str | None:
    """The seller's word for a campaign type: known code, unknown code, else the text as is."""
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if value in CAMPAIGN_CODES:
        return CAMPAIGN_CODES[value]
    if value.isdigit():
        return f"Loại chiến dịch {value}"
    return raw


def options(
    values: Iterable[str | None], fn: Callable[[str | None], str | None]
) -> list[dict[str, str | None]]:
    """``[{value, label}]`` of the distinct raw values, sorted by label then value."""
    return [
        {"value": v, "label": fn(v)}
        for v in sorted(set(values), key=lambda v: ((fn(v) or "").casefold(), v or ""))
    ]
