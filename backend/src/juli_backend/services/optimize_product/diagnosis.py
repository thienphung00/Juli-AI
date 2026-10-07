"""The stage diagnosis — ADR-106 decision 4, as a pure function.

Given one product's funnel, the shop medians and its listing evidence,
:func:`diagnose_product` returns either a :class:`Diagnosis` (label, trigger,
branch, angle, evidence, rank score) or a :class:`Skip` with the named
reason. :func:`rank_diagnoses` orders diagnoses by ``gap × GMV_28d``, the
sort the T7 ranker performs.

Order of operations, fixed:

1. exclusion (gift / not-for-sale title, non-live status);
2. volume floors per factor (a factor below its floor is not diagnosed);
3. two gaps per factor — against the shop median and against the product's
   own prior window — ``gap = max(gap_median, gap_trend)``, trigger recorded;
4. label: the larger gap of {CTOR, AOV}, AOV only when CTOR's gap is under
   its threshold;
5. branch under CTOR: CTR fires and its gap ≥ CTOR gap → card branch, else
   page branch (Amendment 3: a healthy CTR never routes to the card branch);
6. angle: first angle in the branch's fixed order that has evidence; the card
   branch falls to the page branch when it has none, the page branch falls to
   the card branch only when CTR fires; no branch left → Skip, named by why
   (``tiktok_not_asked``, ``discount_cap_needed``, ``tiktok_found_no_fault``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from juli_backend.services.optimize_product.basket import basket_threshold
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.funnel import ZERO, ProductFunnel, ShopMedians
from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    is_description_code,
    is_image_code,
    is_title_code,
)


class Label(str, Enum):
    """The card's Main KPI — ADR-106 decision 2."""

    CTOR = "Increase CTOR"
    AOV = "Increase AOV"


class Trigger(str, Enum):
    """Which gap fired; copy names exactly one."""

    SHOP_MEDIAN = "shop_median"
    OWN_TREND = "own_trend"


class Branch(str, Enum):
    CARD = "card"  # impression → click: first image, title
    PAGE = "page"  # click → order: description, product discount
    BASKET = "basket"  # order → basket: BMSM


class Angle(str, Enum):
    """The five angles a card may propose. Exactly one per card."""

    ANH_BIA = "ảnh bìa"
    TIEU_DE = "tiêu đề"
    MO_TA = "mô tả"
    GIAM_GIA = "giảm giá sản phẩm"
    MUA_NHIEU_GIAM_NHIEU = "mua nhiều giảm nhiều"


#: Fixed angle order inside each branch (decision 4).
BRANCH_ORDER: dict[Branch, tuple[Angle, ...]] = {
    Branch.CARD: (Angle.ANH_BIA, Angle.TIEU_DE),
    Branch.PAGE: (Angle.MO_TA, Angle.GIAM_GIA),
    Branch.BASKET: (Angle.MUA_NHIEU_GIAM_NHIEU,),
}

#: Prefix rule per angle (TikTok returns codes the published table lacks).
ANGLE_MATCHERS: dict[Angle, Callable[[str], bool]] = {
    Angle.ANH_BIA: is_image_code,
    Angle.TIEU_DE: is_title_code,
    Angle.MO_TA: is_description_code,
}


def codes_for_angle(angle: Angle, codes: Iterable[str]) -> set[str]:
    """The codes among ``codes`` that belong to ``angle`` by prefix rule."""
    matcher = ANGLE_MATCHERS.get(angle)
    return {c for c in codes if matcher(c)} if matcher else set()


@dataclass(frozen=True)
class Gap:
    """Both gaps of one factor, and the one that counts."""

    factor: str
    value: Decimal | None
    median: Decimal | None
    prior: Decimal | None
    gap_median: Decimal | None
    gap_trend: Decimal | None
    cleared_floor: bool
    #: How many products above the floor formed ``median`` (0 when none).
    median_peers: int = 0

    @property
    def gap(self) -> Decimal:
        candidates = [g for g in (self.gap_median, self.gap_trend) if g is not None]
        return max(candidates) if candidates else ZERO

    @property
    def trigger(self) -> Trigger | None:
        if self.gap_median is None and self.gap_trend is None:
            return None
        if self.gap_trend is None or (
            self.gap_median is not None and self.gap_median >= self.gap_trend
        ):
            return Trigger.SHOP_MEDIAN
        return Trigger.OWN_TREND

    def fires(self, config: StageDiagnosisConfig) -> bool:
        if not self.cleared_floor:
            return False
        if self.trigger is Trigger.SHOP_MEDIAN:
            return self.gap >= config.gap_threshold_median
        if self.trigger is Trigger.OWN_TREND:
            return self.gap >= config.gap_threshold_trend
        return False


@dataclass(frozen=True)
class BmsmProposal:
    threshold_items: int
    percent: int
    percent_is_estimate: bool
    #: Where the threshold came from (``histogram`` or ``mean_fallback``), the
    #: orders behind it and, for the histogram, the share already at it.
    source: str = "mean_fallback"
    orders: int = 0
    share: Decimal | None = None


