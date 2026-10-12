"""Shop terms: subscription periods, expiry states, the grant function (D28.4, D28.5).

A shop's term is the set of its ``shop_subscription_periods`` rows (migration
086); its expiry is the latest ``ends_on``. ``days_left = ends_on - today`` on
the shop's (UTC+7) calendar:

- ``none``: no period yet ("Chưa đặt thời hạn") -- Juli runs, NOT restricted;
- ``ok``: more than 14 days left -- Juli runs;
- ``soon``: 0–14 days left ("sắp hết") -- Juli runs;
- ``grace``: 1–7 days after expiry ("ân hạn") -- Juli runs, the seller sees an
  amber reminder;
- ``read_only``: 8+ days after expiry ("chỉ xem") -- no new cards, runs or
  drafting; data sync continues so a renewal resumes at once.

:func:`grant_period` is THE way a period is added -- by an Admin in Juli Ops
(``source="contract"``, ``reference`` = the contract number) and, later, by
the payment system (``source="payment"``, ``reference`` = its transaction id;
D28.5). It is idempotent on ``(source, reference)``: granting the same reference
again returns the existing period and adds nothing. A still-active shop's new
period starts at its current expiry; an expired one (grace or read-only)
starts today.

Every function runs under the shop's own scope (``with_shop_scope`` or the
seller's request scope); the table's RLS keys on ``app_current_shop_id()``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.subscriptions import (
    PLAN_BY_DAYS,
    SOURCES,
    ShopSubscriptionPeriod,
)

logger = logging.getLogger(__name__)

STATE_NONE = "none"
STATE_OK = "ok"
STATE_SOON = "soon"
STATE_GRACE = "grace"
STATE_READ_ONLY = "read_only"
STATES: tuple[str, ...] = (STATE_NONE, STATE_OK, STATE_SOON, STATE_GRACE, STATE_READ_ONLY)
#: "Sắp hết hạn": 0–14 days left.
SOON_DAYS = 14
#: "Ân hạn": Juli keeps running 7 days after expiry.
GRACE_DAYS = 7
PACKAGE_DAYS: tuple[int, ...] = (30, 365)
REFERENCE_MAX = 120
#: The shop's calendar (Vietnam, no DST).
SHOP_UTC_OFFSET = timedelta(hours=7)
CONTACT_EMAIL = "lienhe@app-juli.com"
#: HTTP 403 detail on every seller write a read-only shop is refused (D28.4).
READ_ONLY_DETAIL = f"Shop đang ở chế độ chỉ xem — liên hệ {CONTACT_EMAIL} để gia hạn."
READ_ONLY_CODE = "shop_read_only"


class GrantError(ValueError):
    """An invalid grant (422): bad package, source or reference."""


def shop_today(now: datetime | None = None) -> date:
    """Today on the shop's (UTC+7) calendar."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment.astimezone(UTC) + SHOP_UTC_OFFSET).date()


@dataclass(frozen=True)
class ShopTerm:
    state: str
    expires_on: date | None
    days_left: int | None
    grace_days_left: int | None

    @property
    def read_only(self) -> bool:
        return self.state == STATE_READ_ONLY

    def to_json(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "expires_on": self.expires_on.isoformat() if self.expires_on else None,
            "days_left": self.days_left,
            "grace_days_left": self.grace_days_left,
        }


NO_TERM = ShopTerm(state=STATE_NONE, expires_on=None, days_left=None, grace_days_left=None)


def term_for(expires_on: date | None, today: date) -> ShopTerm:
    """The state of a shop whose latest period ends on ``expires_on`` (pure)."""
    if expires_on is None:
        return NO_TERM
    left = (expires_on - today).days
    if left > SOON_DAYS:
        state = STATE_OK
    elif left >= 0:
        state = STATE_SOON
    elif left >= -GRACE_DAYS:
        state = STATE_GRACE
    else:
        state = STATE_READ_ONLY
    return ShopTerm(
        state=state,
        expires_on=expires_on,
        days_left=left,
        grace_days_left=GRACE_DAYS + left if state == STATE_GRACE else None,
    )


def period_json(period: ShopSubscriptionPeriod) -> dict[str, Any]:
    return {
        "id": str(period.id),
        "plan": period.plan,
        "days": period.days,
        "starts_on": period.starts_on.isoformat(),
        "ends_on": period.ends_on.isoformat(),
        "source": period.source,
        "reference": period.reference,
        "actor_email": period.actor_email,
        "created_at": period.created_at.isoformat() if period.created_at else None,
    }


