"""Vietnamese template copy of the content cards and runs (contract §1, §2.1).

Templates only — no model writes any of this (D24.1, D24.3). Numbers come from
the ranking rows; nothing here invents one.
"""

from __future__ import annotations

from collections.abc import Sequence

from juli_backend.services.content_cards.candidates import ContentCandidate, EvidenceRow
from juli_backend.services.content_cards.constants import VIDEO, ContentKind


def pct(value: float | None, digits: int = 1) -> str:
    """0.019 → "1,9 %"."""
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}".replace(".", ",") + " %"


def compact(value: float) -> str:
    """118_400 → "118k", 1_250_000 → "1,3 tr"."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".replace(".", ",").removesuffix(",0") + " tr"
    if value >= 1_000:
        return f"{round(value / 1_000)}k"
    return str(round(value))


def vnd(value: float) -> str:
    return f"{round(value):,}".replace(",", ".") + " ₫"


def product_label(seller_sku: str | None, title: str | None) -> str:
    """How copy names the product: its seller SKU, else its title."""
    return seller_sku or (title or "sản phẩm")


def _quoted(name: str) -> str:
    return f"“{name.strip()}”" if name.strip() else ""


def reason_full(candidate: ContentCandidate) -> str:
    """The card's "Lý do đầy đủ" (ContentCards.dc.html), from the evidence rows."""
    rows: Sequence[EvidenceRow] = candidate.rows
    if candidate.kind == VIDEO:
        if len(rows) == 1:
            row = rows[0]
            return (
                f"Video {_quoted(row.name)} có {compact(row.volume)} lượt hiển thị sản phẩm, "
                f"CTR {pct(row.rate)} so với {pct(candidate.target)} của video trong shop "
                "30 ngày trước."
            )
        return (
            f"{len(rows)} video gắn sản phẩm có {compact(candidate.volume)} "
            "lượt hiển thị sản phẩm, "
            f"CTR {pct(candidate.current)} so với {pct(candidate.target)} của video trong shop "
            f"30 ngày trước. Thấp nhất: {_quoted(rows[0].name)} (CTR {pct(rows[0].rate)})."
        )
    if len(rows) == 1:
        row = rows[0]
        return (
            f"Phiên {_quoted(row.name)} có CTOR {pct(row.rate)} so với {pct(candidate.target)} "
            "trung bình các phiên LIVE 30 ngày trước."
        )
    return (
        f"{len(rows)} phiên LIVE có bán sản phẩm, CTOR {pct(candidate.current)} so với "
        f"{pct(candidate.target)} trung bình các phiên LIVE 30 ngày trước. Thấp nhất: "
        f"{_quoted(rows[0].name)} (CTOR {pct(rows[0].rate)})."
    )


def will_draft(kind: ContentKind, label: str, *, discount_cap_pct: float | None) -> list[str]:
    """ "Juli sẽ soạn" — one line each (ContentCards.dc.html)."""
    if kind == VIDEO:
        return [
            "Hook 3 giây và 2 phương án mở đầu",
            "Kịch bản 25–35 giây theo cảnh, sản phẩm xuất hiện trước giây 3",
            "Lời kêu gọi bấm giỏ, gợi ý hashtag và nhạc",
        ]
    offer = (
        "Gợi ý flash sale trong LIVE trong mức trần giảm giá của bạn"
        if discount_cap_pct is not None
        else "Gợi ý ưu đãi trong LIVE không giảm giá (bạn chưa đặt trần giảm giá)"
    )
    return [
        f"Kịch bản host theo khung ASBC cho {label}, có so sánh giá và giới hạn số lượng",
        "Thứ tự giỏ: sản phẩm chủ lực lên đầu, thời điểm ghim",
        offer,
    ]


def measure_line(kind: ContentKind, label: str) -> str:
    """ "Đo kết quả" (ContentCards.dc.html)."""
    if kind == VIDEO:
        return f"CTR trên các video mới gắn {label} trong 7 và 14 ngày, so với video cũ."
    return f"CTOR của {label} ở 3 phiên LIVE kế tiếp, so với phiên trước."


def impact_sentence(per_day: float) -> str:
    return (
        f"Có thể lấy lại khoảng {vnd(per_day)} GMV mỗi ngày "
        "(ước tính theo quy tắc, chưa phải mô hình)"
    )


__all__ = [
    "compact",
    "impact_sentence",
    "measure_line",
    "pct",
    "product_label",
    "reason_full",
    "vnd",
    "will_draft",
]
