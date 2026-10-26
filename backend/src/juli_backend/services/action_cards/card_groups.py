"""Optimise in groups, each with a randomised delayed control (D34 / D39.3, fast track P30).

Cards are chosen *because* a product just dropped, so before/after alone over-credits a
lever (regression to the mean), and a shop optimising a few products cannot tell a
working lever from luck (platform algorithm, season, competitors). Randomisation is the
only design that removes both. In the card system:

1. **Group (D34.1).** Optimize Product drafts that share a target metric × lever × KPI
   channel within one shop (``ctr|cover_image|product_card``) -- D33's cells split by
   lever, D32's channels.
2. **Draw (D34.2).** When at least :data:`MIN_GROUP_SIZE` (3) eligible drafts of one
   key, from distinct products, are not in a group of that key launched within
   :data:`MEMBER_MEMORY_DAYS` (44), a group is launched: the
   products are shuffled with a recorded random seed and ``round(n / 3)`` of them are
   the **delayed control** (:func:`assign_arms`, reproducible from the seed). A control
   card is held (``suppressed_reason = group_control``) and released
   :data:`CONTROL_DELAY_DAYS` (14) days after launch -- no seller loses the card for
   good. Fewer than 3: nothing changes for those drafts.
3. **Wave (D34.3).** The treated cards surface within ~:data:`LAUNCH_WINDOW_DAYS` (3)
   days: during the window they go first among the drafts; the emission budget (daily
   slots, or D33's per-cell quota) still decides how many surface each day.
4. **Verdict (D34.4/5).** At day 14 (the newest analytics day ≥ launch + 13) every
   member's target metric is read on the group's channel over the 14 days from launch
   against the 14 days before (``lever_flows.measurement``'s window totals), the change
   in %; verdict = median change of the treated − median change of the control, a 90 %
   bootstrap interval (seeded by the group's seed), graded with D31.7's rule against the
   interval's half-width (``clear`` / ``likely`` / ``noise``). By assignment
   (intent-to-treat); the approved-only comparison is a secondary number. "Sơ bộ" with
   ≥ 3 treated + ≥ 2 control measured products, no label from ≥ 5 + ≥ 3, else
   "Chưa đủ cơ sở" (no numbers). **D41.3 (P31, :mod:`.group_stats`):** each change is
   CUPED-adjusted by the product's own previous 14 days; with fewer than 5 controls a
   permutation test over the random assignment must also reject (p ≤ 0.10); and when
   the rule's simulated false-alarm rate on the group's own no-effect data is above
   15 % (T3.1), the verdict makes no strength claim and reads "Đang đo" -- re-gated
   weekly to day 56 as the control's untouched data join the null pool.
5. **Who sees it (D34.8).** Ops sees groups, arms, seeds, intervals
   (:func:`group_views`); the seller one plain sentence on the cards of the same group
   key once a verdict exists (:func:`seller_sentences`), e.g. "Nhóm 6 sản phẩm đổi ảnh
   bìa: CTR tăng khoảng 7 % so với các sản phẩm chưa đổi".

6. **Ops groups and more metrics (D45, fast track P36 -- Ops only).** Juli Ops can
   create a group by hand (:func:`create_ops_group`) for a lever Juli never proposes
   as a card -- ``pack_option``, a new pack / variant option the owner creates on
   TikTok (Juli never writes it) -- with the same seeded ≈ 1/3 control draw. Such a
   group has no cards, declares its primary metric (default AOV, all channels) and
   reads the product-card CTR as a **guard**: Ops warns when the treated products'
   CTR falls more than 15 % against the control (``group_guard_ctr_drop``), even if
   AOV rose. Every group's verdict also carries all-channel AOV and items per order
   (``verdict.metrics``, same rule: 90 % interval, false-alarm replay, pre-period
   adjustment). D45.6: the pre-period adjustment follows the group size
   (:func:`.group_stats.adjust_changes`: the P31 θ below 15 measured products (D47.1),
   two pre-period windows from 15, ``group_two_window_min``). Each group shows its
   weekly-drift floor and the traffic needed (:mod:`.group_design`) and an optional
   one-line "lý do chọn thử nghiệm" (``design.reason``). The seller never sees an
   Ops group: no seller sentence, no card.
7. **EB-shrunk lift, Ops only (D52, fast track P45).** Each verdict comparison also
   stores ``eb`` (:func:`.group_stats.shrink_lift`): the observed log-lift pulled
   toward a prior for the lever type -- the default N(0, 0.15²) when measured (the
   pipeline runs in the shop's own scope and cannot read other shops). The Ops groups
   page re-shrinks every comparison with the pooled prior of measured groups of the
   same lever × metric × channel across all shops (:func:`lift_draws`, read through
   the ``juli_ops``-only ``ops_group_lift_draws()``; :func:`apply_pooled_eb`, leave-
   one-out, a shop's groups combined first), when there are ≥ ``group_eb_min_groups``
   draws. Only aggregate numbers leave it (prior mean, spread, number of shops). The
   label, the strength and the seller's sentence never read ``eb``. D76 / D11
   (ADR-116 §3, migration 107): the draws come only from shops holding an open
   ``pooled_training`` grant, and a viewed shop without one gets no pooled prior at all
   -- its own data under the default N(0, sd²), labelled ``own`` (``PRIOR_OWN``).
8. **Net of cancelled / refunded orders, Ops only (D55.1, fast track P46,
   :mod:`.group_net`).** TikTok's GMV includes orders later cancelled or refunded. When
   the shop's own orders cover every day a verdict reads, all-channel AOV and items per
   order are read on net values (the analytics day scaled by that day's cancel / refund
   share of the product's orders) -- ``verdict.metrics``, an Ops group's primary, the
   false-alarm replay and the EB lift -- and the TikTok-GMV reading is stored beside
   each one (``gross``). A card group's primary (behind the seller's sentence) stays on
   TikTok's GMV; its net reading is ``verdict.net``. ``verdict.basis`` says which basis
   ran; without the orders every label says "gồm đơn huỷ/hoàn, theo TikTok".

Switch: the team tunable ``card_groups`` (``DiagTunables.groups_enabled``): unset
follows D33's quota mode (on only when the quota mode is on); off = no card is drawn
into a group and the emission budget is unchanged -- only groups already made (e.g.
by Ops) are still measured at day 14.
"""

from __future__ import annotations

import json
import logging
import random
import secrets
import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_groups import (
    ARM_CONTROL,
    ARM_TREATED,
    GROUP_MEASURED,
    GROUP_OPEN,
    CardGroup,
    CardGroupMember,
)
from juli_backend.models.models import ActionCard, AnalyticsPerformanceInterval, Product
from juli_backend.services.action_cards.emission_budget import SUPPRESSED_REASON_GROUP_CONTROL
from juli_backend.services.action_cards.group_design import (
    DRIFT_SIGMA_WEEK,
    drift_floor,
    traffic_needed,
)
from juli_backend.services.action_cards.group_net import (
    BASIS_GROSS,
    BASIS_NET,
    BASIS_TEXT_VI,
    OrderDay,
    basis_label,
    load_order_days,
    needs_net,
    net_rows,
    order_coverage,
)
from juli_backend.services.action_cards.group_stats import (
    ALPHA,
    EB_MIN_GROUPS,
    EB_PRIOR_SD,
    INTERVAL_HIGH,
    INTERVAL_LOW,
    TWO_WINDOW_MIN_PRODUCTS,
    FalseAlarm,
    LogLift,
    Prior,
    Unit,
    adjust_changes,
    assess,
    default_prior,
    estimate_prior,
    false_alarm_rate,
    log_lift_of,
    null_pool,
    own_data_prior,
    shrink_lift,
    unit_from_change,
)
from juli_backend.services.change_strength import STRENGTH_LABELS_VI
from juli_backend.services.optimize_product.tunables import DiagTunables

logger = logging.getLogger(__name__)


MIN_GROUP_SIZE = 3
CONTROL_SHARE = 1 / 3
LAUNCH_WINDOW_DAYS = 3
CONTROL_DELAY_DAYS = 14
MEASURE_DAYS = 14
#: How long a product stays tied to its group (it never joins a second group of the
#: same key in that time): the release, plus a month for the card to surface.
MEMBER_MEMORY_DAYS = CONTROL_DELAY_DAYS + 30
#: A product needs this many days with data in each window to be measured.
MIN_DAYS_MEASURED = 7
BOOTSTRAP_SAMPLES = 2000
#: The interval: p5–p95 of the bootstrap (90 %, D41.3; P30 used 80 %).
INTERVAL_LEVEL = round(INTERVAL_HIGH - INTERVAL_LOW, 2)

#: D34.4 thresholds (treated, control) of measured products.
PRELIMINARY_MIN = (3, 2)
FULL_MIN = (5, 3)
LABEL_PRELIMINARY = "Sơ bộ"
LABEL_NOT_ENOUGH = "Chưa đủ cơ sở"
#: D41.3 / T3.1: the group's simulated false-alarm rate is above 15 % -- no strength claim.
LABEL_MEASURING = "Đang đo"
#: T3.1: a "Đang đo" group is re-gated weekly with the latest data, until this many
#: days after launch (four 14-day windows: the controls are usually approved by then).
RECHECK_EVERY_DAYS = 7
RECHECK_UNTIL_DAYS = 56

_WORKFLOW_KEY = "optimize_product_2"
_ACTIVE = "active"
_SHOP_UTC_OFFSET = timedelta(hours=7)

#: Card metric -> ``lever_flows.measurement.WindowTotals.value`` name.
MEASURE_METRIC: Mapping[str, str] = {
    "impressions": "impressions",
    "ctr": "ctr",
    "ctor": "conversion_rate",
    "aov": "gmv_per_order",
    #: D45.2 (P36): items sold / SKU orders (computed here, not a WindowTotals value).
    "items_per_order": "items_per_order",
}

