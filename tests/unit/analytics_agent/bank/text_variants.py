"""How sellers write each dimension value, for the PAID set only (the free bank gives the parse,
so it cannot test the parser): per value, the Vietnamese words with accents, without accents,
with a typo, mixed with English, and in seller shorthand. The table is generated from the
dimension tables and the registry's Vietnamese labels (`write_table`) and committed as
`text_variants.json`; edit the JSON to add a seller's real wording (paraphrased)."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from juli_backend.services.metrics.registry import METRICS as REGISTRY
from tests.unit.analytics_agent.bank import dimensions as D

TABLE_FILE = Path(__file__).parent / "text_variants.json"
KINDS = ("accent", "no_accent", "typo", "english_mix", "shorthand")

PERIOD_VI = {
    "yesterday": ("hôm qua", "yesterday"),
    "this_week": ("tuần này", "this week"),
    "last_week": ("tuần trước", "last week"),
    "this_vs_last_week": ("tuần này so với tuần trước", "this week vs last week"),
    "7d": ("7 ngày qua", "last 7 days"),
    "14d": ("14 ngày qua", "last 14 days"),
    "30d": ("30 ngày qua", "last 30 days"),
    "90d": ("90 ngày qua", "last 90 days"),
    "this_month": ("tháng này", "this month"),
    "last_month": ("tháng trước", "last month"),
    "named_finished": ("tháng 9", "September"),
    "named_unfinished": ("tháng 10", "October"),
    "named_not_started": ("tháng 11", "November"),
    "explicit_range": ("từ 2/10 đến 5/10", "from 2/10 to 5/10"),
    "single_date": ("ngày 3/10", "on 3/10"),
    "sale_day": ("ngày 25/9", "on 25/9 sale day"),
    "none": ("", ""),
}
SCOPE_VI = {
    "shop": ("cả shop", "whole shop"),
    "product_name": ("găng tay", "găng tay product"),
    "product_id": ("sản phẩm 1002", "item 1002"),
    "product_sku": ("mã T1", "SKU T1"),
    "voucher": ("đơn dùng voucher", "voucher orders"),
    "affiliate": ("tiếp thị liên kết", "affiliate"),
    "kol": ("KOL", "KOL"),
    "campaign": ("chiến dịch quảng cáo", "ad campaign"),
    "combo": ("combo khuyến mãi", "combo deal"),
    "add_on": ("mua kèm deal sốc", "add-on deal"),
    "flash_sale": ("flash sale của shop", "shop flash sale"),
    "programme": ("chương trình của shop", "shop programme"),
    "gift": ("mua để nhận quà", "gift with purchase"),
    "channel_organic": ("tự nhiên (organic)", "organic"),
    "channel_ads": ("từ quảng cáo", "from ads"),
    "dvht_product": ("dịch vụ hiển thị sản phẩm", "DVHT product ads"),
    "dvht_shop": ("dịch vụ hiển thị shop+", "DVHT Shop+ ads"),
    "ads_live": ("quảng cáo livestream", "livestream ads"),
    "ads_other": ("quảng cáo khác", "other ads"),
}
OUTPUT_VI = {
    "value": ("bao nhiêu", "how much"),
    "comparison": ("so với kỳ trước thế nào", "vs before"),
    "top": ("sản phẩm nào cao nhất", "top products"),
    "decline": ("sản phẩm nào giảm mạnh nhất", "biggest drop"),
    "breakdown": ("theo từng kênh", "by channel"),
    "trend": ("theo từng ngày", "per day"),
    "why": ("vì sao thay đổi", "why changed"),
    "verdict": ("đang lãi hay lỗ", "profit or loss"),
}
SHORT = (
    ("doanh thu", "dt"),
    ("đơn hàng", "đh"),
    ("quảng cáo", "qc"),
    ("sản phẩm", "sp"),
    ("lợi nhuận", "ln"),
    ("tuần trước", "tuần trc"),
    ("không", "ko"),
    ("bao nhiêu", "bn"),
    ("tiếp thị liên kết", "ttlk"),
    ("chi phí", "cp"),
    ("được", "dc"),
    ("ngày", "ng"),
)


def fold(text: str) -> str:
    """The words without accents ("đơn hàng" -> "don hang")."""
    d = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def typo(text: str) -> str:
    """One deterministic slip per longer word: the last letter doubled."""
    return " ".join(w + w[-1] if len(w) > 3 and w.isalpha() else w for w in text.split())


def shorthand(text: str) -> str:
    out = text
    for long, short in SHORT:
        out = out.replace(long, short)
    return out


def variants(vi: str, en: str) -> dict[str, str]:
    words = vi.split()
    mixed = " ".join([*words[: max(1, len(words) // 2)], en]) if vi else en
    return {
        "accent": vi,
        "no_accent": fold(vi),
        "typo": typo(vi),
        "english_mix": mixed.strip(),
        "shorthand": shorthand(vi),
    }


def _metric_vi(key: str) -> tuple[str, str]:
    if key == "none":
        return ("số liệu", "numbers")
    label = REGISTRY[key].label_vi
    return (label.lower() if label else key, D.phrase_of(key) or key)


def build_table() -> dict[str, dict[str, dict[str, str]]]:
    table: dict[str, dict[str, dict[str, str]]] = {
        "period": {k: variants(*v) for k, v in PERIOD_VI.items()},
        "scope": {k: variants(*v) for k, v in SCOPE_VI.items()},
        "metric": {k: variants(*_metric_vi(k)) for k in D.metric_ids()},
        "output": {k: variants(*v) for k, v in OUTPUT_VI.items()},
        "card_type": {
            k: variants(f"tạo thẻ {k.replace('_', ' ')}", f"create {k} card") for k in D.CARD_TYPES
        },
        "goal": {
            k: variants(f"nên làm gì ({k.replace('_', ' ')})", f"what to do {k}") for k in D.GOALS
        },
    }
    return table


def write_table() -> None:
    TABLE_FILE.write_text(
        json.dumps(build_table(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def load_table() -> dict[str, Any]:
    return dict(json.loads(TABLE_FILE.read_text(encoding="utf-8")))


def question(dims: dict[str, Any], kind: str, table: dict[str, Any] | None = None) -> str:
    """A seller's question for a data combination, in one text variant."""
    t = table or load_table()
    parts = [
        t["metric"][dims["metric"]][kind],
        t["scope"][dims["scope"]][kind],
        t["period"][dims["period"]][kind],
        t["output"][dims["output"]][kind],
    ]
    return " ".join(p for p in parts if p).strip() + "?"


if __name__ == "__main__":
    write_table()
