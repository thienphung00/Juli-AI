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
3. keep the top ``top_k`` (30, D24.17); one proposal per product.

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

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

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
from juli_backend.services.optimize_product.diagnosis import (
    BRANCH_ORDER,
    Angle,
    Branch,
    Diagnosis,
    Gap,
    Label,
    Skip,
    Trigger,
)
from juli_backend.services.optimize_product.funnel import FunnelWindow, ProductFunnel, ShopMedians
from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    derive_local_evidence,
    is_title_code,
    listing_signals_from_product,
)
from juli_backend.services.optimize_product.shop_report import (
    STATUS_NEEDS_CAP,
    STATUS_NOT_ASKED,
    STATUS_RULE,
)

#: Version of the card payload shape; bump when ``diagnosis`` changes shape.
PAYLOAD_VERSION = "adr106-v1"

#: Ranked proposals kept per shop (D24.17: nightly candidates top 30; was 10).
DEFAULT_TOP_K = 30

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
    Branch.CARD: "Hiển thị → Nhấp (thẻ sản phẩm)",
    Branch.PAGE: "Nhấp → Đặt hàng (trang sản phẩm)",
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

    @property
    def ranking_gmv_per_day(self) -> Decimal | None:
        """Recoverable GMV × the lever's history weight — what the ranking sorts on."""
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
RECOVERABLE_LABEL = "Ước tính theo quy tắc (chưa phải mô hình)"


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
    """Gift / not-for-sale titles and listings not on sale are not diagnosed."""
    signals = listing_signals_from_product({"title": product.title}, config)
    if signals.excluded_reason:
        return signals.excluded_reason
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


def plan_shop_cards(
    funnels: list[ProductFunnel],
    catalog: dict[str, CatalogProduct],
    config: StageDiagnosisConfig,
    *,
    top_k: int = DEFAULT_TOP_K,
    discount_cap_set: bool = False,
    last30: dict[str, FunnelWindow] | None = None,
    history: dict[str, LeverHistory] | None = None,
) -> ShopCardPlan:
    """Score the catalog, compose the ranked proposals, keep the top ``top_k``.

    ``history`` (lever code -> :class:`LeverHistory`, D24.6) weights the
    ranking; a lever absent from it is neutral.
    """
    excluded: dict[str, str] = {}
    evidence_by_id: dict[str, list[Evidence]] = {}
    for funnel in funnels:
        product = catalog.get(funnel.product_id) or CatalogProduct(funnel.product_id, funnel.title)
        reason = exclusion_reason(product, config)
        if reason:
            excluded[funnel.product_id] = reason
        evidence_by_id[funnel.product_id] = title_evidence(product.title, config)

    medians, diagnoses, skips = diagnose_all(
        funnels,
        evidence_by_id,
        excluded,
        config,
        asked=set(),
        discount_cap_set=discount_cap_set,
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
    kept = [replace(p, rank=index) for index, p in enumerate(ordered[:top_k], start=1)]
    return ShopCardPlan(
        proposals=kept,
        medians=medians,
        skips=skips,
        excluded=excluded,
        products_scored=len(funnels),
        overflow=max(len(ordered) - top_k, 0),
    )
