"""Versioned writes of the seller's rules (P90 step 4, ADR-120 d.12).

Every change appends one ``shop_rule_versions`` row (who -- ``team`` | ``seller`` and the
user id --, why, the import file's SHA-256, ``valid_from``) AND updates the
``shop_rules`` projection, in the caller's transaction: this module flushes and never
commits, so a failure anywhere rolls the history and the projection back together.
History is append-only (the table grants SELECT and INSERT); restoring appends a NEW
version that copies the old value.

Version numbers count per ``(rule_key, scope_ref)``. For the screen, the versions of one
SKU that were written together (same ``valid_from``, file, reason and author -- one
import apply or one restore) are shown as one change set ``v1``, ``v2`` ... per SKU.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import SET_BY_VALUES, ShopRule, ShopRuleVersion
from juli_backend.services.shop_rules.rules import (
    SKU_INPUT_RULE_KEYS,
    RuleValidationError,
    set_rule,
    validate_rule,
)

MAX_REASON_LENGTH = 500


class VersionError(ValueError):
    """A versioned write the store refuses; the message is safe to show the caller."""


class VersionNotFound(VersionError):
    """The version (or change set) asked for does not exist for this shop."""


@dataclass(frozen=True)
class Actor:
    """Who writes: ``team`` (Juli staff, on the seller's behalf) or ``seller``."""

    set_by: str
    user_id: uuid.UUID | None

    def __post_init__(self) -> None:
        if self.set_by not in SET_BY_VALUES:
            raise VersionError(f"set_by must be one of {list(SET_BY_VALUES)}")


@dataclass(frozen=True)
class RuleChange:
    rule_key: str
    scope_ref: str
    value: Any


def _naive_utc(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)


def clean_reason(reason: str | None, *, required: bool) -> str | None:
    text = (reason or "").strip()
    if required and not text:
        raise VersionError("Cần ghi lý do cho thay đổi này")
    if len(text) > MAX_REASON_LENGTH:
        raise VersionError(f"Lý do tối đa {MAX_REASON_LENGTH} ký tự")
    return text or None


async def _current_row(
    session: AsyncSession, shop_id: uuid.UUID, rule_key: str, scope_ref: str
) -> ShopRule | None:
    return (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key == rule_key,
                ShopRule.scope_ref == scope_ref,
            )
        )
    ).scalar_one_or_none()


async def _next_version(
    session: AsyncSession, shop_id: uuid.UUID, rule_key: str, scope_ref: str
) -> int:
    latest = (
        await session.execute(
            select(func.max(ShopRuleVersion.version)).where(
                ShopRuleVersion.shop_id == shop_id,
                ShopRuleVersion.rule_key == rule_key,
                ShopRuleVersion.scope_ref == scope_ref,
            )
        )
    ).scalar_one()
    return (latest or 0) + 1


async def write_version(
    session: AsyncSession,
    shop_id: uuid.UUID,
    change: RuleChange,
    *,
    actor: Actor,
    reason: str | None = None,
    import_file_hash: str | None = None,
    now: datetime | None = None,
    skip_unchanged: bool = True,
) -> ShopRuleVersion | None:
    """Append one version and update the projection. ``None`` when the value is unchanged.

    The value is validated (and normalised) by the rule store first, so history never
    holds a value the projection would refuse.
    """
    scope_ref, value = validate_rule(change.rule_key, change.scope_ref, change.value)
    current = await _current_row(session, shop_id, change.rule_key, scope_ref)
    if skip_unchanged and current is not None and current.value == value:
        return None
    moment = _naive_utc(now)
    version = ShopRuleVersion(
        id=uuid.uuid4(),
        shop_id=shop_id,
        rule_key=change.rule_key,
        scope_ref=scope_ref,
        value=value,
        version=await _next_version(session, shop_id, change.rule_key, scope_ref),
        set_by=actor.set_by,
        set_by_user_id=actor.user_id,
        reason=clean_reason(reason, required=False),
        import_file_hash=import_file_hash,
        valid_from=moment,
    )
    session.add(version)
    await set_rule(
        session,
        shop_id,
        rule_key=change.rule_key,
        scope_ref=scope_ref,
        value=value,
        set_by=actor.set_by,
        set_by_user_id=actor.user_id,
        now=moment.replace(tzinfo=UTC),
    )
    await session.flush()
    return version


