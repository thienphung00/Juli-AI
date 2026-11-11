"""Shared constants, the typed refusal and small helpers of the per-family translations."""

from __future__ import annotations

from decimal import Decimal

from juli_backend.services.shopee_builder.engine.contract import Band

#: Cashback / coupon affiliates (ADR-122 d.9): matched on the lower-cased handle, whole word or
#: prefix. They get ``extra_share`` 0, are labelled below and are never suggested samples.
CASHBACK_AFFILIATES: tuple[str, ...] = ("accesstradevn", "shopbackvn_", "shopback", "accesstrade")
CASHBACK_LABEL = "trang hoàn tiền / mã giảm giá"

#: Ads / affiliate notes (Vietnamese, shown on the card).
NOTE_ADS_NOT_ESTIMABLE = "chưa ước tính được — cần chạy thử"
NOTE_KOL_NOT_ESTIMABLE = "chưa ước tính được — đo sau lần gửi mẫu đầu"
NOTE_NO_PACK_EVIDENCE = "chưa có dữ liệu cho quy cách này"
NOTE_FOLLOWER = "chưa biết tỉ lệ người theo dõi"
#: P100-C (B.10): too few orders to measure who moves up to a tier -> cost and break-even only
NOTE_COMBO_REACH = "chưa ước tính được — chưa đủ đơn để đo số đơn lên mức combo"
NOTE_PACK_SOLD = "Shop đang bán quy cách này: khách chuyển sang listing mới, không thêm đơn."

#: Priors tagged "prior" (ước tính chung) until the shop's own results calibrate them (ADR-121).
#: A visible discount / badge converts a few more clicks: relative CTOR lift at P10 / P50 / P90.
CTOR_VISIBLE_OFFER = (Decimal("0"), Decimal("0.01"), Decimal("0.03"))
#: Share of the orders that sit under a minimum / one unit under a tier that move up to it: the
#: prior (ADR-122 d.13 E2), used only when the scope has too few orders to measure it.
REACH = (Decimal("0"), Decimal("0.2"), Decimal("0.5"))
#: E2: an order within this share below a voucher minimum / combo tier today reaches it.
REACH_WINDOW = Decimal("0.2")
#: E2: fewer orders than this in the scope -> the reach is the tagged prior, not measured.
MIN_REACH_ORDERS = 30
#: The second driver of a two-driver listing / basket family earns this share of the lead
#: driver's predicted lift (tagged "prior").
CO_DRIVER_SHARE = Decimal("0.5")
#: Minimum days with and without ads (and before / after a KOL) before an extra share is measured.
MIN_MEASURE_DAYS = 5
#: Z of the P90 of a normal (the engine fits through P10 / P50 / P90).
Z90 = Decimal("1.2815515655")
#: A flash sale / a day count never goes below one day.
HOURS_PER_DAY = 24


class FamilyRefused(ValueError):
    """The version cannot become an option; ``code`` is stable (``hidden``: builder hides it)."""

    def __init__(self, code: str, text: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.text = text

    @property
    def hidden(self) -> bool:
        return self.code == "hidden"


def dec(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def point(x: Decimal) -> Band:
    return Band(x, x, x)


def band3(t: tuple[Decimal, Decimal, Decimal]) -> Band:
    return Band(*t)


def scaled(b: Band, k: Decimal) -> Band:
    """A band times a factor, kept ordered (a negative factor swaps the ends)."""
    a, m, c = b.p10 * k, b.p50 * k, b.p90 * k
    return Band(min(a, c), m, max(a, c))


def clamp01(x: Decimal) -> Decimal:
    return min(max(x, Decimal(0)), Decimal(1))