METRIC_LABELS_VI: Mapping[str, str] = {
    "impressions": "Lượt hiển thị",
    "ctr": "CTR",
    "ctor": "CTOR",
    "aov": "AOV",
    "items_per_order": "Số món mỗi đơn",
}
LEVER_LABELS_VI: Mapping[str, str] = {
    "cover_image": "Ảnh bìa",
    "title": "Tiêu đề",
    "description": "Mô tả",
    "product_discount": "Giảm giá sản phẩm",
    "flash_sale": "Flash sale",
    "shipping_discount": "Giảm phí vận chuyển",
    "buy_more_save_more": "Mua nhiều giảm nhiều",
    #: D45.1 (P36): a new pack / variant option (e.g. 2× at −5 % per unit) the owner
    #: creates on TikTok. Never a card -- only an Ops group.
    "pack_option": "Quy cách mới",
}
CHANNEL_LABELS_VI: Mapping[str, str] = {
    "product_card": "Thẻ sản phẩm",
    "video": "Video",
    "live": "LIVE",
    "total": "tất cả kênh",
}
#: Seller copy: what the group did, and what moved (plain words).
_LEVER_DID_VI: Mapping[str, str] = {
    "cover_image": "đổi ảnh bìa",
    "title": "đổi tiêu đề",
    "description": "đổi mô tả",
    "product_discount": "giảm giá",
    "flash_sale": "chạy flash sale",
    "shipping_discount": "giảm phí vận chuyển",
    "buy_more_save_more": "thêm mua nhiều giảm nhiều",
    "pack_option": "thêm quy cách mới",
}
_METRIC_MOVED_VI: Mapping[str, str] = {
    "impressions": "lượt hiển thị",
    "ctr": "lượt nhấp",
    "ctor": "đơn hàng trên mỗi lượt nhấp",
    "aov": "giá trị mỗi đơn",
    "items_per_order": "số món mỗi đơn",
}

#: D45 (P36): who made a group.
SOURCE_CARDS = "cards"
SOURCE_OPS = "ops"
#: D45.2: every group's verdict also reads these (metric, channel) -- all channels.
EXTRA_METRICS: tuple[tuple[str, str], ...] = (("aov", "total"), ("items_per_order", "total"))
#: D45.2: the guard of a group whose primary metric is not CTR (e.g. pack → AOV).
GUARD_METRIC: tuple[str, str] = ("ctr", "product_card")
#: D45.2: warn when the guard's treated − control change is below −this (points of %).
GUARD_DROP_PCT = 15.0
#: D45.3: the "lý do chọn thử nghiệm" is one line.
REASON_MAX_CHARS = 200
#: An Ops group: this many products at most (a whole small shop).
OPS_GROUP_MAX_PRODUCTS = 60
#: D45.8: an Ops group can be drawn within order-volume strata (high / low), each
#: stratum drawn like a small group (3 products -> 2 treated + 1 control).
STRATUM_HIGH = "high"
STRATUM_LOW = "low"
STRATIFY_ORDERS_DAYS = 30
STRATIFIED_BY = "orders_30d"
#: Each stratum needs this many products (a stratum of 3 = 2 treated + 1 control).
STRATUM_MIN_PRODUCTS = MIN_GROUP_SIZE
CHANNELS: tuple[str, ...] = ("product_card", "video", "live", "total")


# =========================================================================== pure


@dataclass(frozen=True)
class GroupKey:
    """Target metric × lever × KPI channel (D34.1)."""

    metric: str
    lever: str
    channel: str

    @property
    def text(self) -> str:
        return f"{self.metric}|{self.lever}|{self.channel}"

    @property
    def label_vi(self) -> str:
        return (
            f"{METRIC_LABELS_VI.get(self.metric, self.metric)} · "
            f"{LEVER_LABELS_VI.get(self.lever, self.lever)} · "
            f"{CHANNEL_LABELS_VI.get(self.channel, self.channel)}"
        )

    @classmethod
    def parse(cls, text: str) -> GroupKey:
        metric, lever, channel = text.split("|", 2)
        return cls(metric, lever, channel)


@dataclass(frozen=True)
class GroupDesign:
    """``card_groups.design`` (D45, migration 092); ``None`` in the row = a card group."""

    source: str = SOURCE_CARDS
    #: The one-line "lý do chọn thử nghiệm" (D45.3), typed in Ops.
    reason: str | None = None
    #: Read the product-card CTR as a guard (D45.2).
    guard: bool = False
    created_by: str | None = None
    #: D45.8: product -> ``high`` / ``low`` order-volume stratum (``None`` = one draw).
    strata: Mapping[str, str] | None = None
    #: D45.8: the 30-day all-channel SKU orders behind the strata (shown in Ops).
    strata_orders: Mapping[str, float] | None = None

    @classmethod
    def of(cls, group: CardGroup) -> GroupDesign:
        raw = group.design if isinstance(group.design, dict) else {}
        reason = raw.get("reason")
        return cls(
            source=SOURCE_OPS if raw.get("source") == SOURCE_OPS else SOURCE_CARDS,
            reason=reason if isinstance(reason, str) and reason.strip() else None,
            guard=bool(raw.get("guard")),
            created_by=raw.get("created_by") if isinstance(raw.get("created_by"), str) else None,
            strata=_str_map(raw.get("strata")),
            strata_orders=_num_map(raw.get("strata_orders")),
        )

    @property
    def ops(self) -> bool:
        return self.source == SOURCE_OPS

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "reason": self.reason,
            "guard": self.guard,
            "created_by": self.created_by,
            "strata": dict(self.strata) if self.strata else None,
            "strata_orders": dict(self.strata_orders) if self.strata_orders else None,
            "stratified_by": STRATIFIED_BY if self.strata else None,
        }


