"""Test cards: the seller-facing shape of a diagnosis, with hedged copy.

A :class:`TestCard` is what the nightly pass would emit as an Optimize Card
and what the catalog scan writes to ``cards.json``. Copy follows the fixed
vocabulary: the Main KPI (CTOR or AOV) with its value, one *lý do* sentence
naming the trigger that fired (shop median **or** own trend, never both),
one *góc độ* with its evidence, and the metric the impact reading will be
scored on. Numbers are always "ước tính"; nothing claims TikTok's authority
unless the evidence source is TikTok.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.diagnosis import (
    Angle,
    Diagnosis,
    Gap,
    Label,
    Trigger,
    rank_diagnoses,
)
from juli_backend.services.optimize_product.listing_signals import EvidenceSource

#: Which metric the impact reading is scored on, per angle (ADR-106
#: Consequences → impact reader fix). Primary first.
MEASURE_BY_ANGLE: dict[Angle, tuple[str, ...]] = {
    Angle.ANH_BIA: ("ctr", "click_order_rate"),
    Angle.TIEU_DE: ("ctr", "impressions"),
    Angle.MO_TA: ("click_order_rate",),
    Angle.GIAM_GIA: ("click_order_rate", "gmv"),
    Angle.MUA_NHIEU_GIAM_NHIEU: ("aov", "items_per_order"),
}

ANGLE_ACTION = {
    Angle.ANH_BIA: "Thay ảnh bìa",
    Angle.TIEU_DE: "Viết lại tiêu đề",
    Angle.MO_TA: "Viết lại mô tả",
    Angle.GIAM_GIA: "Tạo giảm giá sản phẩm 30 ngày",
    Angle.MUA_NHIEU_GIAM_NHIEU: "Tạo mua nhiều giảm nhiều một bậc",
}


def _pct(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)} %"


def _ratio(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{(value * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} %"


def _vnd(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,} ₫".replace(",", ".")


@dataclass(frozen=True)
class TestCard:
    product_id: str
    title: str
    main_kpi: str
    main_kpi_value: str
    reason: str
    trigger: str
    angle: str
    action: str
    evidence: list[dict]
    measure: list[str]
    other_angles: list[str]
    caveats: list[str]
    rank: int
    rank_score: str
    within_open_slots: bool
    channel_scope: str

    def to_dict(self) -> dict:
        return asdict(self)


def gap_reason_sentence(gap: Gap, trigger: Trigger, *, full_median_peers: int = 5) -> str:
    """One sentence for one fired gap — the shared builder of every *lý do*.

    Under ``full_median_peers`` products above the floor the sentence names the
    peer count instead of claiming a "trung bình shop" (ADR-106 amendment).
    """
    kpi = {"ctr": "CTR thẻ sản phẩm", "ctor": "CTOR", "aov": "AOV"}.get(
        gap.factor, gap.factor.upper()
    )
    pct = _pct(gap.gap)
    if trigger is Trigger.SHOP_MEDIAN:
        if gap.median_peers < full_median_peers:
            return (
                f"{kpi} ước tính thấp hơn {pct} so với {gap.median_peers} sản phẩm đủ dữ liệu "
                "của shop trong 14 ngày qua"
            )
        return f"{kpi} ước tính thấp hơn {pct} so với trung bình shop trong 14 ngày qua"
    return f"{kpi} ước tính giảm {pct} so với 4 tuần trước"


def reason_sentence(diag: Diagnosis, *, full_median_peers: int = 5) -> str:
    """One sentence, one trigger. Never a blended number."""
    return gap_reason_sentence(diag.gap, diag.trigger, full_median_peers=full_median_peers)


def angle_sentence(diag: Diagnosis) -> str:
    action = ANGLE_ACTION[diag.angle]
    if diag.angle is Angle.MUA_NHIEU_GIAM_NHIEU and diag.bmsm:
        pct = (
            f"khoảng {diag.bmsm.percent} % (cần trần giảm giá của shop để chốt)"
            if diag.bmsm.percent_is_estimate
            else f"{diag.bmsm.percent} %"
        )
        return f"{action}: mua từ {diag.bmsm.threshold_items} món giảm {pct}, 30 ngày"
    if diag.angle is Angle.GIAM_GIA:
        return f"{action}; độ sâu do rule tính trong trần giảm giá của shop"
    if not diag.evidence:
        return action
    tiktok = [e for e in diag.evidence if e.source is EvidenceSource.TIKTOK]
    local = [e for e in diag.evidence if e.source is EvidenceSource.LOCAL]
    parts = []
    if tiktok:
        parts.append("TikTok đánh dấu: " + "; ".join(e.how_to_solve or e.code for e in tiktok))
    if local:
        parts.append("Juli đánh giá: " + "; ".join(e.detail or e.code for e in local))
    return f"{action}. " + " ".join(parts)


NOT_ENOUGH_DATA = "chưa đủ dữ liệu"


def main_kpi_value(diag: Diagnosis) -> str:
    """The card's Main KPI value, or ``NOT_ENOUGH_DATA`` below its ADR-077 floor.

    A CTOR built on a handful of clicks reads as 0,00 %, which a seller takes
    for a fact; below the floor the card says so instead (Amendment 3).
    """
    if diag.label is Label.CTOR:
        gap = diag.gaps["ctor"]
        return _ratio(gap.value) if gap.cleared_floor else NOT_ENOUGH_DATA
    gap = diag.gaps["aov"]
    return _vnd(gap.value) if gap.cleared_floor else NOT_ENOUGH_DATA


def build_cards(diagnoses: list[Diagnosis], config: StageDiagnosisConfig) -> list[TestCard]:
    """Rank, mark the open slots, and render copy for every diagnosis."""
    cards: list[TestCard] = []
    for index, diag in enumerate(rank_diagnoses(diagnoses), start=1):
        kpi_value = main_kpi_value(diag)
        cards.append(
            TestCard(
                product_id=diag.product_id,
                title=diag.title,
                main_kpi="CTOR" if diag.label is Label.CTOR else "AOV",
                main_kpi_value=kpi_value,
                reason=reason_sentence(diag, full_median_peers=config.full_median_peers),
                trigger=diag.trigger.value,
                angle=diag.angle.value,
                action=angle_sentence(diag),
                evidence=[
                    {
                        "code": e.code,
                        "source": e.source.value,
                        "detail": e.detail,
                        "how_to_solve": e.how_to_solve,
                    }
                    for e in diag.evidence
                ],
                measure=list(MEASURE_BY_ANGLE[diag.angle]),
                other_angles=[a.value for a in diag.other_angles],
                caveats=list(diag.caveats),
                rank=index,
                rank_score=str(diag.rank_score.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                within_open_slots=index <= config.max_open_cards_per_shop,
                channel_scope=diag.channel_scope,
            )
        )
    return cards
