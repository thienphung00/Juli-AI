"""The system-wide monthly OpenAI limit (fast track P20, DECISIONS D28.3, tab Chi phí).

ONE number for the whole system, on top of each shop's own cap (D25.8,
``services/shop_rules/openai_cap.py``):

- **Cap**: ``ops_system_settings['openai_system_cap_usd']`` (Admin-editable in
  Juli Ops, audited), else ``OPENAI_SYSTEM_CAP_USD_DEFAULT`` (env, $50).
- **Spend**: every shop's ``workflow_runs.cost_usd`` + ``content_analyses.cost_usd``
  since the first instant of the same UTC+7 month as the per-shop cap
  (``openai_cap.month_start_utc``). On Postgres it is read through the SECURITY
  DEFINER ``openai_spend_since(timestamp)`` (migration 086) -- a tenant-scoped
  session sees only its own shop's rows; the function returns one number.
- **≥ 100 %**: :func:`system_cap_reached` is True and every OpenAI gate refuses
  with the distinct reason ``system_cap_reached`` -- content analysis
  (``content_analysis/costs.check``), drafting (``content_cards.driver.draft_gate_for``)
  and agent runs (``ops.overrides.CapGuardedLLMService``). Cards keep being emitted.
- **≥ 80 %**: a banner on every Ops page (``GET /v1/ops/costs``) and ONE e-mail
  per month to the active Admins (:func:`check_alert`, the hourly
  ``ops_openai_system_alert`` task), remembered in
  ``ops_system_settings['openai_alert_sent'] = {"month": "YYYY-MM", "level": 80|100}``.
  Without SMTP nothing is sent, ``openai_system_alert_unsent`` is logged and the
  month is NOT marked (the next run tries again).

``ops_system_settings`` holds no shop data: ``juli_app`` may SELECT it (the
gates), only ``juli_ops`` writes it (:func:`ops_role`).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.models.models import WorkflowRun
from juli_backend.models.ops import ROLE_ADMIN, OpsStaff, OpsSystemSetting
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import is_sqlite, ops_role
from juli_backend.services.shop_rules.openai_cap import SHOP_UTC_OFFSET, month_start_utc

logger = logging.getLogger(__name__)

SYSTEM_CAP_KEY = "openai_system_cap_usd"
ALERT_KEY = "openai_alert_sent"
DEFAULT_ENV = "OPENAI_SYSTEM_CAP_USD_DEFAULT"
FALLBACK_DEFAULT_USD = Decimal("50")
CAP_MIN_USD = Decimal("1")
CAP_MAX_USD = Decimal("100000")
WARN_PCT = Decimal("0.8")
REASON_SYSTEM_CAP = "system_cap_reached"
ACTION_SYSTEM_CAP = "openai_system_cap_set"
ACTION_SHOP_CAP = "openai_shop_cap_set"
#: What the seller sees where drafting would start (D28.3).
SELLER_PAUSED_VI = (
    "Juli tạm dừng soạn nội dung mới. Thẻ đề xuất và các bước bạn tự làm vẫn dùng bình thường."
)


class SystemCapError(ValueError):
    """An invalid system cap (422)."""


@dataclass(frozen=True)
class SystemCap:
    usd: Decimal
    is_default: bool
    updated_at: datetime | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class SystemCapStatus:
    month: str
    month_start_utc: datetime
    used_usd: Decimal
    cap: SystemCap

    @property
    def pct(self) -> Decimal:
        if self.cap.usd <= 0:
            return Decimal("1") if self.used_usd > 0 else Decimal("0")
        return self.used_usd / self.cap.usd

    @property
    def reached(self) -> bool:
        return self.used_usd >= self.cap.usd

    @property
    def warn(self) -> bool:
        return self.pct >= WARN_PCT

    @property
    def level(self) -> int | None:
        if self.reached:
            return 100
        if self.warn:
            return 80
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "used_usd": float(self.used_usd),
            "cap_usd": float(self.cap.usd),
            "cap_is_default": self.cap.is_default,
            "cap_updated_at": self.cap.updated_at.isoformat() if self.cap.updated_at else None,
            "cap_updated_by": self.cap.updated_by,
            "pct": float(self.pct),
            "level": self.level,
            "reached": self.reached,
        }


def default_cap_usd() -> Decimal:
    raw = os.environ.get(DEFAULT_ENV, "").strip()
    if not raw:
        return FALLBACK_DEFAULT_USD
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return FALLBACK_DEFAULT_USD
    return value if value.is_finite() and value >= 0 else FALLBACK_DEFAULT_USD


def validate_cap(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise SystemCapError("usd must be a number")
    try:
        cap = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SystemCapError("usd must be a number") from None
    if not cap.is_finite() or not CAP_MIN_USD <= cap <= CAP_MAX_USD:
        raise SystemCapError(f"usd must be between {CAP_MIN_USD} and {CAP_MAX_USD}")
    return cap.quantize(Decimal("0.01"))


def month_label(now: datetime | None = None) -> str:
    """``YYYY-MM`` of the shop (UTC+7) month containing ``now``."""
    start = month_start_utc(now) + SHOP_UTC_OFFSET
    return f"{start.year:04d}-{start.month:02d}"


async def _setting(session: AsyncSession, key: str) -> OpsSystemSetting | None:
    """Read one row as the session's own role (``juli_app`` has SELECT on this table)."""
    try:
        async with session.begin_nested():
            return await session.get(OpsSystemSetting, key, populate_existing=True)
    except SQLAlchemyError:
        logger.warning("ops_system_setting_read_failed", extra={"key": key}, exc_info=True)
        return None


