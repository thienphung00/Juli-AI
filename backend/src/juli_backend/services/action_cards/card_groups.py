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

Switch: the team tunable ``card_groups`` (``DiagTunables.groups_enabled``): unset
follows D33's quota mode (on only when the quota mode is on); off = nothing here runs
and the emission budget is unchanged.
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_groups import (
    ARM_CONTROL,
    ARM_TREATED,
    GROUP_MEASURED,
    GROUP_OPEN,
    CardGroup,
    CardGroupMember,
)
from juli_backend.models.models import ActionCard
from juli_backend.services.action_cards.emission_budget import SUPPRESSED_REASON_GROUP_CONTROL
from juli_backend.services.action_cards.group_stats import (
    ALPHA,
    INTERVAL_HIGH,
    INTERVAL_LOW,
    FalseAlarm,
    Unit,
    assess,
    cuped_adjust,
    false_alarm_rate,
    null_pool,
    unit_from_change,
)
from juli_backend.services.change_strength import STRENGTH_LABELS_VI

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
}

METRIC_LABELS_VI: Mapping[str, str] = {
    "impressions": "Lượt hiển thị",
    "ctr": "CTR",
    "ctor": "CTOR",
    "aov": "AOV",
}
LEVER_LABELS_VI: Mapping[str, str] = {
    "cover_image": "Ảnh bìa",
    "title": "Tiêu đề",
    "description": "Mô tả",
    "product_discount": "Giảm giá sản phẩm",
    "flash_sale": "Flash sale",
    "shipping_discount": "Giảm phí vận chuyển",
    "buy_more_save_more": "Mua nhiều giảm nhiều",
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
}
_METRIC_MOVED_VI: Mapping[str, str] = {
    "impressions": "lượt hiển thị",
    "ctr": "lượt nhấp",
    "ctor": "đơn hàng trên mỗi lượt nhấp",
    "aov": "giá trị mỗi đơn",
}


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


def _units(measured: Sequence[Mapping[str, Any]]) -> tuple[list[Unit], bool]:
    """CUPED units of the measured rows: (before, after) when every row has both > 0,
    else change-only units (CUPED then leaves the changes as they are)."""
    full = all(
        isinstance(c.get("before"), int | float)
        and isinstance(c.get("after"), int | float)
        and c["before"] > 0
        and c["after"] > 0
        for c in measured
    )
    if full:
        return [Unit(c["arm"], float(c["before"]), float(c["after"])) for c in measured], True
    units = []
    for c in measured:
        unit = unit_from_change(c["arm"], float(c["change_pct"]))
        units.append(unit if unit is not None else Unit(c["arm"], 1.0, 1e-6))
    return units, False


def _false_alarm(
    pre_pairs: Sequence[tuple[float, float]],
    adjusted: Sequence[tuple[str, float]],
    n_treated: int,
    n_control: int,
    seed: int,
    control_pairs: Sequence[tuple[float, float]] = (),
) -> FalseAlarm | None:
    if _label(n_treated, n_control) == LABEL_NOT_ENOUGH:
        return None
    pool, source = null_pool(pre_pairs, adjusted, control_pairs)
    return false_alarm_rate(pool, n_treated, n_control, seed=seed, source=source)


