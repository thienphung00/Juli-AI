"""Decision emission/surfacing budget — ADR-038 §6, #716 (B-4), fasttrack D24.17.

Decides which persisted Action Card *candidates* (``status == "active"``)
surface into the Demo active set. Deliberately independent of recomputation:
``services.action_cards.persist`` refreshes a candidate this module has not yet
surfaced on every scoring run regardless of budget (Collision 1, #716); this
module runs on its own cadence and writes only the surfacing columns
(``ActionCard.surfaced_at`` / ``ActionCard.suppressed_reason``), the
``expired`` status of a card past its validity, and the surfacing ledger —
never title/priority/payload/computed_at.

**D24.17 limits (owner, 2026-10-10), one for every shop.** At most
``daily_new_cap`` (5) cards surfaced for the first time per shop day,
``weekly_new_cap`` (25) per shop week, ``max_open`` (30) open at once. Days and
weeks are the shop's (Vietnam, UTC+7; weeks start Monday). Campaign-plan cards
(:data:`CAMPAIGN_PLAN_WORKFLOW_KEYS`) are outside every limit.

- **Sticky.** A surfaced card keeps its ``surfaced_at`` (the moment it was first
  put in front of the seller) until it leaves the desk: the seller acts, it
  expires, or the producer withdraws it (``optimize_product_cards`` keeps it at
  least ``min_stay_days`` unless it is no longer valid).
- **Validity.** ``validity_days`` (7) after surfacing it becomes ``expired``.
  The same action on the same subject may return ``cooldown_days`` (7) after
  that (``persist`` / ``optimize_product_cards`` own the return; see
  :func:`expired_card_returns`).
- **Fixed daily slots** (D24.21 (4), owner 2026-10-10). Every shop day --
  the first one included -- is split by executor (``daily_slots``: at most 3
  Juli / Juli + ảnh, 1 Seller Center, 1 content -- P14-E video/LIVE cards).
  Each type is ranked by its own priority (expected GMV × calibration ×
  reason penalty, set by its producer); a slot with no candidate stays
  **empty** -- no backfill from another type. The weekly and open limits still
  bind across all slots. This replaced D24.17's first-day-only mix.

**Surfacing ledger.** ``decision_emission_novelty_ledger`` (the #716 weekly
novelty ledger) now holds one row per surfacing: ``workflow_key`` carries
``<card id hex>@<shop day yyyymmdd>`` and ``week_start`` the shop week's
Monday. ``surfaced_at`` cannot count surfacings — a dismissed or withdrawn
card clears it — so the per-day and per-week counts are read here, and no
schema change is needed. Rows written before D24.17 (one per workflow key and
week) still count as one surfacing each.

``SUPPRESSED_REASONS`` below is this module's vocabulary and answers "was this
candidate surfaced?". The emission path owns a separate, disjoint set
(``persist.REVISION_SUPPRESSED_REASONS``) answering "was a row written at
all?"; those never reach ``ActionCard.suppressed_reason`` (ADR-087 d.6).

Postgres is sole source of truth here. Nothing in this module reads or writes
Redis.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import (
    EXECUTOR_CONTENT,
    EXECUTOR_JULI,
    EXECUTOR_SELLER_CENTER,
    DecisionEmissionConfig,
    decision_emission_config,
)
from juli_backend.models.models import ActionCard, DecisionEmissionNoveltyLedger
from juli_backend.services.content_cards.constants import (
    CONTENT_WORKFLOW_KEYS as _P14E_CONTENT_WORKFLOW_KEYS,
)
from juli_backend.services.content_cards.constants import EXECUTOR_JULI_DRAFTS

logger = logging.getLogger(__name__)

#: Open-card ceiling reached (``max_open``). The string predates D24.17.
SUPPRESSED_REASON_ACTIVE_CAP = "active_cap"
SUPPRESSED_REASON_COOLDOWN = "cooldown"
#: Today's ``daily_new_cap`` is used up.
SUPPRESSED_REASON_DAILY_CAP = "daily_cap"
#: This week's ``weekly_new_cap`` is used up. The string predates D24.17 (it
#: was the never-assigned soft novelty quota of #716); since D24.17 it is a
#: real, hard weekly limit on new cards.
SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP = "weekly_novelty_cap"
SUPPRESSED_REASON_WEEKLY_CAP = SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP

SUPPRESSED_REASONS: frozenset[str] = frozenset(
    {
        SUPPRESSED_REASON_ACTIVE_CAP,
        SUPPRESSED_REASON_COOLDOWN,
        SUPPRESSED_REASON_DAILY_CAP,
        SUPPRESSED_REASON_WEEKLY_CAP,
    }
)

#: A surfaced card past ``validity_days`` (D24.17). Not ``active``, so it
#: leaves the Demo active set; ``surfaced_at`` is kept as history.
EXPIRED_STATUS = "expired"
#: ``metadata_json`` key stamped with the moment a card expired.
EXPIRED_AT_METADATA_KEY = "expired_at"

#: Campaign-plan cards ("Kế hoạch chiến dịch", D24.10) sit outside the D24.17
#: limits and the 7-day validity (a plan is valid until registration closes).
#: No producer writes them yet; this is the hook.
CAMPAIGN_PLAN_WORKFLOW_KEYS: frozenset[str] = frozenset({"campaign_plan"})

#: Workflows whose cards fill the daily ``content`` slot (video / LIVE,
#: "Juli soạn · bạn làm", D24.4): P14-E's ``content_video`` / ``content_live``.
#: A card of any workflow can also claim it with ``recommendation_payload``
#: ``card_executor`` = ``juli_drafts`` (P14-E) or ``executor_type`` = ``video``
#: / ``live``. Content cards obey every limit, the validity and the 3-day stay
#: here like any other card; P14-E's ≤ 5 new per week is a sub-limit applied
#: when they are written (``content_cards.emission``).
CONTENT_WORKFLOW_KEYS: frozenset[str] = _P14E_CONTENT_WORKFLOW_KEYS
_CONTENT_EXECUTOR_TYPES = frozenset({"video", "live"})
_CONTENT_CARD_EXECUTORS = frozenset({EXECUTOR_JULI_DRAFTS})

#: Executor slot of a card with no ADR-106 lever (legacy workflows, rule
#: pipeline cards). Those are run by the Juli agent, so they take ``juli`` slots.
EXECUTOR_OTHER = "other"

#: The shop's clock (Vietnam, UTC+7) for "day" and "week".
SHOP_UTC_OFFSET = timedelta(hours=7)

# Only "active" (candidate, un-actioned) rows are eligible for surfacing
# consideration. Anything in persist.IN_FLIGHT_STATUSES has already left the
# candidate pool structurally and is not re-litigated here.
_CANDIDATE_STATUS = "active"


@dataclass(frozen=True, slots=True)
class EmissionBudgetOutcome:
    """Result of one ``apply_emission_budget`` run for a shop.

    ``surfaced`` is the whole open set after the run (cards already open plus
    the ones surfaced now); ``newly_surfaced`` only the latter; ``expired`` the
    cards this run moved to :data:`EXPIRED_STATUS`.
    """

    surfaced: list[ActionCard]
    suppressed: dict[str, list[ActionCard]]
    newly_surfaced: list[ActionCard] = field(default_factory=list)
    expired: list[ActionCard] = field(default_factory=list)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def shop_day(now: datetime) -> date:
    """The shop's calendar day (UTC+7) at *now*."""
    return (_as_aware(now).astimezone(UTC) + SHOP_UTC_OFFSET).date()


