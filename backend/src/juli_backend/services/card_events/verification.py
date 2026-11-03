"""Read-back verification of an assisted execution (P90 plan "Assisted execution" step 4).

A person saved an approved change in Seller Centre and marked it done (an ``executed`` event
whose payload carries ``change``). The Connector's NEXT readings are the proof. This module
compares them with the expected after-value and logs one event per execution:

- ``verified`` -- an observation taken after ``executed_at`` shows the expected value (the first
  such observation; its value and time go in the payload; the 14 / 28-day measurement of
  ADR-107 starts at that time);
- ``mismatch`` -- at the deadline (``VERIFY_WINDOW`` = 48 h after ``executed_at``) the shop was
  read after the change but never showed the expected value (the latest observed value is
  reported);
- ``not_seen`` -- at the deadline nothing was read after the change.

Before the deadline an unmatched execution stays pending: the person may save later, and a
Connector day that read the old value is not yet a failure. A deadline outcome is final for
that execution (a later match is not recorded; a new execution gets a new reference).

``executed`` payload contract (written by the card UI, Step 9)::

    payload["change"] = {
        "change_kind": "title" | "price" | "images" | "stock" | "daily_budget" | "roas_target"
                       | "voucher",
        "target":   {"item_id", "variation_id"?} | {"campaign_id"?} | {"voucher_id"},
        "expected": {<field>: <after value>, ...},
    }

What each kind reads (the Connector posts these datasets; all after ``executed_at``):

=============  ===========================================  ================================
change_kind    observation                                  fields
=============  ===========================================  ================================
title          ``platform_items.name`` (item_catalog)       ``title``
price          ``platform_item_snapshots``                  ``current_price``, ``list_price``
stock          ``platform_item_snapshots``                  ``stock``
images         ``platform_item_snapshots``                  ``image_urls`` (cover only today)
daily_budget   ``ads_campaign_daily`` (campaign row)        ``daily_budget``
roas_target    ``ads_campaign_daily`` (campaign row, or     ``roas_target``
               the shop-level ``roi_target`` row)
voucher        ``voucher_settings`` (``platform_promotions``) ``discount_amount``,
                                                            ``discount_percent``,
                                                            ``min_spend``, ``max_value``,
                                                            ``usage_limit``, ``starts_at``,
                                                            ``ends_at``
=============  ===========================================  ================================

Reads only the shop's own rows (the caller holds its scope); never calls Seller Centre.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    ACTOR_SYSTEM,
    EVENT_EXECUTED,
    EVENT_MISMATCH,
    EVENT_NOT_SEEN,
    EVENT_VERIFIED,
    CardEvent,
)
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import PlatformItem, PlatformPromotion
from juli_backend.models.shopee_profit import PlatformItemSnapshot
from juli_backend.services.card_events import keys
from juli_backend.services.card_events.writer import EventSpec, as_utc, insert_event
from juli_backend.services.ingest.mapping import SHOPEE_PROMO_TYPES, campaign_segment

#: How long the Connector has to show the change (plan: "no change seen within 48 h").
VERIFY_WINDOW = timedelta(hours=48)
#: An execution older than this that is still unresolved is left alone.
LOOKBACK = timedelta(days=30)
PLATFORM = "shopee"
VERIFICATION_EVENTS = (EVENT_VERIFIED, EVENT_MISMATCH, EVENT_NOT_SEEN)
CHANGE_KINDS = (
    "title",
    "price",
    "images",
    "stock",
    "daily_budget",
    "roas_target",
    "voucher",
)
VOUCHER_FIELDS = ("discount_amount", "discount_percent", "min_spend", "max_value", "usage_limit")


@dataclass(frozen=True)
class ExecutedChange:
    shop_id: uuid.UUID
    card_id: uuid.UUID
    execution_ref: str
    change_kind: str
    target: Mapping[str, Any]
    expected: Mapping[str, Any]
    executed_at: datetime  # aware UTC
    workflow_key: str = "shopee_assisted_execution"
    subject_type: str = ""
    subject_id: str = ""

    @property
    def deadline(self) -> datetime:
        return self.executed_at + VERIFY_WINDOW


@dataclass(frozen=True)
class Observation:
    observed: Mapping[str, Any]
    observed_at: datetime  # aware UTC


@dataclass(frozen=True)
class Verdict:
    #: ``verified`` / ``mismatch`` / ``not_seen``; None = still pending.
    outcome: str | None
    observed: Mapping[str, Any] = field(default_factory=dict)
    observed_at: datetime | None = None


# -- comparison (pure) ------------------------------------------------------------------


def _text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value)).split())


def same_value(expected: Any, observed: Any) -> bool:
    """Numbers by value, text by NFKC with single spaces, lists item by item."""
    if expected is None or observed is None:
        return expected is None and observed is None
    if isinstance(expected, list | tuple):
        return (
            isinstance(observed, list | tuple)
            and len(expected) == len(observed)
            and all(same_value(a, b) for a, b in zip(expected, observed, strict=True))
        )
    if isinstance(expected, bool) or isinstance(observed, bool):
        return expected == observed
    try:
        return Decimal(str(expected)) == Decimal(str(observed))
    except InvalidOperation:
        return _text(expected) == _text(observed)


def matches(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> bool:
    return bool(expected) and all(
        name in observed and same_value(value, observed[name]) for name, value in expected.items()
    )


def evaluate(change: ExecutedChange, observations: list[Observation], now: datetime) -> Verdict:
    """The verdict on one execution from the observations taken after ``executed_at``."""
    after = sorted(
        (o for o in observations if o.observed_at > change.executed_at),
        key=lambda o: o.observed_at,
    )
    for obs in after:
        if matches(change.expected, obs.observed):
            return Verdict(EVENT_VERIFIED, obs.observed, obs.observed_at)
    if as_utc(now) < change.deadline:
        return Verdict(None)
    if after:
        return Verdict(EVENT_MISMATCH, after[-1].observed, after[-1].observed_at)
    return Verdict(EVENT_NOT_SEEN)


# -- observations (DB) ------------------------------------------------------------------


def _naive_utc(value: datetime) -> datetime:
    return as_utc(value).replace(tzinfo=None)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


def _numbers(extra: Mapping[str, Any] | None, names: tuple[str, ...]) -> dict[str, Any]:
    return {n: (extra or {})[n] for n in names if (extra or {}).get(n) is not None}


async def observations_for(session: AsyncSession, change: ExecutedChange) -> list[Observation]:
    """Everything the Connector stored for the change's target after ``executed_at``."""
    since = _naive_utc(change.executed_at)
    shop_id, target, kind = change.shop_id, change.target, change.change_kind
    if kind == "title":
        rows = (
            await session.execute(
                select(PlatformItem.name, PlatformItem.captured_at).where(
                    PlatformItem.shop_id == shop_id,
                    PlatformItem.platform == PLATFORM,
                    PlatformItem.item_id == str(target["item_id"]),
                    PlatformItem.variation_id == "",
                    PlatformItem.captured_at > since,
                    PlatformItem.name.is_not(None),
                )
            )
        ).all()
        return [Observation({"title": name}, _utc(at)) for name, at in rows]
    if kind in ("price", "stock", "images"):
        snaps = (
            (
                await session.execute(
                    select(PlatformItemSnapshot).where(
                        PlatformItemSnapshot.shop_id == shop_id,
                        PlatformItemSnapshot.platform == PLATFORM,
                        PlatformItemSnapshot.item_id == str(target["item_id"]),
                        PlatformItemSnapshot.variation_id == str(target.get("variation_id", "")),
                        PlatformItemSnapshot.captured_at > since,
                    )
                )
            )
            .scalars()
            .all()
        )
        fields = {
            "price": lambda s: {"current_price": s.current_price, "list_price": s.list_price},
            "stock": lambda s: {"stock": s.stock},
            "images": lambda s: {"image_urls": list(s.image_urls or [])},
        }[kind]
        return [Observation(fields(s), _utc(s.captured_at)) for s in snaps]
    if kind in ("daily_budget", "roas_target"):
        campaign_id = target.get("campaign_id")
        segment = campaign_segment(str(campaign_id)) if campaign_id else "all"
        rows = (
            (
                await session.execute(
                    select(PlatformDailyMetric).where(
                        PlatformDailyMetric.shop_id == shop_id,
                        PlatformDailyMetric.platform == PLATFORM,
                        PlatformDailyMetric.dataset == "ads_campaign_daily",
                        PlatformDailyMetric.segment == segment,
                        PlatformDailyMetric.captured_at > since,
                    )
                )
            )
            .scalars()
            .all()
        )
        out = []
        for row in rows:
            extra = row.extra or {}
            if kind == "daily_budget":
                value = extra.get("daily_budget")
            else:
                value = extra.get("roi_two_target") if campaign_id else extra.get("roi_target")
            if value is not None:
                key = "daily_budget" if kind == "daily_budget" else "roas_target"
                out.append(Observation({key: value}, _utc(row.captured_at)))
        return out
    if kind == "voucher":
        rows = (
            (
                await session.execute(
                    select(PlatformPromotion).where(
                        PlatformPromotion.shop_id == shop_id,
                        PlatformPromotion.platform == PLATFORM,
                        PlatformPromotion.promo_type == SHOPEE_PROMO_TYPES["Voucher"],
                        PlatformPromotion.captured_at > since,
                    )
                )
            )
            .scalars()
            .all()
        )
        out = []
        for row in rows:
            extra = row.extra or {}
            if str(extra.get("voucher_id")) != str(target["voucher_id"]):
                continue
            seen = _numbers(extra, VOUCHER_FIELDS)
            seen["starts_at"] = row.starts_at.isoformat()
            if row.ends_at is not None:
                seen["ends_at"] = row.ends_at.isoformat()
            out.append(Observation(seen, _utc(row.captured_at)))
        return out
    raise ValueError(f"unknown change_kind {kind!r}")