async def system_cap(session: AsyncSession) -> SystemCap:
    row = await _setting(session, SYSTEM_CAP_KEY)
    if row is not None and row.value is not None:
        try:
            return SystemCap(
                usd=validate_cap(row.value),
                is_default=False,
                updated_at=row.updated_at,
                updated_by=row.updated_by,
            )
        except SystemCapError:
            logger.warning("ops_system_cap_invalid", extra={"value": str(row.value)[:40]})
    return SystemCap(usd=default_cap_usd(), is_default=True)


async def system_spend_since(session: AsyncSession, since: datetime) -> Decimal:
    """Every shop's OpenAI spend since ``since`` (naive UTC)."""
    if is_sqlite(session):
        runs = (
            await session.execute(
                select(func.coalesce(func.sum(WorkflowRun.cost_usd), 0)).where(
                    WorkflowRun.created_at >= since
                )
            )
        ).scalar_one()
        analyses = (
            await session.execute(
                select(func.coalesce(func.sum(ContentAnalysis.cost_usd), 0)).where(
                    ContentAnalysis.created_at >= since
                )
            )
        ).scalar_one()
        return Decimal(str(runs or 0)) + Decimal(str(analyses or 0))
    value = (
        await session.execute(text("SELECT public.openai_spend_since(:since)"), {"since": since})
    ).scalar_one()
    return Decimal(str(value or 0))


async def system_status(session: AsyncSession, *, now: datetime | None = None) -> SystemCapStatus:
    since = month_start_utc(now)
    return SystemCapStatus(
        month=month_label(now),
        month_start_utc=since,
        used_usd=await system_spend_since(session, since),
        cap=await system_cap(session),
    )


# -- the Ops banner read (P29) -------------------------------------------------------
#
# ``GET /v1/ops/costs/system`` sits behind the >= 80 % banner on EVERY Ops page.
# It was the spend, then each ``ops_system_settings`` row in its own SAVEPOINT:
# nine round trips (~3.5 s from the VPS) for three values. Now: one statement
# for all three, and the answer cached per process for BANNER_CACHE_TTL_SECONDS,
# keyed by the (UTC+7) month. The figure is system-wide -- no shop's data, the
# same for every staff member. The OpenAI GATES never read this cache
# (``system_cap_reached`` still reads the database every time).
#
# Invalidation: TTL; and :func:`forget_banner`, called by ``set_system_cap``
# (the Admin's "Sửa giới hạn") and again by its route after the COMMIT. The
# hourly alert task runs in a worker process; its "sent" marker reaches the
# banner within the TTL.

BANNER_CACHE_TTL_SECONDS = 30.0

_banner_cache: dict[str, tuple[float, SystemCapStatus, bool]] = {}
_banner_lock = threading.Lock()


def forget_banner() -> None:
    """Drop the cached banner figure (a cap change; tests)."""
    with _banner_lock:
        _banner_cache.clear()