@dataclass(frozen=True)
class Diagnosis:
    product_id: str
    title: str
    label: Label
    trigger: Trigger
    branch: Branch
    angle: Angle
    gap: Gap
    gaps: dict[str, Gap]
    evidence: tuple[Evidence, ...]
    rank_score: Decimal
    channel_scope: str
    #: Angles that also had evidence, in branch order — the "other angles"
    #: a report lists so the analysis covers all five, while the card
    #: carries only ``angle``.
    other_angles: tuple[Angle, ...] = ()
    bmsm: BmsmProposal | None = None
    caveats: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Skip:
    product_id: str
    title: str
    reason: str
    gaps: dict[str, Gap] = field(default_factory=dict)


def _gap_for(
    factor: str,
    value: Decimal | None,
    median: Decimal | None,
    prior: Decimal | None,
    cleared_floor: bool,
    *,
    trend_allowed: bool,
    median_peers: int = 0,
) -> Gap:
    gap_median = None
    gap_trend = None
    if value is not None and median is not None and median > 0:
        gap_median = Decimal(1) - value / median
    if trend_allowed and value is not None and prior is not None and prior > 0:
        gap_trend = Decimal(1) - value / prior
    return Gap(
        factor=factor,
        value=value,
        median=median,
        prior=prior,
        gap_median=gap_median,
        gap_trend=gap_trend,
        cleared_floor=cleared_floor,
        median_peers=median_peers,
    )


def compute_gaps(
    product: ProductFunnel, medians: ShopMedians, config: StageDiagnosisConfig
) -> dict[str, Gap]:
    """Both gaps for CTR, CTOR and AOV."""
    floors = product.clears_floor(config)
    trend_allowed = product.prior is not None and (
        product.age_days is None or product.age_days >= config.min_age_days_for_trend
    )
    prior = product.prior
    return {
        "ctr": _gap_for(
            "ctr",
            product.current.ctr,
            medians.ctr,
            prior.ctr if prior else None,
            floors["ctr"],
            trend_allowed=trend_allowed,
            median_peers=medians.peers.get("ctr", 0),
        ),
        "ctor": _gap_for(
            "ctor",
            product.current.ctor,
            medians.ctor,
            prior.ctor if prior else None,
            floors["ctor"],
            trend_allowed=trend_allowed,
            median_peers=medians.peers.get("ctor", 0),
        ),
        "aov": _gap_for(
            "aov",
            product.current.aov,
            medians.aov,
            prior.aov if prior else None,
            floors["aov"],
            trend_allowed=trend_allowed,
            median_peers=medians.peers.get("aov", 0),
        ),
    }


def _angles_with_evidence(
    branch: Branch,
    evidence: list[Evidence],
    *,
    discount_cap_set: bool,
    active_promotion: bool,
) -> list[Angle]:
    """Angles of ``branch`` that have evidence, in the branch's fixed order."""
    codes = {e.code for e in evidence}
    out: list[Angle] = []
    for angle in BRANCH_ORDER[branch]:
        if angle is Angle.GIAM_GIA:
            # Decision 4: a discount only when no description code remains and
            # the seller's maximum discount is set. Never while a Juli
            # promotion is live on the product (OP-FR-4 cooldown).
            if (
                not codes_for_angle(Angle.MO_TA, codes)
                and discount_cap_set
                and not active_promotion
            ):
                out.append(angle)
            continue
        if angle is Angle.MUA_NHIEU_GIAM_NHIEU:
            if not active_promotion:
                out.append(angle)
            continue
        if codes_for_angle(angle, codes):
            out.append(angle)
    return out