# -- events (DB) ------------------------------------------------------------------------


async def record_verdict(
    session: AsyncSession, change: ExecutedChange, verdict: Verdict, *, now: datetime
) -> bool:
    """Write the verdict's event (idempotent per execution and outcome); False when pending
    or already written."""
    if verdict.outcome is None:
        return False
    occurred = verdict.observed_at or (
        change.deadline if verdict.outcome == EVENT_NOT_SEEN else as_utc(now)
    )
    return await insert_event(
        session,
        EventSpec(
            shop_id=change.shop_id,
            card_id=change.card_id,
            event_type=verdict.outcome,
            actor=ACTOR_SYSTEM,
            occurred_at=occurred,
            workflow_key=change.workflow_key,
            subject_type=change.subject_type or "item",
            subject_id=change.subject_id or str(change.target.get("item_id", "")),
            dedup_key=keys.verification(change.execution_ref, verdict.outcome),
            payload={
                "execution_ref": change.execution_ref,
                "change_kind": change.change_kind,
                "target": dict(change.target),
                "expected": dict(change.expected),
                "observed": dict(verdict.observed),
                "observed_at": verdict.observed_at,
                "executed_at": change.executed_at,
                "deadline": change.deadline,
            },
        ),
    )


async def pending_changes(
    session: AsyncSession, shop_id: uuid.UUID, now: datetime
) -> list[ExecutedChange]:
    """Executions of the shop (``executed`` events carrying ``payload.change``, inside the
    look-back) with no verification event yet."""
    cutoff = as_utc(now) - LOOKBACK
    executed = (
        (
            await session.execute(
                select(CardEvent).where(
                    CardEvent.shop_id == shop_id,
                    CardEvent.event_type == EVENT_EXECUTED,
                    CardEvent.card_id.is_not(None),
                    CardEvent.occurred_at >= cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    done = set(
        (
            await session.execute(
                select(CardEvent.dedup_key).where(
                    CardEvent.shop_id == shop_id, CardEvent.event_type.in_(VERIFICATION_EVENTS)
                )
            )
        )
        .scalars()
        .all()
    )
    out = []
    for event in executed:
        spec = (event.payload or {}).get("change")
        if not isinstance(spec, dict) or spec.get("change_kind") not in CHANGE_KINDS:
            continue
        ref = event.dedup_key
        if any(keys.verification(ref, name) in done for name in VERIFICATION_EVENTS):
            continue
        out.append(
            ExecutedChange(
                shop_id=shop_id,
                card_id=event.card_id,
                execution_ref=ref,
                change_kind=spec["change_kind"],
                target=spec.get("target") or {},
                expected=spec.get("expected") or {},
                executed_at=as_utc(event.occurred_at),
                workflow_key=event.workflow_key,
                subject_type=event.subject_type,
                subject_id=event.subject_id,
            )
        )
    return out


@dataclass(frozen=True)
class VerificationCounts:
    checked: int = 0
    verified: int = 0
    mismatch: int = 0
    not_seen: int = 0
    pending: int = 0
    failed: int = 0


async def verify_shop(
    session: AsyncSession, shop_id: uuid.UUID, now: datetime
) -> VerificationCounts:
    """Check every pending execution of one shop and write the events (no commit)."""
    tally = {"checked": 0, "verified": 0, "mismatch": 0, "not_seen": 0, "pending": 0, "failed": 0}
    for change in await pending_changes(session, shop_id, now):
        tally["checked"] += 1
        try:
            verdict = evaluate(change, await observations_for(session, change), now)
            await record_verdict(session, change, verdict, now=now)
        except (KeyError, ValueError):
            tally["failed"] += 1  # a malformed target: counted, never stops the rest
            continue
        tally[verdict.outcome or "pending"] += 1
    return VerificationCounts(**tally)