def _setting_value(key: str) -> Any:
    return select(OpsSystemSetting.value).where(OpsSystemSetting.key == key).scalar_subquery()


def _cap_from(value: Any, updated_at: datetime | None, updated_by: str | None) -> SystemCap:
    """``system_cap``'s decision, from an already-read row (``value`` None = no row)."""
    if value is not None:
        try:
            return SystemCap(
                usd=validate_cap(value),
                is_default=False,
                updated_at=updated_at,
                updated_by=updated_by,
            )
        except SystemCapError:
            logger.warning("ops_system_cap_invalid", extra={"value": str(value)[:40]})
    return SystemCap(usd=default_cap_usd(), is_default=True)


async def _banner_from_database(
    session: AsyncSession, now: datetime | None
) -> tuple[SystemCapStatus, bool]:
    since = month_start_utc(now)
    month = month_label(now)
    if is_sqlite(session):
        status = await system_status(session, now=now)
        return status, await alert_sent_for(session, status.month)
    stmt = select(
        func.public.openai_spend_since(since),
        _setting_value(SYSTEM_CAP_KEY),
        select(OpsSystemSetting.updated_at)
        .where(OpsSystemSetting.key == SYSTEM_CAP_KEY)
        .scalar_subquery(),
        select(OpsSystemSetting.updated_by)
        .where(OpsSystemSetting.key == SYSTEM_CAP_KEY)
        .scalar_subquery(),
        _setting_value(ALERT_KEY),
    )
    try:
        spent, cap_value, updated_at, updated_by, alert = (await session.execute(stmt)).one()
    except SQLAlchemyError:
        # The old path tolerated an unreadable settings row (each read in its
        # own savepoint). Keep that: this is the request's only statement, so
        # roll back and take the slow, tolerant path once.
        logger.warning("ops_system_banner_fused_read_failed", exc_info=True)
        await session.rollback()
        status = await system_status(session, now=now)
        return status, await alert_sent_for(session, status.month)
    status = SystemCapStatus(
        month=month,
        month_start_utc=since,
        used_usd=Decimal(str(spent or 0)),
        cap=_cap_from(cap_value, updated_at, updated_by),
    )
    return status, isinstance(alert, dict) and alert.get("month") == month


async def system_banner(
    session: AsyncSession, *, now: datetime | None = None
) -> tuple[SystemCapStatus, bool]:
    """``(system_status, alert_sent_for(month))`` for the Ops banner: cached, else ONE read.

    Only for a caller with no other work in the transaction before it (a
    failed fused read rolls the transaction back).
    """
    month = month_label(now)
    with _banner_lock:
        hit = _banner_cache.get(month)
        if hit is not None and time.monotonic() - hit[0] <= BANNER_CACHE_TTL_SECONDS:
            return hit[1], hit[2]
    status, sent = await _banner_from_database(session, now)
    with _banner_lock:
        _banner_cache[month] = (time.monotonic(), status, sent)
    return status, sent


async def system_cap_reached(session: AsyncSession, *, now: datetime | None = None) -> bool:
    """The gate read: True when the month's system spend ≥ the system cap.

    A failed read never blocks (logged): the per-shop caps still hold.
    """
    try:
        async with session.begin_nested():
            status = await system_status(session, now=now)
    except SQLAlchemyError:
        logger.warning("ops_system_cap_read_failed", exc_info=True)
        return False
    if status.reached:
        logger.warning(
            "ops_openai_system_cap_reached",
            extra={"used_usd": float(status.used_usd), "cap_usd": float(status.cap.usd)},
        )
    return status.reached


