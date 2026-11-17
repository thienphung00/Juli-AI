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
    """Whole orders: 12.4 -> '12'; 1234 -> '1.234'; 0 < |x| < 1 -> '< 1'; 0 -> '0'."""
    v = abs(float(x))
    if v < 1e-9:
        return "0"
    if v < 1:
        return "< 1"
    return _group(int(v + 0.5))


def signed_orders(x: Decimal | float) -> str:
    """'+12 đơn' / '−3 đơn'; '< 1 đơn' (no sign) under one order; '0 đơn' for none."""
    n = count(x)
    if n in ("0", "< 1"):
        return f"{n} đơn"
    return f"{'+' if float(x) > 0 else '−'}{n} đơn"