def build_verdict(
    changes: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    as_of: date,
    control_pairs: Sequence[tuple[float, float]] = (),
    history: Sequence[Mapping[str, Any]] = (),
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
    """
    measured = [c for c in changes if isinstance(c.get("change_pct"), int | float)]
    units, cuped_used = _units(measured)
    adjusted, theta = cuped_adjust(units)
    adjusted_by_id = {id(c): round(v, 2) for c, v in zip(measured, adjusted, strict=True)}
    treated = [v for c, v in zip(measured, adjusted, strict=True) if c["arm"] == ARM_TREATED]
    control = [v for c, v in zip(measured, adjusted, strict=True) if c["arm"] == ARM_CONTROL]
    approved = [
        v
        for c, v in zip(measured, adjusted, strict=True)
        if c["arm"] == ARM_TREATED and c.get("approved")
    ]
    pre_pairs = [
        (float(c["pre_before"]), float(c["before"]))
        for c in measured
        if isinstance(c.get("pre_before"), int | float) and isinstance(c.get("before"), int | float)
    ]
    arm_changes = [(c["arm"], v) for c, v in zip(measured, adjusted, strict=True)]
    fa_primary = _false_alarm(
        pre_pairs, arm_changes, len(treated), len(control), seed, control_pairs
    )
    fa_approved = _false_alarm(
        pre_pairs, arm_changes, len(approved), len(control), seed, control_pairs
    )
    products = []
    for c in changes:
        row = dict(c)
        row["adjusted_change_pct"] = adjusted_by_id.get(id(c))
        products.append(row)
    primary = compare(treated, control, seed=seed, false_alarm=fa_primary)
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
        "false_alarm": fa_primary.to_json() if fa_primary is not None else None,
        "null_pool": {"pre_period": len(pre_pairs), "control_after": len(control_pairs)},
        "checks": [*(dict(h) for h in history), check],
        "products": products,
    }


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
    for group in sorted(groups, key=lambda g: g.launched_on):
        for member in members.get(group.id, []):
            by_member[(group.group_key, member.tiktok_product_id)] = (group, member)

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


def _window_pairs(
    rows: Sequence[Any], name: str, launch: date, untouched_through: date
) -> list[tuple[float, float]]:
    """Consecutive 14-day window pairs from day −14 ending on or before ``untouched_through``.

    (−14..−1, 0..13), (0..13, 14..27), … -- a control member's no-effect pairs (T3.1).
    """
    from juli_backend.services.lever_flows.measurement import window_totals

    def value(start: date) -> float | None:
        totals = window_totals(rows, start, start + timedelta(days=MEASURE_DAYS - 1))
        v = totals.value(name)
        if v is None or totals.days < MIN_DAYS_MEASURED or v <= 0:
            return None
        return float(v)

    pairs: list[tuple[float, float]] = []
    start = launch - timedelta(days=MEASURE_DAYS)
    while start + timedelta(days=2 * MEASURE_DAYS - 1) <= untouched_through:
        b, a = value(start), value(start + timedelta(days=MEASURE_DAYS))
        if b is not None and a is not None:
            pairs.append((b, a))
        start += timedelta(days=MEASURE_DAYS)
    return pairs


async def _member_change(
    session: AsyncSession,
    shop_id: uuid.UUID,
    group: CardGroup,
    product: str,
    *,
    untouched_through: date | None = None,
) -> dict[str, Any]:
    """One member's before (14 days before launch) / after (14 days from launch) values.

    ``untouched_through`` (control members only): the last day no lever ran on the
    product -- its consecutive post-launch window pairs up to then are returned as
    ``null_pairs`` for the false-alarm pool (T3.1).
    """
    from juli_backend.services.lever_flows.measurement import (
        _daily_rows,
        channel_rows,
        window_totals,
    )

    launch = group.launched_on
    before_start = launch - timedelta(days=MEASURE_DAYS)
    pre_start = before_start - timedelta(days=MEASURE_DAYS)
    after_end = launch + timedelta(days=MEASURE_DAYS - 1)
    rows_end = max(after_end, untouched_through) if untouched_through else after_end
    rows: list[Any] = await _daily_rows(session, shop_id, product, pre_start, rows_end)
    if group.channel != "total":
        rows = channel_rows(rows, group.channel)
    pre = window_totals(rows, pre_start, before_start - timedelta(days=1))
    before = window_totals(rows, before_start, launch - timedelta(days=1))
    after = window_totals(rows, launch, after_end)
    name = MEASURE_METRIC.get(group.metric, group.metric)
    b, a = before.value(name), after.value(name)
    # D41.3: the 14 days before "before" -- the no-effect pair for the false-alarm replay.
    p = pre.value(name) if pre.days >= MIN_DAYS_MEASURED else None
    change: float | None = None
    if (
        b is not None
        and a is not None
        and b > 0
        and before.days >= MIN_DAYS_MEASURED
        and after.days >= MIN_DAYS_MEASURED
    ):
        change = round((float(a) / float(b) - 1) * 100, 2)
    return {
        "before": None if b is None else float(b),
        "after": None if a is None else float(a),
        "pre_before": None if p is None or p <= 0 else float(p),
        "change_pct": change,
        "null_pairs": (
            _window_pairs(rows, name, launch, untouched_through)
            if untouched_through is not None
            else []
        ),
    }


async def measure_due_groups(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> list[CardGroup]:
    """Day-14 verdicts for the shop's open groups whose 14 days of data are in (step 4).

    T3.1: a measured group whose verdict reads "Đang đo" is measured again every
    :data:`RECHECK_EVERY_DAYS` (day 21, 28, …, up to :data:`RECHECK_UNTIL_DAYS` after
    launch) with the latest data: the comparison window stays the 14 days from launch,
    but the null pool grows with the control members' untouched post-launch pairs, so
    the false-alarm gate can let the verdict out of "Đang đo".
    """
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
        changes = []
        control_pairs: list[tuple[float, float]] = []
        for member in sorted(members, key=lambda m: m.tiktok_product_id):
            untouched: date | None = None
            if member.arm == ARM_CONTROL:
                # A control is untouched until the seller approves its released card.
                touched = approved_on.get(member.action_card_id) if member.action_card_id else None
                untouched = as_of if touched is None else min(as_of, touched - timedelta(days=1))
            values = await _member_change(
                session, shop_id, group, member.tiktok_product_id, untouched_through=untouched
            )
            control_pairs.extend(values.pop("null_pairs"))
            changes.append(
                {
                    "product_id": member.tiktok_product_id,
                    "arm": member.arm,
                    "approved": member.action_card_id in approved,
                    **values,
                }
            )
        previous = group.verdict if isinstance(group.verdict, dict) else {}
        group.verdict = build_verdict(
            changes,
            seed=group.seed,
            as_of=as_of,
            control_pairs=control_pairs,
            history=previous.get("checks") or [],
        )
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
        verdict = group.verdict if isinstance(group.verdict, dict) else None
        size = len(verdict.get("products") or []) if verdict else 0
        sentence = seller_sentence(GroupKey.parse(group.group_key), size, verdict)
        if sentence is not None:
            out[group.group_key] = sentence
    return out


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def group_views(session: AsyncSession, shop_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every group of the shop for Ops (D34.8): members, arms, launch, verdict, newest first."""
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
    out: list[dict[str, Any]] = []
    for group in groups:
        key = GroupKey.parse(group.group_key)
        rows = []
        for member in sorted(members.get(group.id, []), key=lambda m: (m.arm, m.tiktok_product_id)):
            card = cards.get(member.action_card_id) if member.action_card_id else None
            payload = _payload(card) if card is not None else {}
            diagnosis = payload.get("diagnosis") if isinstance(payload, dict) else None
            title = diagnosis.get("product_title") if isinstance(diagnosis, Mapping) else None
            rows.append(
                {
                    "product_id": member.tiktok_product_id,
                    "product_title": title,
                    "arm": member.arm,
                    "card_id": str(member.action_card_id) if member.action_card_id else None,
                    "card_status": card.status if card is not None else None,
                    "surfaced_at": _iso(card.surfaced_at) if card is not None else None,
                    "approved": bool(card is not None and card.approved_at is not None),
                    "released_at": _iso(member.released_at),
                }
            )
        verdict = group.verdict if isinstance(group.verdict, dict) else None
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
                "treated": sum(1 for r in rows if r["arm"] == ARM_TREATED),
                "control": sum(1 for r in rows if r["arm"] == ARM_CONTROL),
                "members": rows,
                "verdict": verdict,
                #: D41.3: the primary verdict's simulated false-alarm rate (None before).
                "false_alarm": (verdict or {}).get("false_alarm"),
                "seller_sentence": seller_sentence(key, len(rows), verdict),
            }
        )
    return out


__all__ = [
    "CONTROL_DELAY_DAYS",
    "LABEL_MEASURING",
    "LABEL_NOT_ENOUGH",
    "RECHECK_EVERY_DAYS",
    "RECHECK_UNTIL_DAYS",
    "LABEL_PRELIMINARY",
    "LAUNCH_WINDOW_DAYS",
    "MIN_GROUP_SIZE",
    "SUPPRESSED_REASON_GROUP_CONTROL",
    "GroupKey",
    "GroupPass",
    "apply_groups",
    "assign_arms",
    "build_verdict",
    "card_group_key",
    "compare",
    "control_count",
    "group_views",
    "measure_due_groups",
    "new_seed",
    "payload_group_key",
    "seller_sentence",
    "seller_sentences",
]
