"""Vietnamese number formats and labels for the option card (pure)."""

from __future__ import annotations

from decimal import Decimal

SOURCE_LABELS: dict[str, str] = {
    "the_san_pham_khac": "Thẻ sản phẩm",
    "trang_shop": "Trang shop",
    "live": "Live",
    "video": "Video",
    "lien_ket": "Liên kết",
    "chenh_lech_nguon": "Chênh lệch nguồn",
}
DRIVER_LABELS: dict[str, str] = {"views": "Lượt xem", "ctr": "CTR", "ctor": "CTOR", "aov": "AOV"}


def _group(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def vnd(x: Decimal | float) -> str:
    """44900 -> '44.900đ' (whole đồng, '.' thousands)."""
    n = int(round(float(x)))
    return f"{'-' if n < 0 else ''}{_group(abs(n))}đ"


def count(x: Decimal | float) -> str:
    """12.0 -> '12'; 0.4 -> '0,4'; 1234 -> '1.234'. One decimal under 10."""
    v = abs(float(x))
    if v >= 10 or v == round(v):
        return _group(int(round(v)))
    return f"{v:.1f}".replace(".", ",")
