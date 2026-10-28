"""The ops audit log (D25.2): who, which shop, what, before/after, when.

D27 (2026-10-11):

- **Kinds** (D27.4), derived from the action -- no stored column, so rows
  written before P18 classify the same way: ``view`` ("Xem như shop" sessions
  and staff data refreshes), ``system`` (jobs; actions prefixed ``system_``),
  ``config`` (every other change). Retention: config 365 days, view / system
  90 days (:func:`purge_expired`, the nightly ``ops_audit_retention`` task).
- **Merging** (D27.6): a config change that names ONE ``field`` merges into the
  same actor's previous row for the same shop, action and field written within
  :data:`MERGE_WINDOW` -- that row keeps its ``before``, takes the new
  ``after``, ``merged_count += 1`` and its ``at`` moves to now. When the merged
  ``after`` equals the original ``before`` the change was undone: the row is
  deleted and nothing stays logged. A change of several fields at once (one
  settings save) is one row with ``field = None`` and never merges.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ops import OpsAuditLog
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops.access import ops_role

KIND_CONFIG = "config"
KIND_VIEW = "view"
KIND_SYSTEM = "system"
KINDS: tuple[str, ...] = (KIND_CONFIG, KIND_VIEW, KIND_SYSTEM)
#: Staff pressed "Làm mới" (D27.1): numbers recomputed, nothing configured.
ACTION_DATA_REFRESH = "data_refresh"
#: P32-A (D42): a partner reviewer's session -- sign-in, the simulated Duyệt /
#: Thực thi, and every refused request. Actor ``reviewer:<platform>:<email>``.
ACTION_REVIEWER_SIGN_IN = "reviewer_sign_in"
ACTION_REVIEWER_SIMULATED_APPROVE = "reviewer_simulated_approve"
ACTION_REVIEWER_SIMULATED_EXECUTE = "reviewer_simulated_execute"
ACTION_REVIEWER_WRITE_REFUSED = "reviewer_write_refused"
ACTION_REVIEWER_READ_REFUSED = "reviewer_read_refused"
REVIEWER_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_REVIEWER_SIGN_IN,
        ACTION_REVIEWER_SIMULATED_APPROVE,
        ACTION_REVIEWER_SIMULATED_EXECUTE,
        ACTION_REVIEWER_WRITE_REFUSED,
        ACTION_REVIEWER_READ_REFUSED,
    }
)
#: P64 (D73): the reviewer's REAL actions on Juli's own sandbox shop. Config kind
#: (365-day retention), not view: each one changed something at TikTok or queued work.
ACTION_REVIEWER_SANDBOX_APPROVE = "reviewer_sandbox_approve"
ACTION_REVIEWER_SANDBOX_EXECUTE = "reviewer_sandbox_execute"
ACTION_REVIEWER_SANDBOX_SYNC = "reviewer_sandbox_sync"
#: D73.3/D73.4: the reviewer confirmed the sandbox ``create_product`` run's write.
ACTION_REVIEWER_SANDBOX_CREATE_PRODUCT = "reviewer_sandbox_create_product"
#: P65 (D74): the reviewer confirmed the sandbox ``create_promotion`` run's write.
ACTION_REVIEWER_SANDBOX_CREATE_PROMOTION = "reviewer_sandbox_create_promotion"
#: P70 (owner, 2026-10-28): the reviewer started a "Hoàn tác" run on the sandbox shop.
ACTION_REVIEWER_SANDBOX_REVERT = "reviewer_sandbox_revert"
REVIEWER_SANDBOX_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_REVIEWER_SANDBOX_REVERT,
        ACTION_REVIEWER_SANDBOX_APPROVE,
        ACTION_REVIEWER_SANDBOX_EXECUTE,
        ACTION_REVIEWER_SANDBOX_SYNC,
        ACTION_REVIEWER_SANDBOX_CREATE_PRODUCT,
        ACTION_REVIEWER_SANDBOX_CREATE_PROMOTION,
    }
)
#: The provisioning command (config kind: an account was created / changed).
ACTION_REVIEWER_ACCOUNT_CREATE = "reviewer_account_create"
ACTION_REVIEWER_ACCOUNT_RENEW = "reviewer_account_renew"
ACTION_REVIEWER_ACCOUNT_REVOKE = "reviewer_account_revoke"
#: Actions that only look at data (no configuration changed).
VIEW_ACTIONS: frozenset[str] = frozenset(
    {"view_as_view", "view_as_exit", ACTION_DATA_REFRESH} | REVIEWER_ACTIONS
)
SYSTEM_PREFIX = "system_"
#: D27.4: how long each kind is kept.
RETENTION_DAYS: dict[str, int] = {KIND_CONFIG: 365, KIND_VIEW: 90, KIND_SYSTEM: 90}
#: D27.6: same actor + shop + action + field within this window → one row.
MERGE_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True)
class Actor:
    """Who did it: a staff row, or the system (``staff_id=None``)."""

    staff_id: uuid.UUID | None
    email: str


SYSTEM_ACTOR = Actor(staff_id=None, email="system")


def kind_of(action: str) -> str:
    if action in VIEW_ACTIONS:
        return KIND_VIEW
    if action.startswith(SYSTEM_PREFIX):
        return KIND_SYSTEM
    return KIND_CONFIG


def kind_clause(kind: str) -> ColumnElement[bool]:
    """SQL twin of :func:`kind_of`."""
    action = OpsAuditLog.action
    is_view = action.in_(sorted(VIEW_ACTIONS))
    is_system = action.startswith(SYSTEM_PREFIX, autoescape=True)
    if kind == KIND_VIEW:
        return is_view
    if kind == KIND_SYSTEM:
        return and_(is_system, not_(is_view))
    if kind == KIND_CONFIG:
        return and_(not_(is_view), not_(is_system))
    raise ValueError(f"unknown audit kind {kind!r}")


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


async def _mergeable(
    session: AsyncSession,
    actor: Actor,
    action: str,
    shop_id: uuid.UUID | None,
    field: str,
    moment: datetime,
) -> OpsAuditLog | None:
    stmt = (
        select(OpsAuditLog)
        .where(
            OpsAuditLog.actor_staff_id == actor.staff_id,
            OpsAuditLog.action == action,
            OpsAuditLog.field == field,
            OpsAuditLog.at >= moment - MERGE_WINDOW,
            OpsAuditLog.shop_id.is_(None) if shop_id is None else OpsAuditLog.shop_id == shop_id,
        )
        .order_by(OpsAuditLog.at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def record(
    session: AsyncSession,
    actor: Actor,
    action: str,
    *,
    shop_id: uuid.UUID | None = None,
    before: Any = None,
    after: Any = None,
    at: datetime | None = None,
    field: str | None = None,
) -> OpsAuditLog | None:
    """Write one audit row, or merge into the previous one (no commit).

    Returns the row written or merged into; ``None`` when a merge undid the
    previous change and its row was deleted (D27.6).
    """
    moment = at or utc_now_naive()
    clean_before = _jsonable(before)
    clean_after = _jsonable(after)
    async with ops_role(session):
        if field is not None and actor.staff_id is not None and kind_of(action) == KIND_CONFIG:
            previous = await _mergeable(session, actor, action, shop_id, field, moment)
            if previous is not None:
                if clean_after == previous.before:
                    await session.delete(previous)
                    return None
                previous.after = clean_after
                previous.merged_count = (previous.merged_count or 1) + 1
                previous.at = moment
                return previous
        row = OpsAuditLog(
            id=uuid.uuid4(),
            actor_staff_id=actor.staff_id,
            actor_email=actor.email,
            shop_id=shop_id,
            action=action,
            field=field,
            before=clean_before,
            after=clean_after,
            at=moment,
            merged_count=1,
        )
        session.add(row)
    return row


async def list_entries(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> list[OpsAuditLog]:
    stmt = select(OpsAuditLog).order_by(OpsAuditLog.at.desc(), OpsAuditLog.id).limit(limit)
    if shop_id is not None:
        stmt = stmt.where(OpsAuditLog.shop_id == shop_id)
    if kind is not None:
        stmt = stmt.where(kind_clause(kind))
    async with ops_role(session):
        return list((await session.execute(stmt)).scalars().all())


async def purge_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """D27.4: delete config rows older than 365 days, view / system older than 90 (no commit)."""
    current = now or utc_now_naive()
    expired = or_(
        *(
            and_(kind_clause(kind), OpsAuditLog.at < current - timedelta(days=days))
            for kind, days in RETENTION_DAYS.items()
        )
    )
    async with ops_role(session):
        result = await session.execute(delete(OpsAuditLog).where(expired))
    return int(getattr(result, "rowcount", 0) or 0)
