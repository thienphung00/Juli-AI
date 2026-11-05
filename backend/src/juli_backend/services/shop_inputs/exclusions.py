"""P92 B-1: listings the shop leaves out (Cài đặt › Loại trừ sản phẩm).

An excluded listing gets no recommendation card, no product row, no builder entry and no Phân
tích flag; its sales stay in every shop total (see ``shopee_analytics`` ``excluded_summary``).
Stored as the shop rules ``excluded`` (bool) and ``exclude_reason`` (``ngung_ban`` | ``qua_tang`` |
``phan_phoi`` | ``khac``), both scoped to the item id, through the versioned write path of the
other Thông số shop inputs (``shop_rule_versions``: who, when, why), so an add or an undo is an
old -> new entry in the same history as the ``.xlsx`` import. An undo writes ``excluded = false``;
nothing is deleted. Flush, never commit (the route commits together with its audit row).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import ShopRuleVersion
from juli_backend.services.shop_inputs.affected import STALE_REASON, StaleRequest, mark_stale
from juli_backend.services.shop_inputs.catalogue import PLATFORM, load_current
from juli_backend.services.shop_inputs.versions import (
    Actor,
    RuleChange,
    VersionError,
    clean_reason,
    write_versions,
)
from juli_backend.services.shop_rules.rules import (
    EXCLUDE_REASON,
    EXCLUDE_REASONS,
    EXCLUDED,
)

REASON_LABELS: dict[str, str] = {
    "ngung_ban": "Ngừng bán",
    "qua_tang": "Quà tặng",
    "phan_phoi": "Hàng phân phối",
    "khac": "Khác",
}
DEFAULT_ADD_NOTE = "Loại trừ sản phẩm"
DEFAULT_UNDO_NOTE = "Bỏ loại trừ sản phẩm"


class ExclusionError(VersionError):
    """The change is refused; ``code`` is for the route, the message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Exclusion:
    item_id: str
    reason: str
    reason_label: str
    name: str | None
    set_by: str | None
    set_by_user_id: uuid.UUID | None
    set_at: datetime | None
    note: str | None

    def json(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "reason": self.reason,
            "reason_label": self.reason_label,
            "set_by": self.set_by,
            "set_at": None if self.set_at is None else self.set_at.isoformat(),
            "note": self.note,
        }


async def _names(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, str]:
    from juli_backend.models.platform_data import PlatformItem

    rows = (
        await session.execute(
            select(PlatformItem.item_id, PlatformItem.name).where(
                PlatformItem.shop_id == shop_id,
                PlatformItem.platform == PLATFORM,
                PlatformItem.variation_id == "",
            )
        )
    ).all()
    return {item: name for item, name in rows if name}


async def list_exclusions(session: AsyncSession, shop_id: uuid.UUID) -> list[Exclusion]:
    """The listings currently excluded, by item id, with who set the newest version."""
    current = await load_current(session, shop_id)
    flagged = sorted(i for i, v in current.per_sku.items() if v.get(EXCLUDED) is True)
    if not flagged:
        return []
    names = await _names(session, shop_id)
    versions = (
        (
            await session.execute(
                select(ShopRuleVersion)
                .where(
                    ShopRuleVersion.shop_id == shop_id,
                    ShopRuleVersion.rule_key == EXCLUDED,
                    ShopRuleVersion.scope_ref.in_(flagged),
                )
                .order_by(ShopRuleVersion.version)
            )
        )
        .scalars()
        .all()
    )
    newest = {v.scope_ref: v for v in versions}
    out = []
    for item in flagged:
        reason = current.per_sku[item].get(EXCLUDE_REASON)
        reason = reason if reason in REASON_LABELS else "khac"
        v = newest.get(item)
        out.append(
            Exclusion(
                item_id=item,
                reason=reason,
                reason_label=REASON_LABELS[reason],
                name=names.get(item),
                set_by=v.set_by if v else None,
                set_by_user_id=v.set_by_user_id if v else None,
                set_at=v.valid_from if v else None,
                note=v.reason if v else None,
            )
        )
    return out


async def _write(
    session: AsyncSession,
    shop_id: uuid.UUID,
    changes: list[RuleChange],
    *,
    actor: Actor,
    note: str,
    item_id: str,
    now: datetime | None,
) -> None:
    moment = now or datetime.now(UTC)
    await write_versions(session, shop_id, changes, actor=actor, reason=note, now=moment)
    # open cards of this listing are stale now (the engine re-runs them without it)
    await mark_stale(
        session,
        shop_id,
        StaleRequest(item_ids=(item_id,), shop_wide=False, reason=STALE_REASON, changed_at=moment),
    )


async def add_exclusion(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    reason: str,
    *,
    actor: Actor,
    note: str | None = None,
    now: datetime | None = None,
) -> Exclusion:
    """Exclude one listing (idempotent: the same reason again writes nothing)."""
    item = item_id.strip()
    if not item or ":" in item or len(item) > 64:
        raise ExclusionError("exclusion_item_invalid", "Mã sản phẩm không hợp lệ.")
    if reason not in EXCLUDE_REASONS:
        raise ExclusionError(
            "exclusion_reason_invalid",
            "Lý do là Ngừng bán, Quà tặng, Hàng phân phối hoặc Khác.",
        )
    why = clean_reason(note, required=False) or DEFAULT_ADD_NOTE
    await _write(
        session,
        shop_id,
        [RuleChange(EXCLUDED, item, True), RuleChange(EXCLUDE_REASON, item, reason)],
        actor=actor,
        note=why,
        item_id=item,
        now=now,
    )
    found = [e for e in await list_exclusions(session, shop_id) if e.item_id == item]
    return found[0]


async def undo_exclusion(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    actor: Actor,
    note: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Put one listing back. ``False`` when it was not excluded."""
    item = item_id.strip()
    if item not in {e.item_id for e in await list_exclusions(session, shop_id)}:
        return False
    why = clean_reason(note, required=False) or DEFAULT_UNDO_NOTE
    await _write(
        session,
        shop_id,
        [RuleChange(EXCLUDED, item, False)],
        actor=actor,
        note=why,
        item_id=item,
        now=now,
    )
    return True


__all__ = [
    "REASON_LABELS",
    "Exclusion",
    "ExclusionError",
    "add_exclusion",
    "list_exclusions",
    "undo_exclusion",
]
