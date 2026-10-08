"""Funnel comparison, four-factor GMV split and the hero decision tree — ADR-108 d.5, 7.

GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV holds exactly on window totals
(clicks and SKU orders cancel). The GMV change is split into one contribution
per factor by log shares, ``ΔGMV × ln(f₁/f₀) ÷ ln(GMV₁/GMV₀)``; written with the
logarithmic mean ``L(GMV₁, GMV₀)`` it stays defined when GMV did not move, and
the four contributions sum to ΔGMV exactly. Every value is a daily average.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from juli_backend.services.shop_diagnosis.channels import Counts
from juli_backend.services.shop_diagnosis.confidence import (
    Confidence,
    rate_label,
    series_label,
)
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig


class Factor(StrEnum):
    IMPRESSIONS = "impressions"
    CTR = "ctr"
    CTOR = "ctor"
    AOV = "aov"


FACTOR_LABELS: dict[Factor, str] = {
    Factor.IMPRESSIONS: "Lượt hiển thị sản phẩm",
    Factor.CTR: "CTR (Tỷ lệ nhấp)",
    Factor.CTOR: "CTOR",
    Factor.AOV: "AOV (SKU)",
}


@dataclass(frozen=True)
class FactorChange:
    factor: Factor
    prior: float | None
    last: float | None
    #: ₫ per day of the GMV change carried by this factor; ``None`` when undefined.
    contribution: float | None
    confidence: Confidence | None


@dataclass(frozen=True)
class FunnelComparison:
    """One funnel (a channel or a group), last 30 vs prior 30 days, as daily averages."""

    prior: Counts
    last: Counts
    #: Window totals of SKU orders (not averages) — the confidence floors read these.
    orders_prior: float | None
    orders_last: float | None
    factors: tuple[FactorChange, ...]
    gmv_confidence: Confidence | None
    add_to_cart_rate_confidence: Confidence | None
    orders_per_cart_confidence: Confidence | None

    @property
    def gmv_change(self) -> float:
        return self.last.gmv - self.prior.gmv

    @property
    def gmv_change_share(self) -> float | None:
        return self.gmv_change / self.prior.gmv if self.prior.gmv > 0 else None

    def factor(self, factor: Factor) -> FactorChange:
        return next(f for f in self.factors if f.factor is factor)


def _factor_values(counts: Counts) -> dict[Factor, float | None]:
    return {
        Factor.IMPRESSIONS: counts.impressions,
        Factor.CTR: counts.ctr,
        Factor.CTOR: counts.ctor,
        Factor.AOV: counts.aov,
    }


def contributions(prior: Counts, last: Counts) -> dict[Factor, float] | None:
    """Per factor, its share of ``last.gmv − prior.gmv``; ``None`` when a factor is not > 0."""
    before, after = _factor_values(prior), _factor_values(last)
    if any(v is None or v <= 0 for v in (*before.values(), *after.values())):
        return None
    g0, g1 = prior.gmv, last.gmv
    log_mean = g0 if math.isclose(g0, g1) else (g1 - g0) / math.log(g1 / g0)
    return {
        factor: log_mean * math.log(float(after[factor] or 0) / float(before[factor] or 0))
        for factor in Factor
    }


def _sum(days: list[Counts]) -> Counts:
    total = days[0]
    for day in days[1:]:
        total = total + day
    return total


def _daily_aov(days: list[Counts]) -> list[float]:
    return [d.gmv / d.sku_orders for d in days if d.sku_orders]


def compare(
    prior_days: list[Counts], last_days: list[Counts], config: ShopDiagnosisConfig
) -> FunnelComparison:
    """Compare two windows given one ``Counts`` per day of each."""
    total_prior, total_last = _sum(prior_days), _sum(last_days)
    prior = total_prior.scaled(1 / len(prior_days))
    last = total_last.scaled(1 / len(last_days))
    o0, o1 = total_prior.sku_orders, total_last.sku_orders
    split = contributions(prior, last)
    before, after = _factor_values(prior), _factor_values(last)

    def labelled(kind: Factor) -> Confidence | None:
        if o0 is None or o1 is None:
            return None
        if kind is Factor.IMPRESSIONS:
            return series_label(
                [d.impressions for d in prior_days],
                [d.impressions for d in last_days],
                o0,
                o1,
                config,
            )
        if kind is Factor.CTR:
            return rate_label(
                total_prior.clicks,
                total_prior.impressions,
                total_last.clicks,
                total_last.impressions,
                o0,
                o1,
                config,
            )
        if kind is Factor.CTOR:
            return rate_label(o0, total_prior.clicks, o1, total_last.clicks, o0, o1, config)
        return series_label(_daily_aov(prior_days), _daily_aov(last_days), o0, o1, config)

    factors = tuple(
        FactorChange(
            factor,
            before[factor],
            after[factor],
            split[factor] if split else None,
            labelled(factor),
        )
        for factor in Factor
    )
    has_orders = o0 is not None and o1 is not None
    gmv_conf = (
        series_label([d.gmv for d in prior_days], [d.gmv for d in last_days], o0, o1, config)
        if o0 is not None and o1 is not None
        else None
    )
    cart_conf = opa_conf = None
    if (
        has_orders
        and total_prior.add_to_cart is not None
        and total_last.add_to_cart is not None
        and o0 is not None
        and o1 is not None
    ):
        cart_conf = rate_label(
            total_prior.add_to_cart,
            total_prior.clicks,
            total_last.add_to_cart,
            total_last.clicks,
            o0,
            o1,
            config,
        )
        opa_conf = rate_label(
            o0, total_prior.add_to_cart, o1, total_last.add_to_cart, o0, o1, config
        )
    return FunnelComparison(prior, last, o0, o1, factors, gmv_conf, cart_conf, opa_conf)


class Verdict(StrEnum):
    STABLE = "Ổn định"
    INSUFFICIENT = "Chưa đủ dữ liệu"
    UNCLEAR = "Chưa rõ nguyên nhân"
    STORY = "Có nguyên nhân chính"
    IMPRESSIONS_ONLY = "Chỉ lượt hiển thị đổi rõ"


class CartSide(StrEnum):
    BEFORE = "trước giỏ"
    AFTER = "sau giỏ"


LOOK_NEXT: dict[str, str] = {
    CartSide.BEFORE: "ảnh bìa, giá, đánh giá",
    CartSide.AFTER: "voucher, phí vận chuyển, lịch flash sale",
    Factor.CTR: "ảnh bìa, tiêu đề, giá hiển thị trong kết quả tìm kiếm",
    Factor.AOV: "giá bán, combo và số món trên đơn",
    Factor.CTOR: "trang sản phẩm và các ưu đãi đang chạy",
    Verdict.IMPRESSIONS_ONLY: "kênh nào đổi lượt hiển thị (dòng thời gian bên trên)",
    Verdict.UNCLEAR: "theo dõi thêm cho đến khi đủ đơn để kết luận",
    Verdict.INSUFFICIENT: "theo dõi thêm cho đến khi đủ đơn để kết luận",
    Verdict.STABLE: "không cần xem thêm lúc này",
}


@dataclass(frozen=True)
class Conclusion:
    verdict: Verdict
    #: The main story's factor (STORY, IMPRESSIONS_ONLY); for UNCLEAR, the largest
    #: same-direction factor shown for reference only.
    factor: Factor | None
    side: CartSide | None
    gmv_change_share: float | None
    headline: str
    look_next: str


def _log_change(prior: float | None, last: float | None) -> float | None:
    if not prior or not last or prior <= 0 or last <= 0:
        return None
    return math.log(last / prior)


def cart_side(card: FunnelComparison, falling: bool) -> CartSide | None:
    """Which half of the CTOR moved: the add-to-cart rate or orders per add-to-cart."""
    cart = _log_change(card.prior.add_to_cart_rate, card.last.add_to_cart_rate)
    after = _log_change(card.prior.orders_per_add_to_cart, card.last.orders_per_add_to_cart)
    if cart is None or after is None:
        return None
    if falling:
        return CartSide.BEFORE if cart < after else CartSide.AFTER
    return CartSide.BEFORE if cart > after else CartSide.AFTER


SELF_SEARCH_SCOPE = "Ở nhóm khách tự tìm đến (Thẻ sản phẩm và Tab Cửa hàng)"


def _scoped(body: str) -> str:
    """A GMV statement of the decision tree always names the group it was measured on."""
    return f"{SELF_SEARCH_SCOPE}: {body}"


def _pct(share: float | None, signed: bool = True) -> str:
    if share is None:
        return ""
    return f"{share * 100:+.0f} %" if signed else f"{abs(share) * 100:.0f} %"


def decide(
    group: FunnelComparison, card: FunnelComparison, config: ShopDiagnosisConfig
) -> Conclusion:
    """The d.7 decision tree on a hero product's Nhóm khách tự tìm đến."""
    share = group.gmv_change_share
    orders = [o for o in (group.orders_prior, group.orders_last) if o is not None]
    if len(orders) < 2 or min(orders) < config.min_orders_for_story:
        return Conclusion(
            Verdict.INSUFFICIENT,
            None,
            None,
            share,
            f"Chưa đủ dữ liệu: dưới {config.min_orders_for_story} đơn hàng SKU trong một kỳ",
            LOOK_NEXT[Verdict.INSUFFICIENT],
        )
    if share is not None and abs(share) < config.stable_gmv_change:
        return Conclusion(
            Verdict.STABLE,
            None,
            None,
            share,
            _scoped(f"GMV đổi {_pct(share)}, ổn định"),
            LOOK_NEXT[Verdict.STABLE],
        )
    falling = group.gmv_change < 0
    direction = -1.0 if falling else 1.0
    same_way = sorted(
        (f for f in group.factors if f.contribution is not None and f.contribution * direction > 0),
        key=lambda f: -abs(f.contribution or 0.0),
    )
    clear = [f for f in same_way if f.confidence is Confidence.CLEAR]
    verb = "giảm" if falling else "tăng"
    if not clear:
        reference = same_way[0].factor if same_way else None
        hint = f" (lớn nhất: {FACTOR_LABELS[reference]}, chỉ để tham khảo)" if reference else ""
        return Conclusion(
            Verdict.UNCLEAR,
            reference,
            None,
            share,
            _scoped(
                f"GMV {verb} {_pct(share, False)}. Chưa rõ nguyên nhân: không yếu tố nào thay đổi "
                f"rõ{hint}"
            ),
            LOOK_NEXT[Verdict.UNCLEAR],
        )
    main = clear[0]
    if main.factor is Factor.IMPRESSIONS:
        if len(clear) == 1:
            return Conclusion(
                Verdict.IMPRESSIONS_ONLY,
                Factor.IMPRESSIONS,
                None,
                share,
                _scoped(
                    f"GMV {verb} {_pct(share, False)} chủ yếu do lượt hiển thị sản phẩm; "
                    "sửa trang sản phẩm ít tác động đến yếu tố này"
                ),
                LOOK_NEXT[Verdict.IMPRESSIONS_ONLY],
            )
        main = clear[1]
    side = cart_side(card, falling) if main.factor is Factor.CTOR else None
    where = f" — {side.value}" if side else ""
    look = LOOK_NEXT[side] if side else LOOK_NEXT[main.factor]
    return Conclusion(
        Verdict.STORY,
        main.factor,
        side,
        share,
        _scoped(
            f"GMV {verb} {_pct(share, False)}, nguyên nhân chính: {FACTOR_LABELS[main.factor]} "
            f"{verb}{where}"
        ),
        look,
    )