async def write_rule(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    rule_key: str,
    scope_ref: str | None,
    value: Any,
    actor: Actor,
    reason: str | None = None,
) -> ShopRule:
    """``set_rule`` that also appends the version: the rule editors' write path.

    A value equal to the current one appends nothing. Returns the projection row.
    """
    scope = (scope_ref or "").strip()
    version = await write_version(
        session, shop_id, RuleChange(rule_key, scope, value), actor=actor, reason=reason
    )
    if version is None:  # same value: no new version, but who / when still refresh
        return await set_rule(
            session,
            shop_id,
            rule_key=rule_key,
            scope_ref=scope,
            value=value,
            set_by=actor.set_by,
            set_by_user_id=actor.user_id,
        )
    row = await _current_row(session, shop_id, rule_key, scope)
    assert row is not None
    return row


async def write_versions(
    session: AsyncSession,
    shop_id: uuid.UUID,
    changes: Sequence[RuleChange],
    *,
    actor: Actor,
    reason: str,
    import_file_hash: str | None = None,
    now: datetime | None = None,
) -> list[ShopRuleVersion]:
    """A change set: every changed value gets a version with the same ``valid_from``.

    The reason is required here (an import or a restore always says why).
    """
    why = clean_reason(reason, required=True)
    moment = now or datetime.now(UTC)
    written: list[ShopRuleVersion] = []
    for change in changes:
        row = await write_version(
            session,
            shop_id,
            change,
            actor=actor,
            reason=why,
            import_file_hash=import_file_hash,
            now=moment,
        )
        if row is not None:
            written.append(row)
    return written


@dataclass(frozen=True)
class VersionEntry:
    rule_key: str
    scope_ref: str
    version: int
    value: Any
    set_by: str
    set_by_user_id: uuid.UUID | None
    reason: str | None
    import_file_hash: str | None
    valid_from: datetime
    current: bool