async def _write(session: AsyncSession, key: str, value: Any, actor_email: str) -> None:
    """Upsert one setting as ``juli_ops`` (no commit)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with ops_role(session):
        row = await session.get(OpsSystemSetting, key)
        if row is None:
            row = OpsSystemSetting(key=key)
            session.add(row)
        row.value = value
        row.updated_at = now
        row.updated_by = actor_email


async def set_system_cap(session: AsyncSession, actor: audit.Actor, value: Any) -> SystemCap:
    """Admin "Sửa giới hạn": store the cap and write one audit row (no commit)."""
    cap = validate_cap(value)
    forget_banner()  # P29: the route forgets it again after its COMMIT
    before = await system_cap(session)
    stored: int | float = int(cap) if cap == cap.to_integral_value() else float(cap)
    await _write(session, SYSTEM_CAP_KEY, stored, actor.email)
    await audit.record(
        session,
        actor,
        ACTION_SYSTEM_CAP,
        before={SYSTEM_CAP_KEY: float(before.usd), "default": before.is_default},
        after={SYSTEM_CAP_KEY: float(cap)},
        field=SYSTEM_CAP_KEY,
    )
    logger.info("ops_system_cap_set", extra={"usd": float(cap)})
    return SystemCap(usd=cap, is_default=False, updated_by=actor.email)


# -- the 80 % e-mail ----------------------------------------------------------------


async def admin_emails(session: AsyncSession) -> list[str]:
    async with ops_role(session):
        rows = await session.execute(
            select(OpsStaff.email)
            .where(OpsStaff.role == ROLE_ADMIN, OpsStaff.active.is_(True))
            .order_by(OpsStaff.email)
        )
        return [str(e) for e in rows.scalars().all()]


def alert_body(status: SystemCapStatus) -> tuple[str, str]:
    pct = int(status.pct * 100)
    used = f"${float(status.used_usd):.2f}"
    cap = f"${float(status.cap.usd):.2f}"
    if status.reached:
        subject = f"Juli Ops: đã đạt giới hạn OpenAI tháng {status.month}"
        lead = (
            "Juli đã dừng soạn nội dung mới, phân tích nội dung và lượt chạy dùng OpenAI cho mọi "
            "shop đến đầu tháng sau hoặc khi Admin tăng giới hạn. Thẻ đề xuất vẫn được tạo."
        )
    else:
        subject = f"Juli Ops: đã dùng {pct} % giới hạn OpenAI tháng {status.month}"
        lead = "Khi đạt 100 %, Juli dừng mọi lệnh gọi OpenAI mới cho mọi shop."
    body = (
        f"Chào bạn,\n\nChi phí OpenAI của cả hệ thống tháng {status.month}: {used} / {cap} "
        f"({pct} %).\n{lead}\n\nXem và sửa giới hạn: Juli Ops → Chi phí.\n\n— Juli"
    )
    return subject, body


async def alert_sent_for(session: AsyncSession, month: str) -> bool:
    """Whether this month's alert e-mail went out (the banner says so)."""
    marker = await _setting(session, ALERT_KEY)
    value = marker.value if marker is not None else None
    return isinstance(value, dict) and value.get("month") == month


async def check_alert(
    session: AsyncSession, *, mailer: Any = None, now: datetime | None = None
) -> bool:
    """Send the month's ONE alert e-mail when spend ≥ 80 % (no commit). True if sent."""
    status = await system_status(session, now=now)
    if status.level is None:
        return False
    marker = await _setting(session, ALERT_KEY)
    sent = marker.value if marker is not None and isinstance(marker.value, dict) else {}
    if sent.get("month") == status.month:
        return False
    if mailer is None:
        from juli_backend.services.ops.mailer import get_mailer

        mailer = get_mailer()
    recipients = await admin_emails(session)
    if not getattr(mailer, "configured", True) or not recipients:
        logger.warning(
            "openai_system_alert_unsent",
            extra={
                "month": status.month,
                "level": status.level,
                "reason": "no_recipients" if not recipients else "smtp_not_configured",
            },
        )
        return False
    subject, body = alert_body(status)
    delivered = 0
    for to in recipients:
        if await mailer.send_notice(to=to, subject=subject, body=body):
            delivered += 1
    if delivered == 0:
        logger.warning(
            "openai_system_alert_unsent",
            extra={"month": status.month, "level": status.level, "reason": "send_failed"},
        )
        return False
    await _write(
        session, ALERT_KEY, {"month": status.month, "level": status.level}, audit.SYSTEM_ACTOR.email
    )
    await audit.record(
        session,
        audit.SYSTEM_ACTOR,
        "system_openai_alert_sent",
        after={"month": status.month, "level": status.level, "recipients": delivered},
    )
    logger.info(
        "openai_system_alert_sent",
        extra={"month": status.month, "level": status.level, "recipients": delivered},
    )
    return True