def diagnose_product(
    product: ProductFunnel,
    medians: ShopMedians,
    evidence: list[Evidence],
    config: StageDiagnosisConfig,
    *,
    excluded_reason: str | None = None,
    live: bool = True,
    discount_cap_set: bool = False,
    active_promotion: bool = False,
    diagnoses_asked: bool = False,
    basket_quantities: list[int] | None = None,
) -> Diagnosis | Skip:
    """Decision 4 end to end for one product."""
    if excluded_reason:
        return Skip(product.product_id, product.title, f"excluded: {excluded_reason}")
    if not live:
        return Skip(product.product_id, product.title, "not_live")

    gaps = compute_gaps(product, medians, config)
    ctor_fires = gaps["ctor"].fires(config)
    aov_fires = gaps["aov"].fires(config)
    ctr_fires = gaps["ctr"].fires(config)

    if not (ctor_fires or aov_fires or ctr_fires):
        if not any(g.cleared_floor for g in gaps.values()):
            return Skip(product.product_id, product.title, "below_volume_floor", gaps)
        return Skip(product.product_id, product.title, "no_gap_above_threshold", gaps)

    # Label. A CTR gap alone (CTOR still healthy) still routes to the card
    # branch under the CTOR label: the card's KPI is CTOR, the diagnostic KPI
    # that fired is CTR.
    if aov_fires and not ctor_fires and not ctr_fires:
        label, label_gap = Label.AOV, gaps["aov"]
    elif aov_fires and gaps["aov"].gap > max(gaps["ctor"].gap, gaps["ctr"].gap) and not ctor_fires:
        label, label_gap = Label.AOV, gaps["aov"]
    else:
        label = Label.CTOR
        label_gap = gaps["ctor"] if ctor_fires else gaps["ctr"]

    caveats: list[str] = []
    if product.channel_scope != "PRODUCT_CARD":
        caveats.append(
            "CTR và CTOR tính trên mọi kênh (A-34 total); dòng này không có block "
            "thẻ sản phẩm nên góc độ listing cần xác nhận lại"
        )
    if any(e.source.value == "local" for e in evidence):
        caveats.append(
            "bằng chứng listing do Juli đánh giá từ dữ liệu sản phẩm, chưa phải mã chẩn đoán TikTok"
        )

    if label is Label.AOV:
        basket_angles = _angles_with_evidence(
            Branch.BASKET,
            evidence,
            discount_cap_set=discount_cap_set,
            active_promotion=active_promotion,
        )
        if not basket_angles:
            return Skip(product.product_id, product.title, "aov_lever_locked", gaps)
        basket = basket_threshold(basket_quantities, product.current.items_per_order, config)
        if not basket.reached:
            return Skip(product.product_id, product.title, "bmsm_threshold_unreached", gaps)
        bmsm = BmsmProposal(
            threshold_items=basket.threshold_items,
            percent=config.bmsm_percent_default,
            percent_is_estimate=not discount_cap_set,
            source=basket.source,
            orders=basket.orders,
            share=basket.share,
        )
        return Diagnosis(
            product_id=product.product_id,
            title=product.title,
            label=label,
            trigger=label_gap.trigger or Trigger.SHOP_MEDIAN,
            branch=Branch.BASKET,
            angle=Angle.MUA_NHIEU_GIAM_NHIEU,
            gap=label_gap,
            gaps=gaps,
            evidence=tuple(),
            rank_score=label_gap.gap * product.gmv_28d,
            channel_scope=product.channel_scope,
            bmsm=bmsm,
            caveats=tuple(caveats),
        )

    # Branch under CTOR (decision 4 step 5).
    first = Branch.CARD if ctr_fires and gaps["ctr"].gap >= gaps["ctor"].gap else Branch.PAGE
    candidates = [first]
    if first is Branch.CARD:
        candidates.append(Branch.PAGE)
    elif ctr_fires:
        candidates.append(Branch.CARD)
    chosen_branch: Branch | None = None
    angles: list[Angle] = []
    for branch in candidates:
        angles = _angles_with_evidence(
            branch,
            evidence,
            discount_cap_set=discount_cap_set,
            active_promotion=active_promotion,
        )
        if angles:
            chosen_branch = branch
            break
    if chosen_branch is None:
        codes = {e.code for e in evidence}
        if not diagnoses_asked:
            reason = "tiktok_not_asked"
        elif (
            Branch.PAGE in candidates
            and not codes_for_angle(Angle.MO_TA, codes)
            and not discount_cap_set
            and not active_promotion
        ):
            reason = "discount_cap_needed"
        else:
            reason = "tiktok_found_no_fault"
        return Skip(product.product_id, product.title, reason, gaps)

    angle = angles[0]
    angle_evidence = tuple(e for e in evidence if codes_for_angle(angle, [e.code]))
    other_branch = Branch.PAGE if chosen_branch is Branch.CARD else Branch.CARD
    others = angles[1:]
    if other_branch in candidates:
        others += _angles_with_evidence(
            other_branch,
            evidence,
            discount_cap_set=discount_cap_set,
            active_promotion=active_promotion,
        )
    if chosen_branch is Branch.PAGE and first is Branch.CARD:
        caveats.append("nhánh thẻ (ảnh, tiêu đề) không có bằng chứng; chuyển sang nhánh trang")
    if chosen_branch is Branch.CARD and first is Branch.PAGE:
        caveats.append("nhánh trang (mô tả, giảm giá) không có bằng chứng; chuyển sang nhánh thẻ")

    return Diagnosis(
        product_id=product.product_id,
        title=product.title,
        label=label,
        trigger=label_gap.trigger or Trigger.SHOP_MEDIAN,
        branch=chosen_branch,
        angle=angle,
        gap=label_gap,
        gaps=gaps,
        evidence=angle_evidence,
        rank_score=label_gap.gap * product.gmv_28d,
        channel_scope=product.channel_scope,
        other_angles=tuple(others),
        caveats=tuple(caveats),
    )


def rank_diagnoses(diagnoses: list[Diagnosis]) -> list[Diagnosis]:
    """Decision 4's ranking: ``gap × GMV_28d``, descending; ties by gap."""
    return sorted(diagnoses, key=lambda d: (d.rank_score, d.gap.gap), reverse=True)