async def list_versions(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    rule_key: str | None = None,
    scope_ref: str | None = None,
) -> list[VersionEntry]:
    """Versions of one key / scope (or all of a key), newest first."""
    stmt = select(ShopRuleVersion).where(ShopRuleVersion.shop_id == shop_id)
    if rule_key is not None:
        stmt = stmt.where(ShopRuleVersion.rule_key == rule_key)
    if scope_ref is not None:
        stmt = stmt.where(ShopRuleVersion.scope_ref == scope_ref)
    rows = (
        (
            await session.execute(
                stmt.order_by(
                    ShopRuleVersion.rule_key,
                    ShopRuleVersion.scope_ref,
                    ShopRuleVersion.version.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    newest: dict[tuple[str, str], int] = {}
    for row in rows:
        newest.setdefault((row.rule_key, row.scope_ref), row.version)
    return [
        VersionEntry(
            rule_key=r.rule_key,
            scope_ref=r.scope_ref,
            version=r.version,
            value=r.value,
            set_by=r.set_by,
            set_by_user_id=r.set_by_user_id,
            reason=r.reason,
            import_file_hash=r.import_file_hash,
            valid_from=r.valid_from,
            current=newest[(r.rule_key, r.scope_ref)] == r.version,
        )
        for r in rows
    ]


async def restore_version(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    rule_key: str,
    scope_ref: str,
    version: int,
    actor: Actor,
    reason: str | None = None,
    now: datetime | None = None,
) -> ShopRuleVersion:
    """Append a new version copying ``version``'s value; nothing is deleted or rewritten."""
    old = (
        await session.execute(
            select(ShopRuleVersion).where(
                ShopRuleVersion.shop_id == shop_id,
                ShopRuleVersion.rule_key == rule_key,
                ShopRuleVersion.scope_ref == scope_ref,
                ShopRuleVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if old is None:
        raise VersionNotFound("Không có phiên bản này")
    why = clean_reason(reason, required=False) or f"Khôi phục từ v{version}"
    try:
        row = await write_version(
            session,
            shop_id,
            RuleChange(rule_key, scope_ref, old.value),
            actor=actor,
            reason=why,
            now=now,
            skip_unchanged=True,
        )
    except RuleValidationError as exc:
        raise VersionError(str(exc)) from None
    if row is None:
        raise VersionError("Phiên bản này đang là giá trị hiện hành")
    return row


# -- per-SKU change sets ------------------------------------------------------------------


@dataclass
class ChangeSet:
    """The versions of one SKU written together; ``state`` is the SKU after this set."""

    id: str
    number: int
    valid_from: datetime
    set_by: str
    set_by_user_id: uuid.UUID | None
    reason: str | None
    import_file_hash: str | None
    changes: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    current: bool = False


async def sku_history(session: AsyncSession, shop_id: uuid.UUID, scope_ref: str) -> list[ChangeSet]:
    """One SKU's change sets, oldest first (``v1``...); the last one is ``current``."""
    rows = (
        (
            await session.execute(
                select(ShopRuleVersion)
                .where(
                    ShopRuleVersion.shop_id == shop_id,
                    ShopRuleVersion.scope_ref == scope_ref,
                    ShopRuleVersion.rule_key.in_(SKU_INPUT_RULE_KEYS),
                )
                .order_by(
                    ShopRuleVersion.valid_from, ShopRuleVersion.rule_key, ShopRuleVersion.version
                )
            )
        )
        .scalars()
        .all()
    )
    sets: list[ChangeSet] = []
    index: dict[tuple[Any, ...], ChangeSet] = {}
    state: dict[str, Any] = {}
    for row in rows:
        key = (row.valid_from, row.import_file_hash, row.reason, row.set_by, row.set_by_user_id)
        change_set = index.get(key)
        if change_set is None:
            change_set = ChangeSet(
                id=f"v{len(sets) + 1}",
                number=len(sets) + 1,
                valid_from=row.valid_from,
                set_by=row.set_by,
                set_by_user_id=row.set_by_user_id,
                reason=row.reason,
                import_file_hash=row.import_file_hash,
            )
            index[key] = change_set
            sets.append(change_set)
        change_set.changes[row.rule_key] = row.value
        state[row.rule_key] = row.value
        change_set.state = dict(state)
    # later rows of an earlier set cannot exist (ordered by valid_from), but a set's state
    # must be the state after the whole set: recompute cumulatively.
    running: dict[str, Any] = {}
    for change_set in sets:
        running.update(change_set.changes)
        change_set.state = dict(running)
    if sets:
        sets[-1].current = True
    return sets


async def restore_sku_version(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    scope_ref: str,
    number: int,
    actor: Actor,
    now: datetime | None = None,
) -> list[ShopRuleVersion]:
    """New versions that put the SKU's fields back to how they were after change set
    ``number``. Fields that set did not yet hold keep their value (history cannot hold
    "unset"). One reason, one ``valid_from``: it shows as one new change set."""
    sets = await sku_history(session, shop_id, scope_ref)
    target = next((s for s in sets if s.number == number), None)
    if target is None:
        raise VersionNotFound("Không có phiên bản này")
    if target.current:
        raise VersionError("Phiên bản này đang là giá trị hiện hành")
    written = await write_versions(
        session,
        shop_id,
        [RuleChange(key, scope_ref, value) for key, value in target.state.items()],
        actor=actor,
        reason=f"Khôi phục từ v{number}",
        now=now,
    )
    if not written:
        raise VersionError("Phiên bản này đang là giá trị hiện hành")
    return written