def shop_week_start(now: datetime) -> date:
    """Monday of the shop's week at *now*."""
    today = shop_day(now)
    return today - timedelta(days=today.weekday())


def _shop_day_start_utc(now: datetime) -> datetime:
    day = shop_day(now)
    return datetime(day.year, day.month, day.day, tzinfo=UTC) - SHOP_UTC_OFFSET


def _payload(card: ActionCard) -> dict:
    try:
        payload = json.loads(card.recommendation_payload or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def executor_slot(card: ActionCard) -> str:
    """Who carries *card* out (D24.17); :func:`daily_slot` maps it to a day slot."""
    from juli_backend.services.demo_decisions.card_view import LEVERS

    payload = _payload(card)
    if (
        card.workflow_key in CONTENT_WORKFLOW_KEYS
        or payload.get("card_executor") in _CONTENT_CARD_EXECUTORS
        or payload.get("executor_type") in _CONTENT_EXECUTOR_TYPES
    ):
        return EXECUTOR_CONTENT
    diagnosis = payload.get("diagnosis")
    lever = diagnosis.get("lever") if isinstance(diagnosis, dict) else None
    code = lever.get("code") if isinstance(lever, dict) else None
    if not isinstance(code, str) or code not in LEVERS:
        return EXECUTOR_OTHER
    executor = LEVERS[code][1]
    if executor in ("juli", "juli_with_photo"):
        return EXECUTOR_JULI
    if executor == EXECUTOR_SELLER_CENTER:
        return EXECUTOR_SELLER_CENTER
    return EXECUTOR_OTHER


def expired_at(card: ActionCard, *, validity_days: int) -> datetime | None:
    """When *card* expired: the stamped moment, else ``surfaced_at`` + validity."""
    try:
        meta = json.loads(card.metadata_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    raw = meta.get(EXPIRED_AT_METADATA_KEY) if isinstance(meta, dict) else None
    if isinstance(raw, str):
        try:
            return _as_aware(datetime.fromisoformat(raw))
        except ValueError:
            pass
    if card.surfaced_at is not None:
        return _as_aware(card.surfaced_at) + timedelta(days=validity_days)
    if card.updated_at is not None:
        return _as_aware(card.updated_at)
    return None


def expired_card_returns(
    card: ActionCard, *, now: datetime, cooldown_days: int, validity_days: int
) -> bool:
    """Whether the action of an expired *card* may be proposed again (7 days on)."""
    moment = expired_at(card, validity_days=validity_days)
    if moment is None:
        return True
    return _as_aware(now) - moment >= timedelta(days=cooldown_days)


def _expire(card: ActionCard, now: datetime) -> None:
    card.status = EXPIRED_STATUS
    card.suppressed_reason = None
    try:
        meta = json.loads(card.metadata_json or "{}")
    except json.JSONDecodeError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    meta[EXPIRED_AT_METADATA_KEY] = now.isoformat()
    card.metadata_json = json.dumps(meta)


def _terminal_marker(card: ActionCard) -> datetime | None:
    """Most recent terminal-action timestamp on *card*, if any.

    Considers all three terminal markers (approved_at / executed_at /
    dismissed_at), read off already-loaded rows; no query of its own.
    """
    raw_markers = (card.approved_at, card.executed_at, card.dismissed_at)
    markers = [ts for ts in raw_markers if ts is not None]
    if not markers:
        return None
    return max(_as_aware(ts) for ts in markers)


def _in_cooldown(card: ActionCard, *, now: datetime, cooldown_days: int) -> bool:
    marker = _terminal_marker(card)
    if marker is None:
        return False
    return _as_aware(now) - marker < timedelta(days=cooldown_days)


def _ledger_key(card: ActionCard, day: date) -> str:
    return f"{card.id.hex}@{day:%Y%m%d}"


async def _surfacings_this_week(
    session: AsyncSession, shop_id: uuid.UUID, week_start: date
) -> list[DecisionEmissionNoveltyLedger]:
    stmt = select(DecisionEmissionNoveltyLedger).where(
        DecisionEmissionNoveltyLedger.shop_id == shop_id,
        DecisionEmissionNoveltyLedger.week_start == week_start,
    )
    return list((await session.execute(stmt)).scalars().all())


def _log_suppressed(shop_id_str: str, card: ActionCard, reason: str) -> None:
    """One structured log entry per suppressed candidate (#716 AC6).

    Carries only system identifiers (shop id, workflow key, reason code) —
    never ``card.title`` / ``card.description`` / ``card.recommendation_payload``
    (PRD security stories 22/23).
    """
    logger.info(
        "emission_budget_suppressed",
        extra={
            "shop_id": shop_id_str,
            "workflow_key": card.workflow_key,
            "suppressed_reason": reason,
        },
    )


async def _with_shop_card_cap(
    session: AsyncSession, shop_id: uuid.UUID, config: DecisionEmissionConfig
) -> DecisionEmissionConfig:
    """The seller's "Số thẻ mở cùng lúc" (ADR-109 d.12), when set, lowers ``max_open``.

    Fast track P8-C; D24.17 keeps it as the seller's own rule (D24.2 "the
    seller's rules" gate). Unset keeps the configured ceiling (30).
    """
    from juli_backend.services import shop_rules

    cap = await shop_rules.configured_max_open_cards(session, shop_id)
    if cap is None or cap >= config.max_open:
        return config
    return replace(config, max_open=cap)


def daily_slot(card: ActionCard) -> str:
    """The daily slot *card* takes (D24.21 (4)): ``other`` cards share ``juli``."""
    slot = executor_slot(card)
    return EXECUTOR_JULI if slot == EXECUTOR_OTHER else slot


def daily_slot_pick(
    cards: list[ActionCard],
    room: int,
    slots: dict[str, int],
    fill_order: tuple[str, ...],
) -> list[ActionCard]:
    """Today's new cards: up to ``slots[slot]`` of each type, in its own priority order.

    *cards* is in priority order; *slots* is the room left in each slot today;
    *room* the room left across all slots (weekly / open / daily). Slots fill in
    *fill_order*. A slot without a candidate stays empty (no backfill). In the
    ``juli`` slot the ADR-106 Juli cards go first (their own ranking), then
    legacy cards (``other``: a different priority scale, not comparable).
    Returns the chosen cards in priority order.
    """
    chosen: list[ActionCard] = []
    legacy_last = sorted(cards, key=lambda c: executor_slot(c) == EXECUTOR_OTHER)
    for slot in fill_order:
        left = slots.get(slot, 0)
        for card in legacy_last:
            if len(chosen) >= room or left <= 0:
                break
            if daily_slot(card) != slot:
                continue
            chosen.append(card)
            left -= 1
    order = {card.id: index for index, card in enumerate(cards)}
    return sorted(chosen, key=lambda c: order[c.id])


async def _surfaced_today_by_slot(
    session: AsyncSession, rows: list[DecisionEmissionNoveltyLedger], day_start: datetime
) -> dict[str, int]:
    """Slot -> how many cards were surfaced for the first time today (ledger rows)."""
    ids: list[uuid.UUID] = []
    for row in rows:
        if _as_aware(row.first_surfaced_at) < day_start:
            continue
        hex_id, sep, _day = row.workflow_key.partition("@")
        if not sep:
            continue
        try:
            ids.append(uuid.UUID(hex=hex_id))
        except ValueError:
            continue
    counts: dict[str, int] = {}
    if not ids:
        return counts
    cards = (await session.execute(select(ActionCard).where(ActionCard.id.in_(ids)))).scalars()
    for card in cards:
        slot = daily_slot(card)
        counts[slot] = counts.get(slot, 0) + 1
    return counts


async def apply_emission_budget(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime | None = None,
    config: DecisionEmissionConfig | None = None,
) -> EmissionBudgetOutcome:
    """Expire, keep and add to the shop's surfaced set under the D24.17 limits.

    Over every ``status == "active"`` candidate row for *shop_id*, in priority
    order:

    1. **Expire.** A surfaced card ``validity_days`` (7) after its
       ``surfaced_at`` becomes ``expired`` (campaign plans excepted).
    2. **Keep.** Every other surfaced card stays surfaced, its ``surfaced_at``
       untouched (D24.17 "stays at least 3 days" — withdrawal belongs to the
       producer, which knows when a card is no longer valid).
    3. **Cooldown (hard).** A draft inside its 7-day post-terminal-action
       window never surfaces.
    4. **Room.** ``min(daily_new_cap − surfaced today, weekly_new_cap −
       surfaced this week, max_open − open)``; campaign-plan drafts surface
       without taking room. Within it, every day's fixed executor slots
       (:func:`daily_slot_pick`, D24.21 (4)): each slot takes its own type in
       priority order, an empty slot stays empty. Drafts left over are
       suppressed with the binding limit's reason, or ``daily_cap`` when
       their slot is full.

    Every newly surfaced card adds one ledger row. Performs no commit; the
    caller controls the transaction.
    """
    now = _as_aware(now) if now is not None else datetime.now(UTC)
    config = await _with_shop_card_cap(session, shop_id, config or decision_emission_config())
    shop_id_str = str(shop_id)
    today = shop_day(now)
    week_start = shop_week_start(now)
    day_start = _shop_day_start_utc(now)

    stmt = (
        select(ActionCard)
        .where(ActionCard.shop_id == shop_id, ActionCard.status == _CANDIDATE_STATUS)
        .order_by(ActionCard.priority.asc(), ActionCard.workflow_key.asc())
    )
    candidates = list((await session.execute(stmt)).scalars().all())
    week_rows = await _surfacings_this_week(session, shop_id, week_start)
    ledger_keys = {row.workflow_key for row in week_rows}
    surfaced_week = len(week_rows)
    surfaced_today = sum(1 for row in week_rows if _as_aware(row.first_surfaced_at) >= day_start)

    open_cards: list[ActionCard] = []
    expired: list[ActionCard] = []
    drafts: list[ActionCard] = []
    for card in candidates:
        if card.surfaced_at is None:
            drafts.append(card)
            continue
        campaign = card.workflow_key in CAMPAIGN_PLAN_WORKFLOW_KEYS
        age = now - _as_aware(card.surfaced_at)
        if not campaign and age >= timedelta(days=config.validity_days):
            _expire(card, now)
            expired.append(card)
            continue
        card.suppressed_reason = None
        open_cards.append(card)

    suppressed: dict[str, list[ActionCard]] = {reason: [] for reason in SUPPRESSED_REASONS}
    open_counted = sum(1 for c in open_cards if c.workflow_key not in CAMPAIGN_PLAN_WORKFLOW_KEYS)
    # On a tie the earlier limit names the suppression: daily, weekly, open.
    limits = (
        (config.daily_new_cap - surfaced_today, SUPPRESSED_REASON_DAILY_CAP),
        (config.weekly_new_cap - surfaced_week, SUPPRESSED_REASON_WEEKLY_CAP),
        (config.max_open - open_counted, SUPPRESSED_REASON_ACTIVE_CAP),
    )
    room, room_reason = min(limits, key=lambda item: item[0])
    room = max(room, 0)

    eligible: list[ActionCard] = []
    campaign_drafts: list[ActionCard] = []
    for card in drafts:
        if _in_cooldown(card, now=now, cooldown_days=config.cooldown_days):
            card.suppressed_reason = SUPPRESSED_REASON_COOLDOWN
            suppressed[SUPPRESSED_REASON_COOLDOWN].append(card)
            _log_suppressed(shop_id_str, card, SUPPRESSED_REASON_COOLDOWN)
            continue
        if card.workflow_key in CAMPAIGN_PLAN_WORKFLOW_KEYS:
            campaign_drafts.append(card)
        else:
            eligible.append(card)

    used_today = await _surfaced_today_by_slot(session, week_rows, day_start)
    slot_room = {
        slot: max(count - used_today.get(slot, 0), 0) for slot, count in config.daily_slots
    }
    fill_order = tuple(slot for slot, _count in config.daily_slots)
    chosen = daily_slot_pick(eligible, room, slot_room, fill_order)
    chosen_ids = {card.id for card in chosen}
    room_left = room - len(chosen)

    newly_surfaced: list[ActionCard] = []
    for card in eligible:
        if card.id not in chosen_ids:
            # Overall room used up -> the binding limit; else its slot is full
            # (or has no daily slot) -> today's limit for that type.
            reason = room_reason if room_left <= 0 else SUPPRESSED_REASON_DAILY_CAP
            card.suppressed_reason = reason
            suppressed[reason].append(card)
            _log_suppressed(shop_id_str, card, reason)
            continue
        card.surfaced_at = now
        card.suppressed_reason = None
        newly_surfaced.append(card)
        key = _ledger_key(card, today)
        if key not in ledger_keys:
            ledger_keys.add(key)
            session.add(
                DecisionEmissionNoveltyLedger(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    week_start=week_start,
                    workflow_key=key,
                    first_surfaced_at=now,
                )
            )
    for card in campaign_drafts:
        card.surfaced_at = now
        card.suppressed_reason = None
        newly_surfaced.append(card)

    await session.flush()

    logger.info(
        "emission_budget_applied",
        extra={
            "shop_id": shop_id_str,
            "surfaced_count": len(open_cards) + len(newly_surfaced),
            "newly_surfaced_count": len(newly_surfaced),
            "expired_count": len(expired),
            "suppressed_active_cap": len(suppressed[SUPPRESSED_REASON_ACTIVE_CAP]),
            "suppressed_daily_cap": len(suppressed[SUPPRESSED_REASON_DAILY_CAP]),
            "suppressed_cooldown": len(suppressed[SUPPRESSED_REASON_COOLDOWN]),
            "suppressed_weekly_novelty_cap": len(suppressed[SUPPRESSED_REASON_WEEKLY_CAP]),
        },
    )
    return EmissionBudgetOutcome(
        surfaced=open_cards + newly_surfaced,
        suppressed=suppressed,
        newly_surfaced=newly_surfaced,
        expired=expired,
    )
