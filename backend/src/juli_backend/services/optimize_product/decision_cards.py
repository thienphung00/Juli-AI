"""Ranked Optimize Product card proposals for one shop — the backend card pipeline.

The report (:mod:`.shop_report`) composes cards from a snapshot folder with
orders, promotions and ratings beside the A-34 windows. The nightly scoring
pass has less: P1's daily per-product analytics and the ``products`` table
(title, status, creation time). This module runs the same ADR-106 pipeline on
that input and nothing else:

1. score the whole catalog — :func:`.catalog_scan.diagnose_all` (shop medians
   over the products above the volume floor, then decision 4 per product);
2. compose in the report's order (ADR-106 amendments 3 and 5): rule cards
   ("Juli tự đề xuất"), then cards waiting for the seller's maximum discount
   ("Cần mức giảm giá tối đa"), then cards whose listing fault TikTok was not
   asked about yet ("Chưa hỏi TikTok"), each group ranked by ``gap × GMV_28d``;
3. keep the top ``top_k`` (30, D24.17) per executor type (Juli / Seller Center,
   D24.21 (4)); one proposal per product.

How many of those surface is the emission budget's call (D24.17: 5 new a
day, 25 a week, 30 open). Learning (D24.6): the ranking value is the
recoverable GMV × the shop's history weight for the lever
(:class:`LeverHistory`); the shown estimate stays the rule-based one.
Listing evidence here is local and limited to the title — the description
and images are not stored, and deriving their codes from empty values would
invent faults (OP-NFR-2). Owner tests, Seller Center cards, the gift
fallback, the ratings filter and the traffic-source check need orders,
promotions, ratings or A-34 channel blocks this input does not carry; they
stay report-only. Pure.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from juli_backend.services.optimize_product.basket import basket_threshold
from juli_backend.services.optimize_product.cards import (
    ANGLE_ACTION,
    NOT_ENOUGH_DATA,
    angle_sentence,
    build_cards,
    gap_reason_sentence,
    main_kpi_value,
)
from juli_backend.services.optimize_product.catalog_scan import diagnose_all
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import ProductDay, product_funnel
from juli_backend.services.optimize_product.diagnosis import (
    BRANCH_ORDER,
    NO_LEVERS,
    Angle,
    BmsmProposal,
    Branch,
    Diagnosis,
    Gap,
    Label,
    PageLevers,
    Skip,
    Trigger,
    _angles_with_evidence,
    codes_for_angle,
    compute_gaps,
)
from juli_backend.services.optimize_product.eligibility import gift_reason
from juli_backend.services.optimize_product.funnel import FunnelWindow, ProductFunnel, ShopMedians
from juli_backend.services.optimize_product.kpi_channel import (
    CHANNEL_LABELS_VI,
    CHANNEL_TOTAL,
    channel_days,
    channel_gmv_per_day,
    kpi_window,
)
from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    derive_local_evidence,
    is_title_code,
    listing_signals_from_product,
)
from juli_backend.services.optimize_product.metric_trigger import (
    GMV_FELL,
    GMV_HELD,
    STATUS_NO_METRIC_DROP,
    MetricDrop,
    MetricTrigger,
    growth_candidates,
    metric_trigger,
)
from juli_backend.services.optimize_product.prediction import (
    CalibrationStats,
    Prediction,
    gmv_range_per_month,
    predict,
)
from juli_backend.services.optimize_product.quality_score import (
    ListingFacts,
    QualityScore,
    lever_weight,
    quality_score,
)
from juli_backend.services.optimize_product.shop_report import (
    STATUS_NEEDS_CAP,
    STATUS_NOT_ASKED,
    STATUS_RULE,
)
from juli_backend.services.optimize_product.shrinkage import ShrinkageContext
from juli_backend.services.optimize_product.tunables import DiagTunables
from juli_backend.services.optimize_product.volatility import (
    CONFIDENCE_LOW,
    STABILITY_ORDER,
    STATUS_LOW_DATA,
    STATUS_NO_DROP,
    Assessment,
    Kpi,
    MetricWindow,
    assess_product,
    kpi_target,
    reference_for,
    stability,
    window_counts,
)
from juli_backend.services.optimize_product.volatility import (
    confidence as confidence_level,
)

#: Version of the card payload shape; bump when ``diagnosis`` changes shape.
PAYLOAD_VERSION = "adr106-v1"

#: Ranked proposals kept per shop and executor type (D24.17: nightly candidates
#: top 30, was 10; D24.21 (4): per type -- Juli / Seller Center -- since each
#: fills its own daily slot).
DEFAULT_TOP_K = 30

#: The promotion angles a seller carries out in Seller Center (D24.21 (4) slot).
SELLER_CENTER_ANGLES: frozenset[Angle] = frozenset(
    {Angle.GIAM_GIA, Angle.MUA_NHIEU_GIAM_NHIEU, Angle.FLASH_SALE, Angle.GIAM_PHI_VAN_CHUYEN}
)

STATUS_CODE_RULE = "rule"
STATUS_CODE_NEEDS_CAP = "needs_discount_cap"
STATUS_CODE_NOT_ASKED = "tiktok_not_asked"

STATUS_LABELS: dict[str, str] = {
    STATUS_CODE_RULE: STATUS_RULE,
    STATUS_CODE_NEEDS_CAP: STATUS_NEEDS_CAP,
    STATUS_CODE_NOT_ASKED: STATUS_NOT_ASKED,
}

#: The funnel stage each branch acts on, in the seller's words.
STAGE_LABELS: dict[Branch, str] = {
    Branch.CARD: "Lượt hiển thị → Lượt nhấp (thẻ sản phẩm)",
    Branch.PAGE: "Lượt nhấp → Đặt hàng (trang sản phẩm)",
    Branch.BASKET: "Giá trị đơn hàng (AOV)",
}

#: ASCII codes for the angles, for clients that switch on them.
LEVER_CODES: dict[Angle, str] = {
    Angle.ANH_BIA: "cover_image",
    Angle.TIEU_DE: "title",
    Angle.MO_TA: "description",
    Angle.GIAM_GIA: "product_discount",
    Angle.MUA_NHIEU_GIAM_NHIEU: "buy_more_save_more",
    Angle.FLASH_SALE: "flash_sale",
    Angle.GIAM_PHI_VAN_CHUYEN: "shipping_discount",
}

#: TikTok's statuses for a listing that is on sale.
LIVE_STATUSES = frozenset({"activate", "active", "live", "on_sale"})


#: D24.6 calibration mapping: the coefficient (realised ÷ expected GMV,
#: ``lever_flows.measurement``) starts at 0.5 for every lever, so the ranking
#: factor is ``coefficient ÷ 0.5`` -- 1 (neutral) until a lever has been
#: measured -- clamped to [0.25, 2].
CALIBRATION_NEUTRAL = Decimal("0.5")
CALIBRATION_FACTOR_MIN = Decimal("0.25")
CALIBRATION_FACTOR_MAX = Decimal("2")


@dataclass(frozen=True)
class LeverHistory:
    """What the shop's history says about one lever (D24.6), for the ranking only.

    ``calibration``: the lever's coefficient for the shop (0.5 until measured).
    ``reason_penalty``: from the seller's Từ chối / Không thực hiện / Hoàn tác
    reasons (``decision_reasons.reason_penalties``), 1 when there are none.
    """

    calibration: Decimal = CALIBRATION_NEUTRAL
    reason_penalty: Decimal = Decimal(1)

    @property
    def calibration_factor(self) -> Decimal:
        factor = self.calibration / CALIBRATION_NEUTRAL
        return min(max(factor, CALIBRATION_FACTOR_MIN), CALIBRATION_FACTOR_MAX)

    @property
    def weight(self) -> Decimal:
        return self.calibration_factor * self.reason_penalty

    @property
    def adjusted(self) -> bool:
        return self.calibration_factor != 1 or self.reason_penalty != 1


@dataclass(frozen=True)
class CatalogProduct:
    """What the pipeline knows about one listing besides its funnel."""

    product_id: str
    title: str
    status: str | None = None
    #: TikTok's category name (D30.2 risky-claims rule list), when stored.
    category: str | None = None
    #: Known SKU prices (VND) and TikTok's ``is_not_for_sale`` flag, when the
    #: caller has them -- the gift rule (``eligibility``) reads both.
    sku_prices: tuple[Decimal, ...] = ()
    is_not_for_sale: bool | None = None


@dataclass(frozen=True)
class CardProposal:
    """One ranked product card, before it becomes an ``ActionCard`` row."""

    rank: int
    product_id: str
    title: str
    status: str
    label: Label
    stage: Branch
    lever: Angle
    trigger: Trigger
    gap: Decimal
    main_kpi_value: str
    main_kpi_raw: Decimal | None
    reason: str
    action: str
    lever_detail: str
    lever_confirmed: bool
    evidence: tuple[Evidence, ...] = ()
    caveats: tuple[str, ...] = ()
    rank_score: Decimal = Decimal(0)
    #: D22 priority: recoverable GMV per day (rule-based estimate); ``None``
    #: when the weak stage has no reference rate or no volume.
    recoverable_gmv_per_day: Decimal | None = None
    recoverable_basis: dict | None = None
    channel_scope: str = "ALL_CHANNELS"
    bmsm: dict | None = None
    gaps: dict[str, Gap] = field(default_factory=dict)
    #: D24.6: the shop's history for this lever, applied to the ranking only.
    history: LeverHistory | None = None
    #: D29: the product's volatility assessment, its target metric and KPI.
    assessment: Assessment | None = None
    target_metric: str | None = None
    kpi: Kpi | None = None
    #: D30.2 / D30.3 (internal): Quality Score and the calibrated lift.
    quality: QualityScore | None = None
    prediction: Prediction | None = None
    #: D30.3: GMV range per month (min, max) from the KPI range.
    gmv_estimate: tuple[float, float] | None = None
    #: D29 ranking value (recoverable × calibration × reason penalty × QS weight);
    #: replaces the D24.6 weighting when set.
    d29_ranking_value: Decimal | None = None
    #: D29.4: other cards of the same product and target metric in this plan.
    sibling_cards: int = 0
    #: D32: "Độ tin cậy" of a KPI read on the lever's channel (its events and
    #: impressions CV); ``None`` keeps the product's all-channel confidence.
    kpi_confidence: str | None = None
    #: D33 (S28B): why the card exists when it is not the D29 GMV-drop branch
    #: (:data:`REASON_BELOW_SHOP_LEVEL`); ``None`` for every D29 card.
    reason_code: str | None = None
    #: D39.1 (metric-first, internal): the metrics that fell beyond their band,
    #: what each costs, and whether GMV held; ``None`` on the GMV-first path.
    metric_trigger: MetricTrigger | None = None

    @property
    def confidence(self) -> str | None:
        if self.kpi_confidence is not None:
            return self.kpi_confidence
        return self.assessment.confidence if self.assessment is not None else None

    @property
    def ranking_gmv_per_day(self) -> Decimal | None:
        """Recoverable GMV × the lever's history weight — what the ranking sorts on."""
        if self.d29_ranking_value is not None:
            return self.d29_ranking_value
        if self.recoverable_gmv_per_day is None:
            return None
        weight = self.history.weight if self.history is not None else Decimal(1)
        return self.recoverable_gmv_per_day * weight

    @property
    def adjusted_by_history(self) -> bool:
        return self.history is not None and self.history.adjusted

    @property
    def main_kpi(self) -> str:
        return "CTOR" if self.label is Label.CTOR else "AOV"

    def diagnosis_payload(self, *, as_of: str, medians: ShopMedians) -> dict:
        """The ``diagnosis`` block of the card payload (JSON-ready)."""
        return {
            "version": PAYLOAD_VERSION,
            "as_of": as_of,
            "rank": self.rank,
            "status": self.status,
            "status_label": STATUS_LABELS[self.status],
            "stage": {"code": self.stage.value, "label": STAGE_LABELS[self.stage]},
            "lever": {
                "code": LEVER_CODES[self.lever],
                "label": self.lever.value,
                "action": ANGLE_ACTION[self.lever],
                "detail": self.lever_detail,
                "confirmed": self.lever_confirmed,
                "evidence": [
                    {"code": e.code, "source": e.source.value, "detail": e.detail}
                    for e in self.evidence
                ],
            },
            "main_kpi": {
                "key": "ctor" if self.label is Label.CTOR else "aov",
                "label": self.main_kpi,
                "value": self.main_kpi_value,
                "raw": None if self.main_kpi_raw is None else float(self.main_kpi_raw),
            },
            "trigger": {
                "code": self.trigger.value,
                "gap": float(self.gap.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
                "sentence": self.reason,
            },
            "gaps": {
                name: {
                    "value": _f(g.value),
                    "shop_median": _f(g.median),
                    "prior": _f(g.prior),
                    "gap_vs_median": _f(g.gap_median),
                    "gap_vs_prior": _f(g.gap_trend),
                    "median_peers": g.median_peers,
                    "cleared_floor": g.cleared_floor,
                }
                for name, g in self.gaps.items()
            },
            "shop_medians": {
                "ctr": _f(medians.ctr),
                "ctor": _f(medians.ctor),
                "aov": _f(medians.aov),
                "peers": dict(medians.peers),
            },
            "bmsm": self.bmsm,
            "caveats": list(self.caveats),
            "channel_scope": self.channel_scope,
            "rank_score": float(self.rank_score.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "recoverable_gmv_per_day": _f(self.recoverable_gmv_per_day),
            "recoverable_gmv_basis": self.recoverable_basis,
            "product_title": self.title,
            "adjusted_by_history": self.adjusted_by_history,
            "history_adjustment": (
                {
                    "calibration_coefficient": _f(self.history.calibration),
                    "calibration_factor": _f(self.history.calibration_factor),
                    "reason_penalty": _f(self.history.reason_penalty),
                    "ranking_gmv_per_day": _f(self.ranking_gmv_per_day),
                }
                if self.history is not None and self.history.adjusted
                else None
            ),
            # D29 / D30.3 internals (not in the seller allowlist): the assessment
            # behind the target metric and the calibrated lift.
            **({"volatility": self.assessment.to_json()} if self.assessment is not None else {}),
            **({"prediction": self.prediction.to_json()} if self.prediction is not None else {}),
            **(
                {"metric_trigger": self.metric_trigger.to_json()}
                if self.metric_trigger is not None
                else {}
            ),
        }


@dataclass(frozen=True)
class ShopCardPlan:
    """The pipeline's output for one shop."""

    proposals: list[CardProposal]
    medians: ShopMedians
    skips: list[Skip]
    excluded: dict[str, str]
    products_scored: int
    #: Proposals that ranked below ``top_k`` (they get no row).
    overflow: int = 0


#: How the D22 estimate is labelled wherever it is shown.
RECOVERABLE_LABEL = "Ước tính từ số liệu hiện tại của sản phẩm"


def _reference(gap: Gap) -> tuple[Decimal | None, str | None]:
    """The rate the weak stage is compared to: the peer median, else its own prior."""
    if gap.median is not None and gap.gap_median is not None and gap.gap_median > 0:
        return gap.median, "shop_median"
    if gap.prior is not None and gap.gap_trend is not None and gap.gap_trend > 0:
        return gap.prior, "own_prior"
    return None, None


def recoverable_gmv_per_day(
    stage: Branch, gaps: dict[str, Gap], last30: FunnelWindow | None
) -> tuple[Decimal | None, dict | None]:
    """D22 ranking: (reference rate − current rate) × the stage's daily volume × AOV.

    Over the last 30 days (``last30``, a 30-day window): CTR stage → impressions
    per day, and the extra clicks are turned into orders with the product's own
    CTOR (impressions × CTR gap × AOV alone would price clicks as orders);
    CTOR stage → clicks per day; AOV stage → SKU orders per day × AOV gap.
    The rate gap is the diagnosis's own (14 days, ADR-106 decision 4). A
    rule-based estimate, never a model output.
    """
    if last30 is None or last30.days <= 0:
        return None, None
    factor = {"card": "ctr", "page": "ctor", "basket": "aov"}[stage.value]
    gap = gaps.get(factor)
    if gap is None or gap.value is None:
        return None, None
    reference, against = _reference(gap)
    if reference is None:
        return None, None
    delta = reference - gap.value
    if delta <= 0:
        return None, None
    aov = last30.aov
    value: Decimal | None
    if factor == "aov":
        volume = last30.per_day(last30.sku_orders)
        value = delta * volume
    elif factor == "ctor":
        volume = last30.per_day(last30.clicks)
        value = delta * volume * aov if aov is not None else None
    else:
        volume = last30.per_day(last30.impressions)
        ctor = last30.ctor
        value = delta * volume * ctor * aov if aov is not None and ctor is not None else None
    if value is None:
        return None, None
    return value, {
        "label": RECOVERABLE_LABEL,
        "stage_rate": factor,
        "current_rate": float(gap.value),
        "reference_rate": float(reference),
        "reference": against,
        "volume_per_day": float(volume),
        "aov": None if aov is None else float(aov),
        "window_days": last30.days,
    }


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def title_evidence(title: str, config: StageDiagnosisConfig) -> list[Evidence]:
    """Local title evidence only — the one listing field the database stores.

    ``derive_local_evidence`` also reads description length and image count;
    with those unknown it would report a 0-character description and zero
    images, faults that do not exist. Only its title codes are kept.
    """
    signals = listing_signals_from_product({"title": title}, config)
    return [e for e in derive_local_evidence(signals, config) if is_title_code(e.code)]


def exclusion_reason(product: CatalogProduct, config: StageDiagnosisConfig) -> str | None:
    """Gift items (``eligibility``) and listings not on sale are not diagnosed."""
    gift = gift_reason(
        title=product.title,
        is_not_for_sale=product.is_not_for_sale,
        sku_prices=product.sku_prices,
        extra_patterns=config.exclude_title_patterns,
    )
    if gift:
        return gift
    if product.status and product.status.strip().lower() not in LIVE_STATUSES:
        return f"status {product.status}"
    return None


def _firing_gap(gaps: dict[str, Gap], config: StageDiagnosisConfig) -> Gap:
    """The larger fired gap of CTR and CTOR — what a pending card's reason names."""
    firing = [g for g in (gaps["ctr"], gaps["ctor"]) if g.fires(config)]
    return max(firing, key=lambda g: g.gap) if firing else gaps["ctor"]


def _ctor_value(gaps: dict[str, Gap]) -> tuple[str, Decimal | None]:
    gap = gaps["ctor"]
    if not gap.cleared_floor or gap.value is None:
        return NOT_ENOUGH_DATA, None
    shown = (gap.value * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{shown} %", gap.value


def _rule_proposal(diag: Diagnosis, reason: str, config: StageDiagnosisConfig) -> CardProposal:
    label_gap = diag.gaps["ctor" if diag.label is Label.CTOR else "aov"]
    bmsm = None
    if diag.bmsm is not None:
        bmsm = {
            "threshold_items": diag.bmsm.threshold_items,
            "percent": diag.bmsm.percent,
            "percent_is_estimate": diag.bmsm.percent_is_estimate,
            "source": diag.bmsm.source,
            "orders": diag.bmsm.orders,
            "window_days": 30,
        }
    return CardProposal(
        rank=0,
        product_id=diag.product_id,
        title=diag.title,
        status=STATUS_CODE_RULE,
        label=diag.label,
        stage=diag.branch,
        lever=diag.angle,
        trigger=diag.trigger,
        gap=diag.gap.gap,
        main_kpi_value=main_kpi_value(diag),
        main_kpi_raw=label_gap.value if label_gap.cleared_floor else None,
        reason=reason,
        action=ANGLE_ACTION[diag.angle],
        lever_detail=angle_sentence(diag),
        lever_confirmed=bool(diag.evidence) or diag.branch is Branch.BASKET,
        evidence=diag.evidence,
        caveats=diag.caveats,
        rank_score=diag.rank_score,
        channel_scope=diag.channel_scope,
        bmsm=bmsm,
        gaps=diag.gaps,
    )


def _pending_proposal(
    skip: Skip, funnel: ProductFunnel, config: StageDiagnosisConfig
) -> CardProposal:
    """A "Cần mức giảm giá tối đa" or "Chưa hỏi TikTok" card (amendment 3)."""
    gap = _firing_gap(skip.gaps, config)
    trigger = gap.trigger or Trigger.SHOP_MEDIAN
    ctr, ctor = skip.gaps["ctr"], skip.gaps["ctor"]
    branch = Branch.CARD if ctr.fires(config) and ctr.gap >= ctor.gap else Branch.PAGE
    needs_cap = skip.reason == "discount_cap_needed"
    lever = Angle.GIAM_GIA if needs_cap else BRANCH_ORDER[branch][0]
    value, raw = _ctor_value(skip.gaps)
    detail = (
        "Giảm giá sản phẩm, sau khi shop đặt mức giảm giá tối đa"
        if needs_cap
        else f"{ANGLE_ACTION[lever]}, nếu TikTok chỉ ra lỗi"
    )
    caveats = (
        "CTR và CTOR tính trên mọi kênh; chưa tách được kênh thẻ sản phẩm",
        "Juli chưa hỏi TikTok chẩn đoán trang sản phẩm này; lần chạy sẽ hỏi trước khi đề xuất",
    )
    return CardProposal(
        rank=0,
        product_id=skip.product_id,
        title=skip.title,
        status=STATUS_CODE_NEEDS_CAP if needs_cap else STATUS_CODE_NOT_ASKED,
        label=Label.CTOR,
        stage=branch,
        lever=lever,
        trigger=trigger,
        gap=gap.gap,
        main_kpi_value=value,
        main_kpi_raw=raw,
        reason=gap_reason_sentence(gap, trigger, full_median_peers=config.full_median_peers),
        action=ANGLE_ACTION[lever],
        lever_detail=detail,
        lever_confirmed=False,
        caveats=caveats if not needs_cap else caveats[:1],
        rank_score=gap.gap * funnel.gmv_28d,
        channel_scope=funnel.channel_scope,
        gaps=skip.gaps,
    )


def keep_top_per_type(ordered: list[CardProposal], top_k: int) -> list[CardProposal]:
    """The best ``top_k`` of each executor type, re-ranked 1..n in their order.

    D24.21 (4): Juli-executed and Seller Center cards fill separate daily
    slots, so each type keeps its own top ``top_k`` -- otherwise a shop whose
    best 30 are all Juli cards would never fill its Seller Center slot.
    """
    per_type: dict[bool, int] = {}
    selected: list[CardProposal] = []
    for proposal in ordered:
        seller_center = proposal.lever in SELLER_CENTER_ANGLES
        if per_type.get(seller_center, 0) >= top_k:
            continue
        per_type[seller_center] = per_type.get(seller_center, 0) + 1
        selected.append(proposal)
    return [replace(p, rank=index) for index, p in enumerate(selected, start=1)]


def plan_shop_cards(
    funnels: list[ProductFunnel],
    catalog: dict[str, CatalogProduct],
    config: StageDiagnosisConfig,
    *,
    top_k: int = DEFAULT_TOP_K,
    discount_cap_set: bool = False,
    last30: dict[str, FunnelWindow] | None = None,
    history: dict[str, LeverHistory] | None = None,
    tiktok_evidence: dict[str, list[Evidence]] | None = None,
    daily: dict[str, list[ProductDay]] | None = None,
    as_of: date | None = None,
    tunables: DiagTunables | None = None,
    calibration: dict[str, CalibrationStats] | None = None,
    fleet_calibration: dict[str, CalibrationStats] | None = None,
    listing_facts: dict[str, ListingFacts] | None = None,
    benchmarks: dict[str, dict[str, float]] | None = None,
    page_levers: dict[str, PageLevers] | None = None,
    active_bmsm: frozenset[str] = frozenset(),
) -> ShopCardPlan:
    """Score the catalog, compose the ranked proposals, keep the top ``top_k``.

    D33 quota mode (``tunables.card_quota_mode``, D29 path only): ``page_levers``
    (product id -> the promotion facts read from stored data) gates the price
    levers per product, ``active_bmsm`` holds products already running a
    Mua nhiều giảm nhiều; see :func:`_plan_d29` for the rest of the mode.

    ``history`` (lever code -> :class:`LeverHistory`, D24.6) weights the
    ranking; a lever absent from it is neutral. ``tiktok_evidence`` (product id
    -> TikTok's own listing codes, fast track P17: what the quick scan read)
    is added to the local title evidence, and those products count as asked.

    With ``daily`` (product id -> daily rows) and ``as_of`` the D29 pipeline
    runs instead of ADR-106's gap threshold (:func:`_plan_d29`): the D39.1
    metric-first trigger (``tunables.diag_trigger``, default; ``gmv_first`` keeps
    D29.2's GMV gate), one target metric per product, one proposal per (product, lever)
    within it, stable-first ranking, KPI and Quality Score / Performance
    Prediction (D30.2–3). Without them, the ADR-106 behaviour is unchanged.
    """
    excluded: dict[str, str] = {}
    evidence_by_id: dict[str, list[Evidence]] = {}
    asked = set(tiktok_evidence or {})
    for funnel in funnels:
        product = catalog.get(funnel.product_id) or CatalogProduct(funnel.product_id, funnel.title)
        reason = exclusion_reason(product, config)
        if reason:
            excluded[funnel.product_id] = reason
        evidence_by_id[funnel.product_id] = [
            *title_evidence(product.title, config),
            *(tiktok_evidence or {}).get(funnel.product_id, []),
        ]

    medians, diagnoses, skips = diagnose_all(
        funnels,
        evidence_by_id,
        excluded,
        config,
        asked=asked,
        discount_cap_set=discount_cap_set,
    )
    if daily is not None and as_of is not None:
        return _plan_d29(
            funnels,
            catalog,
            config,
            medians=medians,
            excluded=excluded,
            evidence_by_id=evidence_by_id,
            asked=asked,
            top_k=top_k,
            discount_cap_set=discount_cap_set,
            daily=daily,
            as_of=as_of,
            tunables=tunables or DiagTunables(),
            history=history or {},
            calibration=calibration or {},
            fleet_calibration=fleet_calibration or {},
            listing_facts=listing_facts or {},
            benchmarks=benchmarks or {},
            page_levers=page_levers or {},
            active_bmsm=active_bmsm,
        )
    by_id = {d.product_id: d for d in diagnoses}
    funnel_by_id = {f.product_id: f for f in funnels}

    rules = [
        _rule_proposal(by_id[card.product_id], card.reason, config)
        for card in build_cards(diagnoses, config)
    ]
    needs_cap: list[CardProposal] = []
    not_asked: list[CardProposal] = []
    for skip in skips:
        if skip.reason == "discount_cap_needed":
            needs_cap.append(_pending_proposal(skip, funnel_by_id[skip.product_id], config))
        elif skip.reason == "tiktok_not_asked":
            not_asked.append(_pending_proposal(skip, funnel_by_id[skip.product_id], config))

    # D22: rank by recoverable GMV per day (rule-based); ADR-106's gap × GMV_28d
    # breaks ties and orders proposals with no estimate, after those with one.
    # D24.6: both are weighted by the shop's history for the lever.
    def _priced(p: CardProposal) -> CardProposal:
        value, basis = recoverable_gmv_per_day(p.stage, p.gaps, (last30 or {}).get(p.product_id))
        lever_history = (history or {}).get(LEVER_CODES[p.lever])
        return replace(
            p, recoverable_gmv_per_day=value, recoverable_basis=basis, history=lever_history
        )

    def _weight(p: CardProposal) -> Decimal:
        return p.history.weight if p.history is not None else Decimal(1)

    rules, needs_cap, not_asked = (
        [_priced(p) for p in group] for group in (rules, needs_cap, not_asked)
    )
    for group in (rules, needs_cap, not_asked):
        group.sort(
            key=lambda p: (
                p.ranking_gmv_per_day is not None,
                p.ranking_gmv_per_day or Decimal(0),
                p.rank_score * _weight(p),
            ),
            reverse=True,
        )

    ordered: list[CardProposal] = []
    seen: set[str] = set()
    for proposal in (*rules, *needs_cap, *not_asked):
        if proposal.product_id in seen:
            continue
        seen.add(proposal.product_id)
        ordered.append(proposal)
    kept = keep_top_per_type(ordered, top_k)
    return ShopCardPlan(
        proposals=kept,
        medians=medians,
        skips=skips,
        excluded=excluded,
        products_scored=len(funnels),
        overflow=len(ordered) - len(kept),
    )


# =========================================================================== D29


#: D29: the funnel stage (branch) that moves each target metric. Hiển thị moves
#: through the title's keywords (the Đòn bẩy map: "từ khoá tiêu đề").
METRIC_BRANCH: dict[str, Branch] = {
    "impressions": Branch.CARD,
    "ctr": Branch.CARD,
    "ctor": Branch.PAGE,
    "aov": Branch.BASKET,
}
METRIC_LABELS_VI: dict[str, str] = {
    "impressions": "Lượt hiển thị",
    "ctr": "CTR",
    "ctor": "CTOR",
    "aov": "AOV",
}
#: Why a product got no D29 proposal (the plan's ``skips``), besides the assessment's status.
SKIP_NO_LEVER = "no_lever_for_target_metric"


def _pct_text(value: float) -> str:
    return f"{round(value * 100)} %"


def d29_reason(assessment: Assessment, metric: str) -> str:
    """One sentence: the GMV fall beyond its band, then the metric that explains it."""
    gmv_now, gmv_before = assessment.gmv_current or 0.0, assessment.gmv_earlier or 0.0
    fall = 1 - gmv_now / gmv_before if gmv_before > 0 else 0.0
    metric_fall = 1 - math.exp(assessment.contributions.get(metric, 0.0))
    return (
        f"GMV mỗi ngày giảm {_pct_text(fall)} so với {assessment.window_days} ngày trước, "
        f"vượt mức dao động bình thường; nguyên nhân chính: {METRIC_LABELS_VI[metric]} "
        f"giảm {_pct_text(metric_fall)}"
    )


#: D39.1 copy: the metric that held GMV, mid-sentence.
METRIC_NAMES_INLINE_VI: dict[str, str] = {
    "impressions": "lượt hiển thị",
    "ctr": "CTR",
    "ctor": "CTOR",
    "aov": "AOV",
}


def _vnd_text(value: float) -> str:
    """Rounded to the thousand, Vietnamese grouping: 1234567 -> "1.235.000 ₫"."""
    thousands = max(round(value / 1000), 0) * 1000
    return f"{thousands:,}".replace(",", ".") + " ₫"


def metric_first_reason(drop: MetricDrop, trigger: MetricTrigger) -> str:
    """D39.1 seller copy: which metric fell, whether GMV held (and thanks to what), and
    what improving it may bring per month -- plain words, the on-screen metric labels."""
    label = METRIC_LABELS_VI[drop.metric]
    where = (
        f" trên kênh {CHANNEL_LABELS_VI[drop.channel]}"
        if drop.channel != CHANNEL_TOTAL and drop.channel in CHANNEL_LABELS_VI
        else ""
    )
    head = (
        f"{label}{where} giảm {_pct_text(drop.drop_pct / 100)} so với {drop.window_days} ngày trước"
    )
    monthly = _vnd_text(drop.gmv_cost_per_day * 30)
    inline = METRIC_NAMES_INLINE_VI[drop.metric]
    if trigger.gmv == GMV_HELD:
        held = (
            f"doanh thu được giữ nhờ {METRIC_NAMES_INLINE_VI[trigger.held_by]} tăng"
            if trigger.held_by is not None
            else "doanh thu vẫn giữ được"
        )
        return (
            f"{head} nhưng {held}; nếu cải thiện {inline}, doanh thu có thể tăng thêm "
            f"khoảng {monthly}/tháng"
        )
    if trigger.gmv == GMV_FELL and trigger.gmv_change_pct is not None:
        return (
            f"{head} và kéo doanh thu giảm {_pct_text(-trigger.gmv_change_pct / 100)}; nếu "
            f"cải thiện {inline}, doanh thu có thể lấy lại khoảng {monthly}/tháng"
        )
    return f"{head}; nếu cải thiện {inline}, doanh thu có thể tăng thêm khoảng {monthly}/tháng"


def _target_gap(
    metric: str,
    current: float,
    medians: ShopMedians,
    earlier: float | None,
    low_data: bool,
) -> Gap:
    median = {"ctr": medians.ctr, "ctor": medians.ctor, "aov": medians.aov}.get(metric)
    value = Decimal(str(current))
    prior = Decimal(str(earlier)) if earlier is not None else None
    return Gap(
        factor=metric,
        value=value,
        median=median,
        prior=prior,
        gap_median=Decimal(1) - value / median if median else None,
        gap_trend=Decimal(1) - value / prior if prior else None,
        cleared_floor=not low_data,
        median_peers=medians.peers.get(metric, 0),
    )


def _volume_per_day(metric: str, window: FunnelWindow) -> Decimal:
    if metric == "ctor":
        return window.per_day(window.clicks)
    if metric == "aov":
        return window.per_day(window.sku_orders)
    return window.per_day(window.impressions)


def _d29_levers(
    metric: str,
    *,
    evidence: list[Evidence],
    asked: bool,
    discount_cap_set: bool,
    funnel: ProductFunnel,
    config: StageDiagnosisConfig,
    levers: PageLevers = NO_LEVERS,
    bmsm_running: bool = False,
) -> tuple[str | None, list[Angle], BmsmProposal | None]:
    """(status code, levers, BMSM) for the target metric; ``(None, [], None)`` = no lever.

    Same gates as ADR-106 decision 4: a listing lever needs a diagnosis code, a
    discount needs the seller's cap and no description code, BMSM needs a
    reachable basket threshold. A target metric with no evidence yet is a
    pending card ("Chưa hỏi TikTok" / "Cần mức giảm giá tối đa") on its first lever.
    D33: ``levers`` (stored promotion facts) and ``bmsm_running`` (a Mua nhiều
    giảm nhiều already runs on the product); both default to "nothing known".
    """
    branch = METRIC_BRANCH[metric]
    if metric == "aov":
        if bmsm_running:
            return None, [], None
        basket = basket_threshold(None, funnel.current.items_per_order, config)
        if not basket.reached:
            return None, [], None
        bmsm = BmsmProposal(
            threshold_items=basket.threshold_items,
            percent=config.bmsm_percent_default,
            percent_is_estimate=not discount_cap_set,
            source=basket.source,
            orders=basket.orders,
            share=basket.share,
        )
        return STATUS_CODE_RULE, [Angle.MUA_NHIEU_GIAM_NHIEU], bmsm
    angles = _angles_with_evidence(
        branch, evidence, discount_cap_set=discount_cap_set, active_promotion=False, levers=levers
    )
    if metric == "impressions":
        angles = [a for a in angles if a is Angle.TIEU_DE]
    if angles:
        return STATUS_CODE_RULE, angles, None
    codes = {e.code for e in evidence}
    if not asked:
        first = Angle.TIEU_DE if metric == "impressions" else BRANCH_ORDER[branch][0]
        return STATUS_CODE_NOT_ASKED, [first], None
    if branch is Branch.PAGE and not codes_for_angle(Angle.MO_TA, codes) and not discount_cap_set:
        return STATUS_CODE_NEEDS_CAP, [Angle.GIAM_GIA], None
    return None, [], None


#: D33 (S28B): a card for a product whose GMV did not fall but whose target
#: metric sits below the shop's level on the lever's channel (quota mode only).
REASON_BELOW_SHOP_LEVEL = "below_shop_level"
#: Metrics S28B compares with the shop median (Lượt hiển thị has no shop median).
S28B_METRICS: tuple[str, ...] = ("ctr", "ctor", "aov")
#: D33: candidates kept per cell (target metric × KPI channel) in quota mode,
#: as a multiple of the cell's open-card quota (room for cooldowns and D29.4).
QUOTA_CANDIDATES_PER_CELL_MULT = 3


def _median_of(medians: ShopMedians, metric: str) -> float | None:
    value = {"ctr": medians.ctr, "ctor": medians.ctor, "aov": medians.aov}.get(metric)
    return float(value) if value is not None and value > 0 else None


def _clearly_below(value: float | None, band_pct: float | None, median: float | None) -> bool:
    """Below the median by more than one band of its own window (not noise)."""
    if value is None or value <= 0 or band_pct is None or median is None:
        return False
    return value * (1 + band_pct / 100) < median


def below_shop_metric(assessment: Assessment, medians: ShopMedians) -> str | None:
    """S28B: the metric furthest below the shop median, with enough data, else ``None``."""
    best: tuple[float, str] | None = None
    for metric in S28B_METRICS:
        window = assessment.metrics.get(metric)
        median = _median_of(medians, metric)
        if window is None or window.low_data or median is None:
            continue
        if not _clearly_below(window.value, window.band_pct, median):
            continue
        gap = 1 - (window.value or 0.0) / median
        if best is None or gap > best[0]:
            best = (gap, metric)
    return best[1] if best is not None else None


def _rate_text(metric: str, value: float) -> str:
    if metric == "aov":
        return f"{round(value):,}".replace(",", ".") + " ₫"
    return f"{value * 100:.2f}".replace(".", ",") + " %"


def below_shop_reason(metric: str, channel: str, current: float, median: float) -> str:
    """S28B seller copy: the metric sits below the shop's usual level; sales did not fall."""
    where = (
        "trên tất cả kênh"
        if channel == CHANNEL_TOTAL or channel not in CHANNEL_LABELS_VI
        else f"trên kênh {CHANNEL_LABELS_VI[channel]}"
    )
    return (
        f"{METRIC_LABELS_VI[metric]} của sản phẩm {where} thấp hơn mức chung của shop "
        f"({_rate_text(metric, current)} so với {_rate_text(metric, median)}); doanh thu "
        "không giảm, đây là cơ hội tăng thêm"
    )


def keep_top_per_cell(ordered: list[CardProposal], top_k: int) -> list[CardProposal]:
    """D33: the best ``top_k`` of each cell (target metric × KPI channel), re-ranked 1..n."""
    per_cell: dict[tuple[str | None, str], int] = {}
    selected: list[CardProposal] = []
    for proposal in ordered:
        cell = (proposal.target_metric, proposal.kpi.channel if proposal.kpi else CHANNEL_TOTAL)
        if per_cell.get(cell, 0) >= top_k:
            continue
        per_cell[cell] = per_cell.get(cell, 0) + 1
        selected.append(proposal)
    return [replace(p, rank=index) for index, p in enumerate(selected, start=1)]


def _skip_reason(assessment: Assessment, metric_first: bool) -> str:
    """Why a product got no D29 / D39.1 proposal (the plan's ``skips``)."""
    if not metric_first:
        return f"d29:{assessment.status}"
    # Every event-based metric thin (Lượt hiển thị is never low-data): nothing to read.
    thin = all(w.low_data for m, w in assessment.metrics.items() if m != "impressions")
    if assessment.status == STATUS_LOW_DATA and thin:
        return f"d29:{STATUS_LOW_DATA}"
    return f"d39:{STATUS_NO_METRIC_DROP}"


@dataclass(frozen=True)
class _KpiBasis:
    """What one (product, lever) KPI is built on (D29 on the D32 channel)."""

    channel: str
    window: MetricWindow
    rows: tuple[ProductDay, ...]
    reference: float
    source: str
    medians: ShopMedians
    #: ``None``: the product's all-channel confidence (``Assessment.confidence``).
    confidence: str | None
    volatile: bool
    gmv_per_day: float


def _channel_medians(
    channel: str,
    funnels: list[ProductFunnel],
    excluded: dict[str, str],
    daily: dict[str, list[ProductDay]],
    *,
    cache: dict[str, ShopMedians],
    as_of: date,
    config: StageDiagnosisConfig,
) -> ShopMedians:
    """The shop medians over every product's projection onto ``channel`` (same floors)."""
    if channel not in cache:
        cache[channel] = ShopMedians.from_products(
            (
                product_funnel(
                    f.product_id,
                    f.title,
                    channel_days(daily.get(f.product_id, []), channel),
                    as_of=as_of,
                    config=config,
                )
                for f in funnels
                if f.product_id not in excluded
            ),
            config,
        )
    return cache[channel]


def _kpi_basis(
    rows: list[ProductDay],
    *,
    as_of: date,
    metric: str,
    lever: str,
    tunables: DiagTunables,
    total: MetricWindow,
    assessment: Assessment,
    medians: ShopMedians,
    channel_medians: Callable[[str], ShopMedians],
    benchmark: float | None,
) -> _KpiBasis:
    """D32: the KPI window, reference, confidence and GMV/day on the lever's channel.

    All-channel (``total``): D29 unchanged -- the shop median, the product's own
    earlier level and the category benchmark; the product's confidence and
    stability; the product's GMV/day. On a channel: the same rules over the
    channel's own series -- the channel's shop median and earlier level (a
    category benchmark is all-channel, so it is not used); confidence and
    stability from the channel window's clicks and impressions CV; GMV/day of
    the channel (TikTok's sales breakdown), the product's when none is stored.
    """
    kw = kpi_window(rows, as_of=as_of, metric=metric, lever=lever, tunables=tunables, total=total)
    window = kw.window
    current = window.value or 0.0
    gmv_day = assessment.gmv_current or 0.0
    conf: str | None = None
    if not kw.per_channel:
        used = medians
        volatile = assessment.stability == "volatile"
        bench = benchmark
    else:
        used = channel_medians(kw.channel)
        cv = kw.impressions_cv(as_of)
        conf = confidence_level(
            events=window.events, cv=cv, low_data=window.low_data, tunables=tunables
        )
        volatile = stability(cv, tunables) == "volatile"
        bench = None
        channel_gmv = channel_gmv_per_day(rows, kw.channel, as_of, window.window_days)
        if channel_gmv is not None:
            gmv_day = channel_gmv
    median = {"ctr": used.ctr, "ctor": used.ctor, "aov": used.aov}.get(metric)
    reference, source = reference_for(
        metric,
        shop_median=float(median) if median is not None else None,
        earlier=window.earlier,
        benchmark=bench,
    )
    if reference is None:
        reference, source = current, "current"
    return _KpiBasis(
        channel=kw.channel,
        window=window,
        rows=kw.rows,
        reference=reference,
        source=source or "current",
        medians=used,
        confidence=conf,
        volatile=volatile,
        gmv_per_day=gmv_day,
    )


def _plan_d29(
    funnels: list[ProductFunnel],
    catalog: dict[str, CatalogProduct],
    config: StageDiagnosisConfig,
    *,
    medians: ShopMedians,
    excluded: dict[str, str],
    evidence_by_id: dict[str, list[Evidence]],
    asked: set[str],
    top_k: int,
    discount_cap_set: bool,
    daily: dict[str, list[ProductDay]],
    as_of: date,
    tunables: DiagTunables,
    history: dict[str, LeverHistory],
    calibration: dict[str, CalibrationStats],
    fleet_calibration: dict[str, CalibrationStats],
    listing_facts: dict[str, ListingFacts],
    benchmarks: dict[str, dict[str, float]],
    page_levers: dict[str, PageLevers] | None = None,
    active_bmsm: frozenset[str] = frozenset(),
) -> ShopCardPlan:
    """D29 + D30.2–3 over the catalog (see :func:`plan_shop_cards`).

    D33 quota mode (``tunables.card_quota_mode``; off = everything below is
    skipped): price levers read the stored promotion facts (``page_levers``,
    ``active_bmsm``); a product whose GMV did not fall but whose metric sits
    clearly below the shop median gets an S28B card (:func:`below_shop_metric`:
    KPI = the minimum clamp only, "Độ tin cậy" Thấp, ranked after the GMV-drop
    cards, ``reason_code`` :data:`REASON_BELOW_SHOP_LEVEL`); the Quality-Score
    lever weight is neutral (price levers rank like listing levers); and the
    top candidates are kept per cell instead of per executor type.
    """
    quota_mode = tunables.card_quota_mode
    metric_first = tunables.metric_first
    page_levers = page_levers or {}
    skips: list[Skip] = []
    groups: dict[str, list[CardProposal]] = {
        STATUS_CODE_RULE: [],
        STATUS_CODE_NEEDS_CAP: [],
        STATUS_CODE_NOT_ASKED: [],
    }
    channel_medians: dict[str, ShopMedians] = {}
    shrink_context = (
        ShrinkageContext(
            daily=daily,
            categories={pid: product.category for pid, product in catalog.items()},
            as_of=as_of,
        )
        if metric_first and tunables.shrinkage_on
        else None
    )
    for funnel in funnels:
        pid = funnel.product_id
        if pid in excluded:
            continue
        assessment = assess_product(pid, daily.get(pid, []), as_of=as_of, tunables=tunables)
        below = False
        # D39.1: metric-first (default) -- any funnel metric beyond its own band;
        # gmv_first keeps the D29.2 gate (GMV fell beyond its band). D41.2: CTR /
        # CTOR shrunk toward the category first (``kpi_shrinkage``, default on).
        drops = (
            metric_trigger(
                daily.get(pid, []),
                as_of=as_of,
                tunables=tunables,
                assessment=assessment,
                shrinkage=shrink_context.for_product(pid) if shrink_context else None,
            )
            if metric_first
            else None
        )
        drop = drops.target if drops is not None else None
        if drop is not None:
            metric = drop.metric
        elif not metric_first and assessment.candidate and assessment.target_metric is not None:
            metric = assessment.target_metric
        else:
            s28b_metric = (
                below_shop_metric(assessment, medians)
                if quota_mode and assessment.status == STATUS_NO_DROP
                else None
            )
            if s28b_metric is None:
                skips.append(Skip(pid, funnel.title, _skip_reason(assessment, metric_first)))
                continue
            metric, below = s28b_metric, True
        window = assessment.metrics[metric]
        current = window.value
        if current is None or current <= 0 or window.band_pct is None:
            skips.append(Skip(pid, funnel.title, "d29:no_current_value"))
            continue
        evidence = evidence_by_id.get(pid, [])
        status, angles, bmsm = _d29_levers(
            metric,
            evidence=evidence,
            asked=pid in asked,
            discount_cap_set=discount_cap_set,
            funnel=funnel,
            config=config,
            levers=page_levers.get(pid, NO_LEVERS) if quota_mode else NO_LEVERS,
            bmsm_running=quota_mode and pid in active_bmsm,
        )
        if status is None:
            skips.append(Skip(pid, funnel.title, f"d29:{SKIP_NO_LEVER}"))
            continue
        product = catalog.get(pid) or CatalogProduct(pid, funnel.title)
        facts = listing_facts.get(pid) or ListingFacts(
            title=product.title, category=product.category, tiktok_asked=pid in asked
        )
        quality = quality_score(facts, evidence)
        gaps = compute_gaps(funnel, medians, config)
        if below:
            reason = ""
        elif drop is not None and drops is not None:
            reason = metric_first_reason(drop, drops)
        else:
            reason = d29_reason(assessment, metric)
        rows = daily.get(pid, [])
        for angle in angles:
            lever = LEVER_CODES[angle]
            # D32: the KPI is read on the channel the lever acts on.
            basis = _kpi_basis(
                rows,
                as_of=as_of,
                metric=metric,
                lever=lever,
                tunables=tunables,
                total=window,
                assessment=assessment,
                medians=medians,
                channel_medians=lambda ch: _channel_medians(
                    ch, funnels, excluded, daily, cache=channel_medians, as_of=as_of, config=config
                ),
                benchmark=(benchmarks.get(pid) or {}).get(metric),
            )
            current = basis.window.value or 0.0
            card_reason = reason
            kpi_tunables = tunables
            if below:
                # S28B: only when the metric is clearly below the shop's level on
                # the lever's own channel; the KPI is the minimum clamp alone.
                channel_median = _median_of(basis.medians, metric)
                if not _clearly_below(current, basis.window.band_pct, channel_median):
                    continue
                card_reason = below_shop_reason(
                    metric, basis.channel, current, channel_median or 0.0
                )
                kpi_tunables = replace(tunables, kpi_max_band_mult=tunables.kpi_min_band_mult)
            target_gap = _target_gap(
                metric, current, basis.medians, basis.window.earlier, basis.window.low_data
            )
            trigger = Trigger.OWN_TREND if basis.source == "own_earlier" else Trigger.SHOP_MEDIAN
            counts = window_counts(basis.rows, as_of, basis.window.window_days)
            last = FunnelWindow(
                days=counts.days,
                impressions=Decimal(str(counts.impressions)),
                clicks=Decimal(str(counts.clicks)),
                sku_orders=Decimal(str(counts.orders)),
                gmv=Decimal(str(counts.gmv)),
            )
            prediction = predict(
                lever,
                quality.gap(lever),
                shop=calibration.get(lever),
                fleet=fleet_calibration.get(lever),
            )
            kpi = kpi_target(
                metric=metric,
                current=current,
                band_pct=basis.window.band_pct or 0.0,
                reference=basis.reference,
                window_days=basis.window.window_days,
                tunables=kpi_tunables,
                volatile=basis.volatile,
                low_data=basis.window.low_data,
                predicted=prediction.metric_range(current),
                channel=basis.channel,
            )
            gmv_day = basis.gmv_per_day
            recoverable = Decimal(str(gmv_day * max(kpi.target / current - 1, 0.0)))
            low, high = gmv_range_per_month(gmv_day, current, kpi.target_min, kpi.target_max)
            lever_history = history.get(lever)
            penalty = lever_history.reason_penalty if lever_history is not None else Decimal(1)
            # D39.1: a metric-first card ranks on what its metric's fall costs.
            ranked_on = (
                Decimal(str(round(drop.gmv_cost_per_day, 4)))
                if drop is not None and not below
                else recoverable
            )
            ranking = (
                ranked_on
                * Decimal(str(prediction.factor))
                * penalty
                # D33 quota mode: price levers rank like listing levers.
                * Decimal(str(1.0 if quota_mode else lever_weight(quality, lever)))
            )
            diag = Diagnosis(
                product_id=pid,
                title=funnel.title,
                label=Label.AOV if metric == "aov" else Label.CTOR,
                trigger=trigger,
                branch=METRIC_BRANCH[metric],
                angle=angle,
                gap=target_gap,
                gaps=gaps,
                evidence=tuple(e for e in evidence if codes_for_angle(angle, [e.code])),
                rank_score=target_gap.gap * funnel.gmv_28d,
                channel_scope=funnel.channel_scope,
                bmsm=bmsm,
            )
            proposal = _rule_proposal(diag, card_reason, config)
            if status != STATUS_CODE_RULE:
                proposal = replace(
                    proposal,
                    status=status,
                    lever_confirmed=False,
                    lever_detail=(
                        "Giảm giá sản phẩm, sau khi shop đặt mức giảm giá tối đa"
                        if status == STATUS_CODE_NEEDS_CAP
                        else f"{ANGLE_ACTION[angle]}, nếu TikTok chỉ ra lỗi"
                    ),
                )
            groups[status].append(
                replace(
                    proposal,
                    gap=max(target_gap.gap, Decimal(0)),
                    recoverable_gmv_per_day=recoverable,
                    recoverable_basis={
                        "label": RECOVERABLE_LABEL,
                        "stage_rate": metric,
                        "current_rate": current,
                        "reference_rate": kpi.target,
                        "reference": basis.source,
                        "volume_per_day": float(_volume_per_day(metric, last)),
                        "aov": None if last.aov is None else float(last.aov),
                        "window_days": basis.window.window_days,
                        "channel": basis.channel,
                    },
                    history=lever_history,
                    assessment=assessment,
                    target_metric=metric,
                    kpi=kpi,
                    kpi_confidence=CONFIDENCE_LOW if below else basis.confidence,
                    reason_code=REASON_BELOW_SHOP_LEVEL if below else None,
                    metric_trigger=drops if drop is not None and not below else None,
                    quality=quality,
                    prediction=prediction,
                    gmv_estimate=(low, high),
                    d29_ranking_value=ranking,
                )
            )

    def _key(p: CardProposal) -> tuple:
        level = p.assessment.stability if p.assessment is not None else "unknown"
        value = p.ranking_gmv_per_day
        if metric_first:
            # D39.1: by the GMV the target metric's fall costs; stability breaks ties.
            return (
                p.reason_code is not None,
                value is None,
                -(value or Decimal(0)),
                STABILITY_ORDER.get(level, 9),
                -p.rank_score,
                p.product_id,
                LEVER_CODES[p.lever],
            )
        return (
            # D33: S28B cards after every GMV-drop card (always False when off).
            p.reason_code is not None,
            STABILITY_ORDER.get(level, 9),
            value is None,
            -(value or Decimal(0)),
            -p.rank_score,
            p.product_id,
            LEVER_CODES[p.lever],
        )

    # D39.1 seam: products with no metric drop get a card only from a simulated
    # winner (D38), which lives outside the backend -- none until it is stored.
    groups[STATUS_CODE_RULE].extend(growth_candidates(skips=skips, as_of=as_of))
    ordered: list[CardProposal] = []
    for status_code in (STATUS_CODE_RULE, STATUS_CODE_NEEDS_CAP, STATUS_CODE_NOT_ASKED):
        ordered.extend(sorted(groups[status_code], key=_key))
    # D29.4: one proposal per (product, lever); a product's proposals share its metric.
    seen: set[tuple[str, Angle]] = set()
    unique: list[CardProposal] = []
    for proposal in ordered:
        key = (proposal.product_id, proposal.lever)
        if key in seen:
            continue
        seen.add(key)
        unique.append(proposal)
    if quota_mode:
        per_cell = tunables.card_quota_per_cell * QUOTA_CANDIDATES_PER_CELL_MULT
        kept = keep_top_per_cell(unique, max(per_cell, 1))
    else:
        kept = keep_top_per_type(unique, top_k)
    per_product: dict[str, int] = {}
    for proposal in kept:
        per_product[proposal.product_id] = per_product.get(proposal.product_id, 0) + 1
    kept = [replace(p, sibling_cards=per_product[p.product_id] - 1) for p in kept]
    return ShopCardPlan(
        proposals=kept,
        medians=medians,
        skips=skips,
        excluded=excluded,
        products_scored=len(funnels),
        overflow=len(unique) - len(kept),
    )