def _str_map(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    out = {str(k): v for k, v in raw.items() if isinstance(v, str)}
    return out or None


def _num_map(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    out = {str(k): float(v) for k, v in raw.items() if isinstance(v, int | float)}
    return out or None


def metric_specs(key: GroupKey, design: GroupDesign) -> list[tuple[str, str]]:
    """The extra (metric, channel) pairs a group reads besides its primary (D45.2)."""
    specs = [spec for spec in EXTRA_METRICS if spec != (key.metric, key.channel)]
    if design.guard and GUARD_METRIC != (key.metric, key.channel):
        specs.append(GUARD_METRIC)
    return specs


def spec_key(metric: str, channel: str) -> str:
    return f"{metric}|{channel}"


def _payload(card: ActionCard) -> dict[str, Any]:
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def payload_group_key(payload: Mapping[str, Any]) -> tuple[GroupKey, str] | None:
    """(group key, TikTok product id) of a D29 Optimize Product card payload, else ``None``."""
    metric = payload.get("target_metric")
    diagnosis = payload.get("diagnosis")
    kpi = payload.get("kpi")
    if not isinstance(metric, str) or not isinstance(diagnosis, Mapping):
        return None
    if not isinstance(kpi, Mapping):
        return None
    lever = diagnosis.get("lever")
    lever_code = lever.get("code") if isinstance(lever, Mapping) else None
    product = diagnosis.get("tiktok_product_id")
    if not isinstance(lever_code, str) or not product:
        return None
    channel = kpi.get("channel")
    channel = channel if isinstance(channel, str) and channel else "total"
    return GroupKey(metric, lever_code, channel), str(product)


def card_group_key(card: ActionCard) -> tuple[GroupKey, str] | None:
    """(group key, product) of an Optimize Product card with a D29 KPI, else ``None``."""
    if card.workflow_key != _WORKFLOW_KEY:
        return None
    return payload_group_key(_payload(card))


def control_count(n: int) -> int:
    """≈ 1/3 of ``n`` products, at least 1 (a group needs ≥ :data:`MIN_GROUP_SIZE`)."""
    if n < MIN_GROUP_SIZE:
        return 0
    return max(1, round(n * CONTROL_SHARE))


def assign_arms(product_ids: Iterable[str], seed: int) -> dict[str, str]:
    """Product -> ``treated`` / ``control``: the sorted ids shuffled with ``seed``,
    the first :func:`control_count` are the control. Same ids + seed = same arms."""
    order = sorted(set(product_ids))
    rng = random.Random(seed)
    rng.shuffle(order)
    controls = set(order[: control_count(len(order))])
    return {pid: (ARM_CONTROL if pid in controls else ARM_TREATED) for pid in order}


def order_strata(orders: Mapping[str, float]) -> dict[str, str]:
    """D45.8: product -> ``high`` / ``low`` by order volume: the busier half (rounded
    up) is ``high``; ties by product id, so the split is reproducible (pure)."""
    ranked = sorted(orders, key=lambda p: (-float(orders[p]), p))
    cut = (len(ranked) + 1) // 2
    return {p: (STRATUM_HIGH if i < cut else STRATUM_LOW) for i, p in enumerate(ranked)}


def assign_arms_stratified(strata: Mapping[str, str], seed: int) -> dict[str, str]:
    """D45.8: :func:`assign_arms` within each stratum -- the stratum's sorted ids shuffled
    with ``(seed, stratum)``, its first :func:`control_count` the control. A 3 + 3 split
    gives 2 treated + 1 control in each. Same strata + seed = same arms."""
    out: dict[str, str] = {}
    for name in sorted(set(strata.values())):
        order = sorted(p for p, s in strata.items() if s == name)
        rng = random.Random(f"{seed}:{name}")
        rng.shuffle(order)
        controls = set(order[: control_count(len(order))])
        out.update({p: (ARM_CONTROL if p in controls else ARM_TREATED) for p in order})
    return out


def new_seed() -> int:
    """A fresh 31-bit seed (recorded on the group, so the draw can be replayed)."""
    return secrets.randbits(31)


def _label(n_treated: int, n_control: int) -> str | None:
    """``None`` (full), ``Sơ bộ`` or ``Chưa đủ cơ sở`` from the measured counts."""
    if n_treated >= FULL_MIN[0] and n_control >= FULL_MIN[1]:
        return None
    if n_treated >= PRELIMINARY_MIN[0] and n_control >= PRELIMINARY_MIN[1]:
        return LABEL_PRELIMINARY
    return LABEL_NOT_ENOUGH


def compare(
    treated: Sequence[float],
    control: Sequence[float],
    *,
    seed: int,
    samples: int = BOOTSTRAP_SAMPLES,
    false_alarm: FalseAlarm | None = None,
) -> dict[str, Any]:
    """Median change treated − median change control (points of %), with its interval.

    The interval is the p5–p95 (90 %) of ``samples`` bootstrap resamples (each arm
    resampled with replacement, ``random.Random(seed)``); the strength grades the
    difference with D31.7's rule against the interval's half-width. With fewer than 5
    controls a permutation test over the assignment must also reject at p ≤ 0.10, else
    the strength is ``noise`` (:func:`.group_stats.assess`). ``false_alarm`` (the
    group's simulated rate, :func:`.group_stats.false_alarm_rate`): above 15 % the
    label is "Đang đo" and no strength is claimed. Too few products: the label
    "Chưa đủ cơ sở" and no numbers.
    """
    n_t, n_c = len(treated), len(control)
    label = _label(n_t, n_c)
    out: dict[str, Any] = {"n_treated": n_t, "n_control": n_c, "label": label}
    if label == LABEL_NOT_ENOUGH:
        out.update(
            median_treated=None,
            median_control=None,
            difference=None,
            interval=None,
            strength=None,
            strength_label=None,
        )
        return out
    med_t, med_c = statistics.median(treated), statistics.median(control)
    call = assess(treated, control, rng=random.Random(seed), samples=samples)
    low, high = call.interval
    strength = call.strength
    gated = false_alarm is not None and not false_alarm.acceptable
    if gated:
        out["label"] = LABEL_MEASURING
        strength = None
    out.update(
        median_treated=round(med_t, 2),
        median_control=round(med_c, 2),
        difference=round(call.difference, 2),
        interval=[round(low, 2), round(high, 2)],
        strength=strength,
        strength_label=STRENGTH_LABELS_VI.get(strength) if strength else None,
        interval_level=INTERVAL_LEVEL,
        test=call.test,
        alpha=ALPHA,
        permutation=call.permutation.to_json() if call.permutation is not None else None,
        detected=call.detected and not gated,
        #: What the rule would have claimed without the false-alarm gate (Ops only).
        rule_strength=call.strength,
        false_alarm=false_alarm.to_json() if false_alarm is not None else None,
    )
    return out


def seller_sentence(
    key: GroupKey, group_size: int, verdict: Mapping[str, Any] | None
) -> str | None:
    """The seller's one sentence (D34.8), or ``None`` while there is no verdict.

    "Nhóm 6 sản phẩm đổi ảnh bìa: lượt nhấp trên mỗi lượt hiển thị tăng khoảng 7 % so
    với các sản phẩm chưa đổi" -- plain words; "(sơ bộ)" on a preliminary verdict.
    """
    if not isinstance(verdict, Mapping):
        return None
    primary = verdict.get("primary")
    if not isinstance(primary, Mapping) or primary.get("label") in (
        LABEL_NOT_ENOUGH,
        LABEL_MEASURING,
    ):
        return None
    diff = primary.get("difference")
    strength = primary.get("strength")
    if not isinstance(diff, int | float) or strength is None:
        return None
    did = _LEVER_DID_VI.get(key.lever, LEVER_LABELS_VI.get(key.lever, key.lever).lower())
    moved = _METRIC_MOVED_VI.get(key.metric, key.metric)
    head = f"Nhóm {group_size} sản phẩm {did}: {moved}"
    if strength == "noise" or round(abs(diff)) == 0:
        body = f"{head} chưa khác rõ so với các sản phẩm chưa đổi"
    else:
        way = "tăng" if diff > 0 else "giảm"
        body = f"{head} {way} khoảng {round(abs(diff))} % so với các sản phẩm chưa đổi"
    if primary.get("label") == LABEL_PRELIMINARY:
        body += " (sơ bộ)"
    return body


def _positive(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and value > 0 else None


def _units(measured: Sequence[Mapping[str, Any]]) -> tuple[list[Unit], bool]:
    """CUPED units of the measured rows: (before, after) when every row has both > 0,
    else change-only units (CUPED then leaves the changes as they are). D45.6: a row's
    ``pre_before`` (days −28..−15) rides along as ``Unit.pre``."""
    full = all(
        isinstance(c.get("before"), int | float)
        and isinstance(c.get("after"), int | float)
        and c["before"] > 0
        and c["after"] > 0
        for c in measured
    )
    if full:
        return [
            Unit(c["arm"], float(c["before"]), float(c["after"]), _positive(c.get("pre_before")))
            for c in measured
        ], True
    units = []
    for c in measured:
        unit = unit_from_change(c["arm"], float(c["change_pct"]))
        units.append(unit if unit is not None else Unit(c["arm"], 1.0, 1e-6))
    return units, False


def _false_alarm(
    pre_pairs: Sequence[Sequence[float]],
    adjusted: Sequence[tuple[str, float]],
    n_treated: int,
    n_control: int,
    seed: int,
    control_pairs: Sequence[Sequence[float]] = (),
    two_window_min: int | None = TWO_WINDOW_MIN_PRODUCTS,
) -> FalseAlarm | None:
    if _label(n_treated, n_control) == LABEL_NOT_ENOUGH:
        return None
    pool, source = null_pool(pre_pairs, adjusted, control_pairs)
    return false_alarm_rate(
        pool, n_treated, n_control, seed=seed, source=source, two_window_min=two_window_min
    )


def build_verdict(
    changes: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    as_of: date,
    control_pairs: Sequence[Sequence[float]] = (),
    history: Sequence[Mapping[str, Any]] = (),
    two_window_min: int | None = TWO_WINDOW_MIN_PRODUCTS,
    eb_prior_sd: float = EB_PRIOR_SD,
) -> dict[str, Any]:
    """The stored verdict from per-product rows ``{product_id, arm, approved, change_pct}``
    (plus ``before`` / ``after`` / ``pre_before`` when measured from data).

    ``primary``: by assignment (intent-to-treat). ``approved_only``: treated products
    whose card the seller approved, against the same control (secondary). D41.3: the
    changes compared are CUPED-adjusted (``adjusted_change_pct`` per product, ``cuped``
    with ``θ``); each comparison carries its simulated ``false_alarm`` rate, the
    primary one also at the top level. T3.1: ``control_pairs`` (the control members'
    untouched post-launch window pairs) join the pre-period pairs in the null pool;
    ``history`` = the earlier checks of this group, ``checks`` = history + this one.
    D45.6 (P36): the adjustment follows the group size (``adjustment``: the P31 θ
    below ``two_window_min`` measured products (D47.1), two pre-period windows from it;
    ``None`` = the P31 rule, one fitted θ at every size); a
    row's ``pre_pre_before`` (days −42..−29) makes its pre-period pair a triple, so
    the false-alarm replay can apply the same rule. D52 (P45, Ops only): ``primary.eb``
    is the comparison's lift shrunk toward the default prior N(0, ``eb_prior_sd``²)
    (:func:`eb_block`); nothing else reads it.
    """
    measured = [c for c in changes if isinstance(c.get("change_pct"), int | float)]
    units, cuped_used = _units(measured)
    adjustment = adjust_changes(units, two_window_min=two_window_min)
    adjusted, theta = adjustment.changes, adjustment.theta
    adjusted_by_id = {id(c): round(v, 2) for c, v in zip(measured, adjusted, strict=True)}
    treated = [v for c, v in zip(measured, adjusted, strict=True) if c["arm"] == ARM_TREATED]
    control = [v for c, v in zip(measured, adjusted, strict=True) if c["arm"] == ARM_CONTROL]
    approved = [
        v
        for c, v in zip(measured, adjusted, strict=True)
        if c["arm"] == ARM_TREATED and c.get("approved")
    ]
    pre_pairs: list[tuple[float, ...]] = []
    for c in measured:
        if not (
            isinstance(c.get("pre_before"), int | float)
            and isinstance(c.get("before"), int | float)
        ):
            continue
        earlier = _positive(c.get("pre_pre_before"))
        pair = (float(c["pre_before"]), float(c["before"]))
        pre_pairs.append((earlier, *pair) if earlier is not None else pair)
    arm_changes = [(c["arm"], v) for c, v in zip(measured, adjusted, strict=True)]
    fa_primary = _false_alarm(
        pre_pairs, arm_changes, len(treated), len(control), seed, control_pairs, two_window_min
    )
    fa_approved = _false_alarm(
        pre_pairs, arm_changes, len(approved), len(control), seed, control_pairs, two_window_min
    )
    products = []
    for c in changes:
        row = dict(c)
        row["adjusted_change_pct"] = adjusted_by_id.get(id(c))
        products.append(row)
    primary = compare(treated, control, seed=seed, false_alarm=fa_primary)
    primary["eb"] = eb_block(primary, default_prior(eb_prior_sd))
    check = {
        "as_of": as_of.isoformat(),
        "label": primary["label"],
        "false_alarm_rate": fa_primary.rate if fa_primary is not None else None,
        "pool": fa_primary.pool if fa_primary is not None else None,
    }
    return {
        "as_of": as_of.isoformat(),
        "window_days": MEASURE_DAYS,
        "primary": primary,
        "approved_only": compare(approved, control, seed=seed, false_alarm=fa_approved),
        "cuped": {"theta": round(theta, 4), "from_before_after": cuped_used},
        #: D45.6: which pre-period rule ran (``change`` / ``one_window`` / ``two_windows``).
        "adjustment": {**adjustment.to_json(), "two_window_min": two_window_min},
        "false_alarm": fa_primary.to_json() if fa_primary is not None else None,
        "null_pool": {"pre_period": len(pre_pairs), "control_after": len(control_pairs)},
        "checks": [*(dict(h) for h in history), check],
        "products": products,
    }


def metric_summary(
    metric: str, channel: str, verdict: Mapping[str, Any], *, basis: str | None = None
) -> dict[str, Any]:
    """One extra metric's comparison for ``verdict.metrics`` (D45.2): same rule as the primary.

    D55.1 (P46): ``basis`` (``net`` / ``gross``) of a money metric (AOV, items per order,
    all channels) goes into the Ops label, e.g. "AOV (đã trừ huỷ/hoàn) · tất cả kênh".
    """
    name = METRIC_LABELS_VI.get(metric, metric)
    if basis is not None and needs_net(metric, channel):
        name = basis_label(name, basis)
    return {
        "metric": metric,
        "channel": channel,
        "label": f"{name} · {CHANNEL_LABELS_VI.get(channel, channel)}",
        "basis": basis if needs_net(metric, channel) else None,
        "primary": verdict.get("primary"),
        "adjustment": verdict.get("adjustment"),
        "false_alarm": verdict.get("false_alarm"),
        "null_pool": verdict.get("null_pool"),
        "products": [
            {
                "product_id": p.get("product_id"),
                "arm": p.get("arm"),
                "change_pct": p.get("change_pct"),
                "adjusted_change_pct": p.get("adjusted_change_pct"),
            }
            for p in verdict.get("products") or []
        ],
    }


def guard_check(
    key: GroupKey,
    primary: Mapping[str, Any] | None,
    guard: Mapping[str, Any] | None,
    *,
    max_drop_pct: float = GUARD_DROP_PCT,
) -> dict[str, Any]:
    """D45.2: warn in Ops when the guard metric (product-card CTR) fell more than
    ``max_drop_pct`` points of % treated vs control -- whatever the primary did.

    ``primary`` / ``guard``: the two comparisons (``compare`` output). The point
    estimate decides (no interval, no strength): it is a warning to look, not a verdict.
    """
    metric, channel = GUARD_METRIC
    diff = guard.get("difference") if isinstance(guard, Mapping) else None
    primary_diff = primary.get("difference") if isinstance(primary, Mapping) else None
    out: dict[str, Any] = {
        "metric": metric,
        "channel": channel,
        "max_drop_pct": max_drop_pct,
        "difference": diff,
        "primary_difference": primary_diff,
        "warning": False,
    }
    guard_name = f"{METRIC_LABELS_VI[metric]} {CHANNEL_LABELS_VI[channel].lower()}"
    if not isinstance(diff, int | float):
        out["text"] = f"Chưa đủ dữ liệu {guard_name} để kiểm tra"
        return out
    if diff < -max_drop_pct:
        out["warning"] = True
        text = (
            f"Cảnh báo: {guard_name} của nhóm áp dụng giảm {abs(diff):.0f} % so với đối chứng "
            f"(ngưỡng {max_drop_pct:.0f} %)"
        )
        if isinstance(primary_diff, int | float) and primary_diff > 0:
            name = METRIC_LABELS_VI.get(key.metric, key.metric)
            text += f" dù {name} tăng {primary_diff:.0f} %"
        out["text"] = text
        return out
    out["text"] = f"{guard_name} không giảm quá {max_drop_pct:.0f} % so với đối chứng"
    return out


# =========================================================================== storage


def shop_day(now: datetime) -> date:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return (aware.astimezone(UTC) + _SHOP_UTC_OFFSET).date()


def _naive(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo is not None else now


@dataclass
class GroupPass:
    """What :func:`apply_groups` decided for the emission budget's drafts."""

    #: The drafts to consider, in order (a launching group's treated cards first).
    eligible: list[ActionCard]
    #: Control cards held until their release (``group_control``).
    held: list[ActionCard]
    launched: list[CardGroup]


async def _active_groups(
    session: AsyncSession, shop_id: uuid.UUID, today: date
) -> tuple[list[CardGroup], dict[uuid.UUID, list[CardGroupMember]]]:
    """Groups launched in the last :data:`MEMBER_MEMORY_DAYS`, plus every member of them.

    A product stays tied to its group that long: a released control (or a treated
    product) whose card is still a draft is never drawn into a new group of its key,
    so no seller is held back twice.
    """
    groups = list(
        (
            await session.execute(
                select(CardGroup).where(
                    CardGroup.shop_id == shop_id,
                    CardGroup.launched_on >= today - timedelta(days=MEMBER_MEMORY_DAYS),
                )
            )
        ).scalars()
    )
    members: dict[uuid.UUID, list[CardGroupMember]] = defaultdict(list)
    if groups:
        rows = (
            await session.execute(
                select(CardGroupMember).where(
                    CardGroupMember.shop_id == shop_id,
                    CardGroupMember.group_id.in_([g.id for g in groups]),
                )
            )
        ).scalars()
        for member in rows:
            members[member.group_id].append(member)
    return groups, members


async def apply_groups(
    session: AsyncSession,
    shop_id: uuid.UUID,
    drafts: list[ActionCard],
    *,
    now: datetime,
) -> GroupPass:
    """Hold control cards, release them at day 14, launch new groups (steps 2–3).

    ``drafts`` are the emission budget's eligible drafts in priority order (cooldown and
    Ops switches already applied). Writes groups and members; no commit.
    """
    today = shop_day(now)
    groups, members = await _active_groups(session, shop_id, today)
    by_member: dict[tuple[str, str], tuple[CardGroup, CardGroupMember]] = {}
    #: D45.1: a product in an Ops group (e.g. the pack test) is never drawn into a new
    #: card group -- two experiments on one product would read each other's change.
    in_ops_group: set[str] = set()
    for group in sorted(groups, key=lambda g: g.launched_on):
        ops_group = GroupDesign.of(group).ops
        for member in members.get(group.id, []):
            by_member[(group.group_key, member.tiktok_product_id)] = (group, member)
            if ops_group:
                in_ops_group.add(member.tiktok_product_id)

    held: list[ActionCard] = []
    first: list[ActionCard] = []
    rest: list[ActionCard] = []
    free: dict[str, list[tuple[ActionCard, str]]] = defaultdict(list)
    for card in drafts:
        info = card_group_key(card)
        if info is None:
            rest.append(card)
            continue
        key, product = info
        hit = by_member.get((key.text, product))
        if hit is None:
            if product not in in_ops_group:
                free[key.text].append((card, product))
            rest.append(card)
            continue
        group, member = hit
        if member.arm == ARM_CONTROL:
            if today < group.release_on:
                held.append(card)
                continue
            if member.released_at is None:
                member.released_at = _naive(now)
            rest.append(card)
            continue
        launching = today < group.launched_on + timedelta(days=LAUNCH_WINDOW_DAYS)
        (first if launching else rest).append(card)

    launched: list[CardGroup] = []
    for key_text, entries in free.items():
        products: dict[str, ActionCard] = {}
        for card, product in entries:
            products.setdefault(product, card)
        if len(products) < MIN_GROUP_SIZE:
            continue
        key = GroupKey.parse(key_text)
        seed = new_seed()
        arms = assign_arms(products, seed)
        group = CardGroup(
            id=uuid.uuid4(),
            shop_id=shop_id,
            group_key=key_text,
            metric=key.metric,
            lever=key.lever,
            channel=key.channel,
            launched_on=today,
            release_on=today + timedelta(days=CONTROL_DELAY_DAYS),
            seed=seed,
            status=GROUP_OPEN,
        )
        session.add(group)
        launched.append(group)
        for product, card in products.items():
            session.add(
                CardGroupMember(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    group_id=group.id,
                    tiktok_product_id=product,
                    action_card_id=card.id,
                    arm=arms[product],
                    assigned_at=_naive(now),
                )
            )
            rest.remove(card)
            if arms[product] == ARM_CONTROL:
                held.append(card)
            else:
                first.append(card)
        logger.info(
            "card_group_launched",
            extra={
                "shop_id": str(shop_id),
                "group_key": key_text,
                "members": len(products),
                "controls": sum(1 for a in arms.values() if a == ARM_CONTROL),
                "seed": seed,
            },
        )
    if launched:
        await session.flush()
    order = {card.id: index for index, card in enumerate(drafts)}
    first.sort(key=lambda c: order[c.id])
    rest.sort(key=lambda c: order[c.id])
    return GroupPass(eligible=first + rest, held=held, launched=launched)


def _value(totals: Any, name: str) -> float | None:
    """A window's metric: ``WindowTotals.value`` plus items per order (D45.2)."""
    if name == "items_per_order":
        orders = totals.sku_orders
        return float(totals.items_sold / orders) if totals.days > 0 and orders > 0 else None
    v = totals.value(name)
    return None if v is None else float(v)


def _window_value(rows: Sequence[Any], name: str, start: date) -> float | None:
    """The metric over the 14 days from ``start``; ``None`` below 7 days with data or ≤ 0."""
    from juli_backend.services.lever_flows.measurement import window_totals

    totals = window_totals(rows, start, start + timedelta(days=MEASURE_DAYS - 1))
    v = _value(totals, name)
    if v is None or totals.days < MIN_DAYS_MEASURED or v <= 0:
        return None
    return v


def _window_pairs(
    rows: Sequence[Any], name: str, launch: date, untouched_through: date
) -> list[tuple[float, ...]]:
    """Consecutive 14-day window pairs from day −14 ending on or before ``untouched_through``.

    (−14..−1, 0..13), (0..13, 14..27), … -- a control member's no-effect pairs (T3.1).
    D45.6: a pair whose preceding 14 days have data is a triple (w − 1, w, w + 1), so
    the replay can run the two-window rule.
    """
    pairs: list[tuple[float, ...]] = []
    start = launch - timedelta(days=MEASURE_DAYS)
    while start + timedelta(days=2 * MEASURE_DAYS - 1) <= untouched_through:
        b = _window_value(rows, name, start)
        a = _window_value(rows, name, start + timedelta(days=MEASURE_DAYS))
        if b is not None and a is not None:
            p = _window_value(rows, name, start - timedelta(days=MEASURE_DAYS))
            pairs.append((p, b, a) if p is not None else (b, a))
        start += timedelta(days=MEASURE_DAYS)
    return pairs


def _spec_values(
    raw_rows: Sequence[Any],
    launch: date,
    metric: str,
    channel: str,
    untouched_through: date | None,
) -> dict[str, Any]:
    """One metric × channel of one member: before / after / pre-periods / change (pure)."""
    from juli_backend.services.lever_flows.measurement import channel_rows, window_totals

    rows: Sequence[Any] = raw_rows if channel == "total" else channel_rows(raw_rows, channel)
    before_start = launch - timedelta(days=MEASURE_DAYS)
    pre_start = before_start - timedelta(days=MEASURE_DAYS)
    after_end = launch + timedelta(days=MEASURE_DAYS - 1)
    before = window_totals(rows, before_start, launch - timedelta(days=1))
    after = window_totals(rows, launch, after_end)
    name = MEASURE_METRIC.get(metric, metric)
    b, a = _value(before, name), _value(after, name)
    # D41.3: the 14 days before "before" -- the no-effect pair for the false-alarm replay;
    # D45.6: the 14 days before those -- the replay's own earlier window (a triple).
    p = _window_value(rows, name, pre_start)
    pp = _window_value(rows, name, pre_start - timedelta(days=MEASURE_DAYS))
    change: float | None = None
    if (
        b is not None
        and a is not None
        and b > 0
        and before.days >= MIN_DAYS_MEASURED
        and after.days >= MIN_DAYS_MEASURED
    ):
        change = round((a / b - 1) * 100, 2)
    return {
        "before": b,
        "after": a,
        "pre_before": p,
        "pre_pre_before": pp,
        "change_pct": change,
        "null_pairs": (
            _window_pairs(rows, name, launch, untouched_through)
            if untouched_through is not None
            else []
        ),
    }


async def _member_change(
    session: AsyncSession,
    shop_id: uuid.UUID,
    group: CardGroup,
    product: str,
    *,
    untouched_through: date | None = None,
    specs: Sequence[tuple[str, str]] = (),
    net_days: Mapping[date, OrderDay] | None = None,
) -> dict[str, Any]:
    """One member's before (14 days before launch) / after (14 days from launch) values.

    ``net_days`` (D55.1, P46): the product's order days when the group reads net values
    (``None``: TikTok GMV only). A money spec is then read on the net rows, with the
    TikTok-GMV reading under ``gross``; a money primary's net reading is ``net``.

    ``untouched_through`` (control members only): the last day no lever ran on the
    product -- its consecutive post-launch window pairs up to then are returned as
    ``null_pairs`` for the false-alarm pool (T3.1). ``specs`` (D45.2): extra
    (metric, channel) pairs, returned under ``metrics`` keyed ``metric|channel``.
    """
    from juli_backend.services.lever_flows.measurement import _daily_rows

    launch = group.launched_on
    # Days −42..−1 before launch (three pre-period windows, D45.6) and the after window.
    first = launch - timedelta(days=3 * MEASURE_DAYS)
    after_end = launch + timedelta(days=MEASURE_DAYS - 1)
    rows_end = max(after_end, untouched_through) if untouched_through else after_end
    rows: list[Any] = await _daily_rows(session, shop_id, product, first, rows_end)
    out = _spec_values(rows, launch, group.metric, group.channel, untouched_through)
    net = net_rows(rows, net_days) if net_days is not None else None
    if net is not None and needs_net(group.metric, group.channel):
        out["net"] = _spec_values(net, launch, group.metric, group.channel, untouched_through)
    if specs:
        metrics: dict[str, Any] = {}
        for metric, channel in specs:
            gross = _spec_values(rows, launch, metric, channel, untouched_through)
            if net is not None and needs_net(metric, channel):
                value = _spec_values(net, launch, metric, channel, untouched_through)
                value["gross"] = gross
            else:
                value = gross
            metrics[spec_key(metric, channel)] = value
        out["metrics"] = metrics
    return out


async def measure_due_groups(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    tunables: DiagTunables | None = None,
    only_ops: bool = False,
) -> list[CardGroup]:
    """Day-14 verdicts for the shop's open groups whose 14 days of data are in (step 4).

    T3.1: a measured group whose verdict reads "Đang đo" is measured again every
    :data:`RECHECK_EVERY_DAYS` (day 21, 28, …, up to :data:`RECHECK_UNTIL_DAYS` after
    launch) with the latest data: the comparison window stays the 14 days from launch,
    but the null pool grows with the control members' untouched post-launch pairs, so
    the false-alarm gate can let the verdict out of "Đang đo".

    D45 (P36): every verdict also reads all-channel AOV and items per order
    (``metrics``) and, for a group with a CTR guard, the product-card CTR
    (``guard``); the pre-period rule follows the group size
    (``tunables.group_two_window_min``) for an Ops group and for those extra metrics.
    A card-drawn group's primary verdict -- the one behind the seller's sentence --
    keeps the P31 rule (one fitted θ), because D45 is Ops-only; the D45.6 reading of
    its primary metric is stored next to it as ``ops_rule`` for Ops to compare.
    ``only_ops``: measure only groups made in Ops (card groups switched off).
    """
    tun = tunables if tunables is not None else DiagTunables()
    from juli_backend.services.action_cards.optimize_product_cards import (
        latest_product_analytics_day,
    )

    as_of = await latest_product_analytics_day(session, shop_id, on_or_before=shop_day(now))
    if as_of is None:
        return []
    due = list(
        (
            await session.execute(
                select(CardGroup).where(
                    CardGroup.shop_id == shop_id,
                    CardGroup.status == GROUP_OPEN,
                    CardGroup.launched_on <= as_of - timedelta(days=MEASURE_DAYS - 1),
                )
            )
        ).scalars()
    )
    rechecks = list(
        (
            await session.execute(
                select(CardGroup).where(
                    CardGroup.shop_id == shop_id,
                    CardGroup.status == GROUP_MEASURED,
                    CardGroup.launched_on >= as_of - timedelta(days=RECHECK_UNTIL_DAYS),
                )
            )
        ).scalars()
    )
    due.extend(group for group in rechecks if _recheck_due(group, as_of))
    if only_ops:
        due = [group for group in due if GroupDesign.of(group).ops]
    measured: list[CardGroup] = []
    for group in due:
        members = list(
            (
                await session.execute(
                    select(CardGroupMember).where(
                        CardGroupMember.shop_id == shop_id,
                        CardGroupMember.group_id == group.id,
                    )
                )
            ).scalars()
        )
        card_ids = [m.action_card_id for m in members if m.action_card_id is not None]
        approved_on: dict[uuid.UUID, date] = {}
        if card_ids:
            approved_on = {
                card.id: shop_day(card.approved_at)
                for card in (
                    await session.execute(
                        select(ActionCard).where(
                            ActionCard.shop_id == shop_id, ActionCard.id.in_(card_ids)
                        )
                    )
                ).scalars()
                if card.approved_at is not None
            }
        approved = set(approved_on)
        key = GroupKey.parse(group.group_key)
        design = GroupDesign.of(group)
        specs = metric_specs(key, design)
        # D55.1 (P46): money metrics net of cancelled / refunded orders when the shop's
        # orders cover days −42 .. 13 (else TikTok's GMV, and Ops says so).
        wants_net = needs_net(key.metric, key.channel) or any(needs_net(*s) for s in specs)
        net_by_product: dict[str, dict[date, OrderDay]] | None = None
        if wants_net and await order_coverage(
            session,
            shop_id,
            group.launched_on - timedelta(days=3 * MEASURE_DAYS),
            group.launched_on + timedelta(days=MEASURE_DAYS - 1),
        ):
            net_by_product = await load_order_days(
                session,
                shop_id,
                [m.tiktok_product_id for m in members],
                group.launched_on - timedelta(days=3 * MEASURE_DAYS),
                as_of,
            )
        changes = []
        control_pairs: list[tuple[float, ...]] = []
        extra_changes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        extra_pairs: dict[str, list[tuple[float, ...]]] = defaultdict(list)
        gross_changes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        gross_pairs: dict[str, list[tuple[float, ...]]] = defaultdict(list)
        net_changes: list[dict[str, Any]] = []
        net_pairs: list[tuple[float, ...]] = []
        for member in sorted(members, key=lambda m: m.tiktok_product_id):
            untouched: date | None = None
            if member.arm == ARM_CONTROL:
                # A control is untouched until the seller approves its released card.
                touched = approved_on.get(member.action_card_id) if member.action_card_id else None
                untouched = as_of if touched is None else min(as_of, touched - timedelta(days=1))
            values = await _member_change(
                session,
                shop_id,
                group,
                member.tiktok_product_id,
                untouched_through=untouched,
                specs=specs,
                net_days=(
                    net_by_product.get(member.tiktok_product_id, {})
                    if net_by_product is not None
                    else None
                ),
            )
            control_pairs.extend(values.pop("null_pairs"))
            base = {
                "product_id": member.tiktok_product_id,
                "arm": member.arm,
                "approved": member.action_card_id in approved,
            }
            for name, extra in (values.pop("metrics", None) or {}).items():
                gross_extra = extra.pop("gross", None)
                extra_pairs[name].extend(extra.pop("null_pairs"))
                extra_changes[name].append({**base, **extra})
                if gross_extra is not None:
                    gross_pairs[name].extend(gross_extra.pop("null_pairs"))
                    gross_changes[name].append({**base, **gross_extra})
            net_primary = values.pop("net", None)
            if net_primary is not None:
                net_pairs.extend(net_primary.pop("null_pairs"))
                net_changes.append({**base, **net_primary})
            changes.append({**base, **values})
        previous = group.verdict if isinstance(group.verdict, dict) else {}
        basis = BASIS_NET if net_by_product is not None else BASIS_GROSS
        primary_basis = basis if needs_net(key.metric, key.channel) else None
        # D55.1: an Ops group's money primary is read net; a card group's stays on
        # TikTok's GMV (the seller's sentence) with the net reading beside it.
        ops_net = design.ops and bool(net_changes)
        verdict = build_verdict(
            net_changes if ops_net else changes,
            seed=group.seed,
            as_of=as_of,
            control_pairs=net_pairs if ops_net else control_pairs,
            history=previous.get("checks") or [],
            two_window_min=tun.group_two_window_min if design.ops else None,
            eb_prior_sd=tun.group_eb_prior_sd,
        )
        if wants_net:
            verdict["basis"] = {"money": basis, "text": BASIS_TEXT_VI[basis]}
        if ops_net:
            verdict["gross"] = metric_summary(
                key.metric,
                key.channel,
                build_verdict(
                    changes,
                    seed=group.seed,
                    as_of=as_of,
                    control_pairs=control_pairs,
                    two_window_min=tun.group_two_window_min,
                    eb_prior_sd=tun.group_eb_prior_sd,
                ),
                basis=BASIS_GROSS,
            )
        elif net_changes:
            verdict["net"] = metric_summary(
                key.metric,
                key.channel,
                build_verdict(
                    net_changes,
                    seed=group.seed,
                    as_of=as_of,
                    control_pairs=net_pairs,
                    two_window_min=tun.group_two_window_min,
                    eb_prior_sd=tun.group_eb_prior_sd,
                ),
                basis=BASIS_NET,
            )
        if not design.ops:
            # D45.6, Ops only: the group-size rule on the same rows, beside the P31 verdict.
            verdict["ops_rule"] = metric_summary(
                key.metric,
                key.channel,
                build_verdict(
                    changes,
                    seed=group.seed,
                    as_of=as_of,
                    control_pairs=control_pairs,
                    two_window_min=tun.group_two_window_min,
                    eb_prior_sd=tun.group_eb_prior_sd,
                ),
                basis=BASIS_GROSS if primary_basis else None,
            )
        metrics: dict[str, Any] = {}
        for metric, channel in specs:
            name = spec_key(metric, channel)
            extra_verdict = build_verdict(
                extra_changes[name],
                seed=group.seed,
                as_of=as_of,
                control_pairs=extra_pairs[name],
                two_window_min=tun.group_two_window_min,
                eb_prior_sd=tun.group_eb_prior_sd,
            )
            spec_basis = basis if needs_net(metric, channel) else None
            metrics[name] = metric_summary(metric, channel, extra_verdict, basis=spec_basis)
            if name in gross_changes:
                metrics[name]["gross"] = metric_summary(
                    metric,
                    channel,
                    build_verdict(
                        gross_changes[name],
                        seed=group.seed,
                        as_of=as_of,
                        control_pairs=gross_pairs[name],
                        two_window_min=tun.group_two_window_min,
                        eb_prior_sd=tun.group_eb_prior_sd,
                    ),
                    basis=BASIS_GROSS,
                )
        verdict["metrics"] = metrics
        if design.guard:
            guard_primary = (
                verdict["primary"]
                if (key.metric, key.channel) == GUARD_METRIC
                else (metrics.get(spec_key(*GUARD_METRIC)) or {}).get("primary")
            )
            # D55.1: "… dù AOV tăng …" reads the net AOV when there is one.
            money_primary = (verdict.get("net") or {}).get("primary") or verdict["primary"]
            verdict["guard"] = guard_check(
                key, money_primary, guard_primary, max_drop_pct=tun.group_guard_ctr_drop
            )
        group.verdict = verdict
        group.status = GROUP_MEASURED
        group.measured_at = _naive(now)
        measured.append(group)
        logger.info(
            "card_group_measured",
            extra={
                "shop_id": str(shop_id),
                "group_key": group.group_key,
                "label": group.verdict["primary"]["label"],
                "strength": group.verdict["primary"]["strength"],
            },
        )
    if measured:
        await session.flush()
    return measured


def _recheck_due(group: CardGroup, as_of: date) -> bool:
    """A measured "Đang đo" group whose last check is ≥ :data:`RECHECK_EVERY_DAYS` old."""
    verdict = group.verdict if isinstance(group.verdict, dict) else {}
    primary = verdict.get("primary")
    if not isinstance(primary, Mapping) or primary.get("label") != LABEL_MEASURING:
        return False
    try:
        last = date.fromisoformat(str(verdict.get("as_of")))
    except ValueError:
        return False
    return as_of >= last + timedelta(days=RECHECK_EVERY_DAYS)


async def seller_sentences(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, str]:
    """Group key -> the seller sentence of its latest measured group (one query + members)."""
    groups = list(
        (
            await session.execute(
                select(CardGroup)
                .where(CardGroup.shop_id == shop_id, CardGroup.status == GROUP_MEASURED)
                .order_by(CardGroup.launched_on.asc())
            )
        ).scalars()
    )
    out: dict[str, str] = {}
    for group in groups:
        if GroupDesign.of(group).ops:
            continue  # D45: an Ops group is Ops-only -- the seller never sees it.
        verdict = group.verdict if isinstance(group.verdict, dict) else None
        size = len(verdict.get("products") or []) if verdict else 0
        sentence = seller_sentence(GroupKey.parse(group.group_key), size, verdict)
        if sentence is not None:
            out[group.group_key] = sentence
    return out


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def _before_totals(
    session: AsyncSession, shop_id: uuid.UUID, group: CardGroup, arms: Mapping[str, str]
) -> dict[str, dict[str, float]]:
    """Per arm: impressions / clicks (on the group's channel) and orders / GMV (all channels)
    over the 14 days before launch -- the traffic the group has (D45.4). One query.

    D55.1 (P46): when the shop's orders cover those days, also ``orders_net`` /
    ``gmv_net`` -- the same totals net of cancelled / refunded orders (:mod:`.group_net`);
    ``gmv`` stays TikTok's GMV (cancelled and refunded orders included)."""
    from juli_backend.services.lever_flows.measurement import channel_rows

    start = group.launched_on - timedelta(days=MEASURE_DAYS)
    end = group.launched_on - timedelta(days=1)
    out = {
        arm: {"impressions": 0.0, "clicks": 0.0, "orders": 0.0, "gmv": 0.0}
        for arm in (ARM_TREATED, ARM_CONTROL)
    }
    if not arms:
        return out
    rows = (
        await session.execute(
            select(AnalyticsPerformanceInterval).where(
                AnalyticsPerformanceInterval.shop_id == shop_id,
                AnalyticsPerformanceInterval.grain == "product",
                AnalyticsPerformanceInterval.tiktok_product_id.in_(list(arms)),
                AnalyticsPerformanceInterval.start_date >= start,
                AnalyticsPerformanceInterval.start_date <= end,
            )
        )
    ).scalars()
    by_product: dict[str, list[AnalyticsPerformanceInterval]] = defaultdict(list)
    for row in rows:
        if row.tiktok_product_id:
            by_product[row.tiktok_product_id].append(row)
    net_days: dict[str, dict[date, OrderDay]] | None = None
    if await order_coverage(session, shop_id, start, end):
        net_days = await load_order_days(session, shop_id, list(arms), start, end)
        for totals in out.values():
            totals.update({"orders_net": 0.0, "gmv_net": 0.0})
    for product, product_rows in by_product.items():
        arm = arms.get(product)
        if arm not in out:
            continue
        traffic: Sequence[Any] = (
            product_rows if group.channel == "total" else channel_rows(product_rows, group.channel)
        )
        out[arm]["impressions"] += float(sum((r.impressions or 0) for r in traffic))
        out[arm]["clicks"] += float(sum((r.clicks or 0) for r in traffic))
        out[arm]["orders"] += float(sum((r.sku_orders or 0) for r in product_rows))
        out[arm]["gmv"] += float(sum((r.gmv or 0) for r in product_rows))
        if net_days is not None:
            net = net_rows(product_rows, net_days.get(product, {}))
            out[arm]["orders_net"] += float(sum((r.sku_orders or 0) for r in net))
            out[arm]["gmv_net"] += float(sum((r.gmv or 0) for r in net))
    return out


def plan_view(
    group: CardGroup,
    n_treated: int,
    n_control: int,
    have: Mapping[str, Mapping[str, float]],
    *,
    sigma_week: float = DRIFT_SIGMA_WEEK,
) -> dict[str, Any]:
    """D45.4: the weekly-drift floor of the 90 % interval next to the traffic needed. No
    label, no gate -- numbers for Ops to read (pure)."""
    weeks = MEASURE_DAYS / 7
    floor = drift_floor(n_treated, n_control, weeks, sigma_week)
    pooled = {
        k: sum(float(have.get(arm, {}).get(k) or 0) for arm in (ARM_TREATED, ARM_CONTROL))
        for k in ("impressions", "clicks", "orders")
    }
    return {
        "weeks": weeks,
        "sigma_week": sigma_week,
        "n_treated": n_treated,
        "n_control": n_control,
        "floor": floor.to_json() if floor is not None else None,
        "needed_per_arm": traffic_needed(group.metric, pooled, floor=floor),
        "have_before": {
            arm: {k: round(v) for k, v in (have.get(arm) or {}).items()}
            for arm in (ARM_TREATED, ARM_CONTROL)
        },
        "have_window": [
            (group.launched_on - timedelta(days=MEASURE_DAYS)).isoformat(),
            (group.launched_on - timedelta(days=1)).isoformat(),
        ],
        #: D55.1 (P46): ``net`` when ``have_before`` carries ``gmv_net`` / ``orders_net``.
        "revenue_basis": (
            BASIS_NET
            if all("gmv_net" in (have.get(arm) or {}) for arm in (ARM_TREATED, ARM_CONTROL))
            else BASIS_GROSS
        ),
    }


async def group_views(
    session: AsyncSession, shop_id: uuid.UUID, *, tunables: DiagTunables | None = None
) -> list[dict[str, Any]]:
    """Every group of the shop for Ops (D34.8): members, arms, launch, verdict, newest first.

    D45 (P36): each group also carries its ``design`` (source, reason, CTR guard) and its
    ``plan`` -- the weekly-drift floor and the traffic needed (:func:`plan_view`).
    """
    tun = tunables if tunables is not None else DiagTunables()
    groups = list(
        (
            await session.execute(
                select(CardGroup)
                .where(CardGroup.shop_id == shop_id)
                .order_by(CardGroup.launched_on.desc(), CardGroup.group_key.asc())
            )
        ).scalars()
    )
    if not groups:
        return []
    members: dict[uuid.UUID, list[CardGroupMember]] = defaultdict(list)
    for member in (
        await session.execute(
            select(CardGroupMember).where(
                CardGroupMember.shop_id == shop_id,
                CardGroupMember.group_id.in_([g.id for g in groups]),
            )
        )
    ).scalars():
        members[member.group_id].append(member)
    card_ids = [m.action_card_id for ms in members.values() for m in ms if m.action_card_id]
    cards: dict[uuid.UUID, ActionCard] = {}
    if card_ids:
        cards = {
            c.id: c
            for c in (
                await session.execute(
                    select(ActionCard).where(
                        ActionCard.shop_id == shop_id, ActionCard.id.in_(card_ids)
                    )
                )
            ).scalars()
        }
    # Ops groups have no card: their titles come from the catalogue.
    cardless = sorted(
        {m.tiktok_product_id for ms in members.values() for m in ms if m.action_card_id is None}
    )
    titles: dict[str, str] = {}
    if cardless:
        for product in (
            await session.execute(
                select(Product).where(
                    Product.shop_id == shop_id, Product.tiktok_product_id.in_(cardless)
                )
            )
        ).scalars():
            titles[product.tiktok_product_id] = product.title or product.name
    out: list[dict[str, Any]] = []
    for group in groups:
        key = GroupKey.parse(group.group_key)
        design = GroupDesign.of(group)
        rows = []
        for member in sorted(members.get(group.id, []), key=lambda m: (m.arm, m.tiktok_product_id)):
            card = cards.get(member.action_card_id) if member.action_card_id else None
            payload = _payload(card) if card is not None else {}
            diagnosis = payload.get("diagnosis") if isinstance(payload, dict) else None
            title = diagnosis.get("product_title") if isinstance(diagnosis, Mapping) else None
            rows.append(
                {
                    "product_id": member.tiktok_product_id,
                    "product_title": title or titles.get(member.tiktok_product_id),
                    "arm": member.arm,
                    "card_id": str(member.action_card_id) if member.action_card_id else None,
                    #: D45.8: the member's order-volume stratum (Ops groups drawn by strata).
                    "stratum": (design.strata or {}).get(member.tiktok_product_id),
                    "card_status": card.status if card is not None else None,
                    "surfaced_at": _iso(card.surfaced_at) if card is not None else None,
                    "approved": bool(card is not None and card.approved_at is not None),
                    "released_at": _iso(member.released_at),
                }
            )
        verdict = group.verdict if isinstance(group.verdict, dict) else None
        n_treated = sum(1 for r in rows if r["arm"] == ARM_TREATED)
        n_control = sum(1 for r in rows if r["arm"] == ARM_CONTROL)
        arms = {m.tiktok_product_id: m.arm for m in members.get(group.id, [])}
        have = await _before_totals(session, shop_id, group, arms)
        out.append(
            {
                "id": str(group.id),
                "key": group.group_key,
                "label": key.label_vi,
                "metric": group.metric,
                "lever": group.lever,
                "channel": group.channel,
                "launched_on": group.launched_on.isoformat(),
                "release_on": group.release_on.isoformat(),
                "seed": group.seed,
                "status": group.status,
                "treated": n_treated,
                "control": n_control,
                "members": rows,
                "verdict": verdict,
                #: D41.3: the primary verdict's simulated false-alarm rate (None before).
                "false_alarm": (verdict or {}).get("false_alarm"),
                "seller_sentence": (
                    None if design.ops else seller_sentence(key, len(rows), verdict)
                ),
                #: D45 (P36): who made it, the "lý do chọn thử nghiệm", the CTR guard.
                "design": design.to_json(),
                #: D45.4: weekly-drift floor of the 90 % interval + traffic needed.
                "plan": plan_view(
                    group, n_treated, n_control, have, sigma_week=tun.group_drift_sigma
                ),
            }
        )
    return out


# =========================================================================== EB lift (D52)


def eb_block(comparison: Mapping[str, Any] | None, prior: Prior) -> dict[str, Any] | None:
    """The comparison's EB-shrunk lift (:func:`.group_stats.shrink_lift`), or ``None``."""
    lift = log_lift_of(dict(comparison)) if isinstance(comparison, Mapping) else None
    return None if lift is None else shrink_lift(lift, prior)


@dataclass(frozen=True)
class EbDraw:
    """One measured group comparison of a lever type, as a draw for its prior."""

    shop_id: str
    group_id: str
    lever: str
    metric: str
    channel: str
    lift: LogLift

    @property
    def lever_type(self) -> tuple[str, str, str]:
        return (self.lever, self.metric, self.channel)


def draws_from_rows(rows: Iterable[Sequence[Any]]) -> list[EbDraw]:
    """``(shop, group, lever, metric, channel, comparison)`` rows -> draws with a log-lift."""
    out: list[EbDraw] = []
    for shop_id, group_id, lever, metric, channel, comparison in rows:
        if isinstance(comparison, str):
            try:
                comparison = json.loads(comparison)
            except ValueError:
                continue
        lift = log_lift_of(comparison)
        if lift is None or not (lever and metric and channel):
            continue
        out.append(EbDraw(str(shop_id), str(group_id), lever, metric, channel, lift))
    return out


def _verdict_rows(group: CardGroup) -> list[tuple[Any, ...]]:
    """The rows ``ops_group_lift_draws()`` returns for one group (the SQLite path)."""
    verdict = group.verdict if isinstance(group.verdict, dict) else None
    if verdict is None:
        return []
    rows: list[tuple[Any, ...]] = []
    if isinstance(verdict.get("primary"), dict):
        rows.append(
            (group.shop_id, group.id, group.lever, group.metric, group.channel, verdict["primary"])
        )
    metrics = verdict.get("metrics")
    for entry in (metrics or {}).values() if isinstance(metrics, dict) else ():
        if isinstance(entry, dict) and isinstance(entry.get("primary"), dict):
            rows.append(
                (
                    group.shop_id,
                    group.id,
                    group.lever,
                    entry.get("metric"),
                    entry.get("channel"),
                    entry["primary"],
                )
            )
    return rows


async def lift_draws(session: AsyncSession) -> list[EbDraw]:
    """The measured group comparisons of every shop that opted into pooling, as EB draws
    (D52; D76 / D11). **Ops only.**

    Call it inside an ``ops_role`` block: on Postgres it reads
    ``public.ops_group_lift_draws()`` (migration 093, filtered by 107 to shops with an
    open ``pooled_training`` grant; SECURITY DEFINER, EXECUTE to ``juli_ops`` only -- a
    seller session is refused). The caller must return only aggregates
    (:func:`apply_pooled_eb`), never another shop's rows. SQLite (unit tests) has no RLS
    or roles: the same rows straight from ``card_groups``, with the same consent filter.
    """
    from juli_backend.models.consent import POOLED_TRAINING, DataUseConsent
    from juli_backend.services.ops.access import is_sqlite

    if is_sqlite(session):
        pooled = (
            select(DataUseConsent.id)
            .where(
                DataUseConsent.shop_id == CardGroup.shop_id,
                DataUseConsent.scope == POOLED_TRAINING,
                DataUseConsent.revoked_at.is_(None),
            )
            .exists()
        )
        groups = (
            await session.execute(
                select(CardGroup).where(CardGroup.status == GROUP_MEASURED, pooled)
            )
        ).scalars()
        return draws_from_rows(row for group in groups for row in _verdict_rows(group))
    result = await session.execute(text("SELECT * FROM public.ops_group_lift_draws()"))
    return draws_from_rows(
        (
            r["out_shop_id"],
            r["out_group_id"],
            r["out_lever"],
            r["out_metric"],
            r["out_channel"],
            r["out_comparison"],
        )
        for r in result.mappings()
    )


def _comparisons(
    verdict: dict[str, Any], metric: str, channel: str
) -> list[tuple[dict[str, Any], str, str]]:
    """A verdict's comparisons that carry an ``eb``, each with its (metric, channel)."""
    out: list[tuple[dict[str, Any], str, str]] = []
    if isinstance(verdict.get("primary"), dict):
        out.append((verdict["primary"], metric, channel))
    ops_rule = verdict.get("ops_rule")
    if isinstance(ops_rule, dict) and isinstance(ops_rule.get("primary"), dict):
        out.append((ops_rule["primary"], metric, channel))
    # D55.1 (P46): a card group's net money reading.
    net = verdict.get("net")
    if isinstance(net, dict) and isinstance(net.get("primary"), dict):
        out.append((net["primary"], metric, channel))
    metrics = verdict.get("metrics")
    for entry in metrics.values() if isinstance(metrics, dict) else ():
        if isinstance(entry, dict) and isinstance(entry.get("primary"), dict):
            out.append((entry["primary"], str(entry.get("metric")), str(entry.get("channel"))))
    return out


def apply_pooled_eb(
    views: Sequence[dict[str, Any]],
    draws: Sequence[EbDraw],
    *,
    pooled: bool,
    min_groups: int = EB_MIN_GROUPS,
    default_sd: float = EB_PRIOR_SD,
) -> list[dict[str, Any]]:
    """The Ops group views with every comparison's ``eb`` re-shrunk (D52). Pure.

    Per comparison: the prior of its lever type (lever × metric × channel) from
    ``draws`` without this group (leave-one-out), a shop's groups combined first;
    fewer than ``min_groups`` draws -> the default prior. Each view's verdict is
    copied (the stored JSON is not touched); only ``eb`` blocks change.

    ``pooled`` (D76 / D11, required so no caller forgets it): whether the viewed shop
    holds an open ``pooled_training`` grant. ``False`` -> ``draws`` is ignored and every
    comparison uses :func:`.group_stats.own_data_prior` -- the shop's own data only.
    """
    by_type: dict[tuple[str, str, str], list[tuple[str, str, LogLift]]] = defaultdict(list)
    for d in draws:
        by_type[d.lever_type].append((d.shop_id, d.group_id, d.lift))
    out: list[dict[str, Any]] = []
    for view in views:
        if not isinstance(view.get("verdict"), dict):
            out.append(view)
            continue
        verdict = json.loads(json.dumps(view["verdict"]))
        lever, group_id = str(view.get("lever")), str(view.get("id"))
        for comparison, metric, channel in _comparisons(
            verdict, str(view.get("metric")), str(view.get("channel"))
        ):
            prior = (
                estimate_prior(
                    by_type.get((lever, metric, channel), []),
                    exclude_group=group_id,
                    min_groups=min_groups,
                    default_sd=default_sd,
                )
                if pooled
                else own_data_prior(default_sd)
            )
            comparison["eb"] = eb_block(comparison, prior)
        out.append({**view, "verdict": verdict})
    return out


# =========================================================================== Ops groups (D45)


class GroupError(ValueError):
    """An Ops group request Juli refuses; the message is Vietnamese, shown in Ops."""


def clean_reason(reason: str | None) -> str | None:
    """One line, trimmed, at most :data:`REASON_MAX_CHARS`; empty → ``None``."""
    if reason is None:
        return None
    if not isinstance(reason, str):
        raise GroupError("Lý do phải là chữ")
    line = " ".join(reason.split())
    if len(line) > REASON_MAX_CHARS:
        raise GroupError(f"Lý do tối đa {REASON_MAX_CHARS} ký tự")
    return line or None


async def create_ops_group(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    lever: str,
    metric: str,
    channel: str,
    product_ids: Sequence[str],
    reason: str | None,
    guard: bool | None,
    created_by: str,
    stratify: bool = False,
    now: datetime,
) -> CardGroup:
    """D45.1: a D34 group made in Ops (no cards), e.g. a new pack option on 4 + 2 products.

    Same draw as a card group (sorted ids shuffled by a fresh recorded seed, the first
    round(n/3) the delayed control; launch = the shop's day, control "released" at day
    14). The owner makes the change on TikTok for the treated products only -- Juli never
    writes it. ``guard`` (D45.2; default: on unless the primary metric is CTR) reads the
    product-card CTR alongside. A product already in a group launched within
    :data:`MEMBER_MEMORY_DAYS` is refused, so two experiments never share a product.
    Writes the group and members; no commit.
    """
    if lever not in LEVER_LABELS_VI:
        raise GroupError(f"Đòn bẩy không hợp lệ: {lever}")
    if metric not in METRIC_LABELS_VI:
        raise GroupError(f"Chỉ số không hợp lệ: {metric}")
    if channel not in CHANNELS:
        raise GroupError(f"Kênh không hợp lệ: {channel}")
    products = sorted({p.strip() for p in product_ids if isinstance(p, str) and p.strip()})
    if len(products) < MIN_GROUP_SIZE:
        raise GroupError(f"Cần ít nhất {MIN_GROUP_SIZE} sản phẩm khác nhau")
    if len(products) > OPS_GROUP_MAX_PRODUCTS:
        raise GroupError(f"Tối đa {OPS_GROUP_MAX_PRODUCTS} sản phẩm mỗi nhóm")
    clean = clean_reason(reason)
    known = set(
        (
            await session.execute(
                select(Product.tiktok_product_id).where(
                    Product.shop_id == shop_id, Product.tiktok_product_id.in_(products)
                )
            )
        ).scalars()
    )
    unknown = [p for p in products if p not in known]
    if unknown:
        raise GroupError("Không có trong shop: " + ", ".join(unknown))
    if stratify and len(products) < 2 * STRATUM_MIN_PRODUCTS:
        raise GroupError(
            f"Chia tầng theo số đơn cần ít nhất {2 * STRATUM_MIN_PRODUCTS} sản phẩm "
            f"({STRATUM_MIN_PRODUCTS} mỗi tầng)"
        )
    today = shop_day(now)
    groups, members = await _active_groups(session, shop_id, today)
    taken = sorted(
        {
            m.tiktok_product_id
            for g in groups
            for m in members.get(g.id, [])
            if m.tiktok_product_id in set(products)
        }
    )
    if taken:
        raise GroupError("Đang ở một nhóm thử nghiệm khác: " + ", ".join(taken))
    key = GroupKey(metric, lever, channel)
    seed = new_seed()
    strata: dict[str, str] | None = None
    orders: dict[str, float] | None = None
    if stratify:
        orders = await _recent_orders(session, shop_id, products, today)
        strata = order_strata(orders)
        arms = assign_arms_stratified(strata, seed)
    else:
        arms = assign_arms(products, seed)
    design = GroupDesign(
        source=SOURCE_OPS,
        reason=clean,
        guard=(metric != GUARD_METRIC[0]) if guard is None else bool(guard),
        created_by=created_by,
        strata=strata,
        strata_orders=orders,
    )
    group = CardGroup(
        id=uuid.uuid4(),
        shop_id=shop_id,
        group_key=key.text,
        metric=metric,
        lever=lever,
        channel=channel,
        launched_on=today,
        release_on=today + timedelta(days=CONTROL_DELAY_DAYS),
        seed=seed,
        status=GROUP_OPEN,
        design=design.to_json(),
    )
    session.add(group)
    for product in products:
        session.add(
            CardGroupMember(
                id=uuid.uuid4(),
                shop_id=shop_id,
                group_id=group.id,
                tiktok_product_id=product,
                action_card_id=None,
                arm=arms[product],
                assigned_at=_naive(now),
            )
        )
    await session.flush()
    logger.info(
        "card_group_created_in_ops",
        extra={
            "shop_id": str(shop_id),
            "group_key": key.text,
            "members": len(products),
            "controls": sum(1 for a in arms.values() if a == ARM_CONTROL),
            "seed": seed,
        },
    )
    return group


async def _recent_orders(
    session: AsyncSession, shop_id: uuid.UUID, products: Sequence[str], today: date
) -> dict[str, float]:
    """D45.8: each product's all-channel SKU orders over the :data:`STRATIFY_ORDERS_DAYS`
    days before ``today`` (0 without data). One query."""
    start = today - timedelta(days=STRATIFY_ORDERS_DAYS)
    out = dict.fromkeys(products, 0.0)
    rows = (
        await session.execute(
            select(AnalyticsPerformanceInterval).where(
                AnalyticsPerformanceInterval.shop_id == shop_id,
                AnalyticsPerformanceInterval.grain == "product",
                AnalyticsPerformanceInterval.tiktok_product_id.in_(list(products)),
                AnalyticsPerformanceInterval.start_date >= start,
                AnalyticsPerformanceInterval.start_date < today,
            )
        )
    ).scalars()
    for row in rows:
        if row.tiktok_product_id in out:
            out[row.tiktok_product_id] += float(row.sku_orders or 0)
    return out


async def set_group_reason(
    session: AsyncSession, shop_id: uuid.UUID, group_id: uuid.UUID, reason: str | None
) -> tuple[CardGroup, str | None, str | None]:
    """D45.3: set (or clear) a group's one-line "lý do chọn thử nghiệm" -- any group.

    Returns (group, before, after); raises :class:`LookupError` when the shop has no
    such group. No commit.
    """
    group = (
        await session.execute(
            select(CardGroup).where(CardGroup.shop_id == shop_id, CardGroup.id == group_id)
        )
    ).scalar_one_or_none()
    if group is None:
        raise LookupError(str(group_id))
    clean = clean_reason(reason)
    current = GroupDesign.of(group)
    design = dict(group.design) if isinstance(group.design, dict) else current.to_json()
    design["reason"] = clean
    group.design = design
    await session.flush()
    return group, current.reason, clean


__all__ = [
    "CHANNELS",
    "CONTROL_DELAY_DAYS",
    "EXTRA_METRICS",
    "GUARD_DROP_PCT",
    "GUARD_METRIC",
    "SOURCE_CARDS",
    "SOURCE_OPS",
    "LABEL_MEASURING",
    "LABEL_NOT_ENOUGH",
    "RECHECK_EVERY_DAYS",
    "RECHECK_UNTIL_DAYS",
    "LABEL_PRELIMINARY",
    "LAUNCH_WINDOW_DAYS",
    "MIN_GROUP_SIZE",
    "SUPPRESSED_REASON_GROUP_CONTROL",
    "GroupDesign",
    "GroupError",
    "GroupKey",
    "GroupPass",
    "EbDraw",
    "apply_groups",
    "apply_pooled_eb",
    "assign_arms",
    "build_verdict",
    "card_group_key",
    "clean_reason",
    "compare",
    "control_count",
    "create_ops_group",
    "draws_from_rows",
    "eb_block",
    "guard_check",
    "group_views",
    "lift_draws",
    "measure_due_groups",
    "metric_specs",
    "new_seed",
    "payload_group_key",
    "plan_view",
    "seller_sentence",
    "seller_sentences",
    "set_group_reason",
]