async def list_periods(session: AsyncSession, shop_id: uuid.UUID) -> list[ShopSubscriptionPeriod]:
    """The shop's periods, oldest first. Caller holds the shop's scope."""
    rows = await session.execute(
        select(ShopSubscriptionPeriod)
        .where(ShopSubscriptionPeriod.shop_id == shop_id)
        .order_by(
            ShopSubscriptionPeriod.starts_on,
            ShopSubscriptionPeriod.created_at,
            ShopSubscriptionPeriod.id,
        )
    )
    return list(rows.scalars().all())


async def expiry(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    """The latest ``ends_on`` (None: no period yet)."""
    value = (
        await session.execute(
            select(func.max(ShopSubscriptionPeriod.ends_on)).where(
                ShopSubscriptionPeriod.shop_id == shop_id
            )
        )
    ).scalar_one_or_none()
    if isinstance(value, str):  # SQLite returns the aggregate as text
        return date.fromisoformat(value)
    return value


async def shop_term(
    session: AsyncSession, shop_id: uuid.UUID, today: date | None = None
) -> ShopTerm:
    """The shop's term now: state, expiry, days left, grace days left."""
    return term_for(await expiry(session, shop_id), today or shop_today())


async def is_read_only(
    session: AsyncSession, shop_id: uuid.UUID, today: date | None = None
) -> bool:
    """Enforcement read (cards, runs, drafting). A failed read never restricts: logged."""
    try:
        async with session.begin_nested():
            term = await shop_term(session, shop_id, today)
    except SQLAlchemyError:
        logger.warning("shop_term_read_failed", extra={"shop_id": str(shop_id)}, exc_info=True)
        return False
    if term.read_only:
        logger.info(
            "shop_read_only",
            extra={"shop_id": str(shop_id), "expires_on": str(term.expires_on)},
        )
    return term.read_only


@dataclass(frozen=True)
class Grant:
    period: ShopSubscriptionPeriod
    created: bool
    before: ShopTerm
    after: ShopTerm


def _clean_reference(reference: Any) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise GrantError("reference (số hợp đồng / mã thanh toán) is required")
    clean = reference.strip()
    if len(clean) > REFERENCE_MAX:
        raise GrantError(f"reference must be at most {REFERENCE_MAX} characters")
    return clean


def next_period_dates(current_expiry: date | None, days: int, today: date) -> tuple[date, date]:
    """Still active (expiry ≥ today) → start at the expiry; else start today."""
    start = current_expiry if current_expiry is not None and current_expiry >= today else today
    return start, start + timedelta(days=days)


async def _existing(
    session: AsyncSession, source: str, reference: str
) -> ShopSubscriptionPeriod | None:
    return (
        await session.execute(
            select(ShopSubscriptionPeriod).where(
                ShopSubscriptionPeriod.source == source,
                ShopSubscriptionPeriod.reference == reference,
            )
        )
    ).scalar_one_or_none()


async def grant_period(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    days: int,
    source: str,
    reference: str,
    actor_email: str | None,
    today: date | None = None,
) -> Grant:
    """Add one 30- or 365-day period (no commit). Idempotent on ``(source, reference)``.

    Caller holds the shop's scope. A reference already used for ANOTHER shop
    (invisible under this shop's RLS) fails on the unique constraint and is
    refused with :class:`GrantError`.
    """
    if isinstance(days, bool) or days not in PACKAGE_DAYS:
        raise GrantError("days must be 30 or 365")
    if source not in SOURCES:
        raise GrantError(f"source must be one of {', '.join(SOURCES)}")
    clean_ref = _clean_reference(reference)
    day = today or shop_today()
    current = await expiry(session, shop_id)
    before = term_for(current, day)
    existing = await _existing(session, source, clean_ref)
    if existing is not None:
        if existing.shop_id != shop_id:
            raise GrantError("this reference is already used for another shop")
        logger.info(
            "subscription_period_exists",
            extra={"shop_id": str(shop_id), "source": source, "period_id": str(existing.id)},
        )
        return Grant(period=existing, created=False, before=before, after=before)
    starts_on, ends_on = next_period_dates(current, days, day)
    period = ShopSubscriptionPeriod(
        id=uuid.uuid4(),
        shop_id=shop_id,
        plan=PLAN_BY_DAYS[days],
        days=days,
        starts_on=starts_on,
        ends_on=ends_on,
        source=source,
        reference=clean_ref,
        actor_email=actor_email,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    try:
        async with session.begin_nested():
            session.add(period)
            await session.flush()
    except IntegrityError:
        raise GrantError("this reference is already used for another shop") from None
    after = term_for(max(ends_on, current or ends_on), day)
    logger.info(
        "subscription_period_granted",
        extra={
            "shop_id": str(shop_id),
            "source": source,
            "days": days,
            "starts_on": starts_on.isoformat(),
            "ends_on": ends_on.isoformat(),
        },
    )
    return Grant(period=period, created=True, before=before, after=after)
