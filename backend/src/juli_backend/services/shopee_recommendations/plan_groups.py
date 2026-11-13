"""Groups of a plan (P97 D85.14, the P94 contract): options that run together.

- A **group** ("Nhóm A", "Nhóm B" ...) holds versions of one or several planned cards -- mixed
  kinds are fine -- with ONE period: a start (default: right after the previous group ends, the
  first group from the plan's date) and ``days`` (at least 3). Groups run one after another.
- Inside a group the options are evaluated as one bundle on the same orders by the plan math
  (:func:`plan_aggregate.aggregate`): order independent, one joint lift per product, each buyer gets
  the best voucher / combo tier their basket qualifies for. A group is measured on its own.
- **One live value per exclusive field** (giá bán, tên, ảnh bìa, mô tả, ngân sách, ROAS of the same
  product / campaign): a second option on a field that is already taken in a group moves to the next
  group instead of being refused.
- A card with no membership behaves as before (the plan's own aggregate). A removed member keeps
  its row; an empty group is cancelled (its letter is free again).
- Codes: the group is ``<code of its first card>-G<letter>`` (``JC-2611-0007-GA``), each version
  ``-V<n>``; the export lists group, versions and period.

Data operations only; the orchestration (adding the cards to the plan, the approval, the fill queue)
is in :mod:`.plans`.
"""

from __future__ import annotations

import string
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_plans import (
    GROUP_APPROVED,
    GROUP_CANCELLED,
    GROUP_DRAFT,
    GROUP_MAX_DAYS,
    GROUP_MIN_DAYS,
    ShopRecoPlan,
    ShopRecoPlanCard,
    ShopRecoPlanGroup,
    ShopRecoPlanGroupMember,
)
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import codes, store, versions
from juli_backend.services.shopee_recommendations.plan_aggregate import Entry

LETTERS = string.ascii_uppercase
DEFAULT_DAYS = 7
ERROR_GROUP = "reco_group_not_found"
ERROR_GROUP_DAYS = "reco_group_days"
ERROR_GROUP_EMPTY = "reco_group_empty"
ERROR_GROUP_DATE = "reco_group_date"

#: field key -> (Vietnamese name, change kinds that write it); one live value at a time (P94)
EXCLUSIVE_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "price": ("giá bán", ("price", "product_discount", "flash_sale", "program_registration")),
    "title": ("tên sản phẩm", ("title",)),
    "cover": ("ảnh bìa", ("cover_image",)),
    "description": ("dòng đầu mô tả", ("description_first_line",)),
    "ads_budget": ("ngân sách quảng cáo", ("ads_budget",)),
    "ads_roas": ("mục tiêu ROAS", ("ads_roas_target",)),
}


def exclusive_keys(payload: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """``(field, subject, Vietnamese field name)`` for every exclusive field the card writes: one
    per product / campaign it names (a many-target card names all of its targets)."""
    kind = str(payload.get("change_kind") or "")
    scope = payload.get("scope") or {}
    for key, (label, kinds) in EXCLUSIVE_FIELDS.items():
        if kind not in kinds:
            continue
        subjects = [str(t["id"]) for t in payload.get("targets") or [] if t.get("id")]
        if not subjects:
            subjects = [str(i) for i in scope.get("product_ids") or []]
        if not subjects and scope.get("campaign_key"):
            subjects = [str(scope["campaign_key"])]
        return [(key, s, label) for s in (subjects or [""])]
    return []


def _naive(now: datetime) -> datetime:
    return now.replace(tzinfo=None) if now.tzinfo else now


@dataclass
class Placement:
    """One version of a planned card to put in a group."""

    row: ShopRecoPlanCard
    proposal: ShopProposal
    payload: dict[str, Any]
    version: int


@dataclass
class Placed:
    placement: Placement
    group: ShopRecoPlanGroup
    #: moved to a later group than asked because an exclusive field was already taken
    moved_because: str | None = None


# ------------------------------------------------------------------------------ storage


async def active_groups(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID
) -> list[ShopRecoPlanGroup]:
    rows = await session.scalars(
        select(ShopRecoPlanGroup)
        .where(
            ShopRecoPlanGroup.shop_id == shop_id,
            ShopRecoPlanGroup.plan_id == plan_id,
            ShopRecoPlanGroup.status != GROUP_CANCELLED,
        )
        .order_by(ShopRecoPlanGroup.position, ShopRecoPlanGroup.letter)
    )
    return list(rows)


async def get_group(
    session: AsyncSession, shop_id: uuid.UUID, group_id: uuid.UUID
) -> ShopRecoPlanGroup:
    row = await session.scalar(
        select(ShopRecoPlanGroup).where(
            ShopRecoPlanGroup.id == group_id,
            ShopRecoPlanGroup.shop_id == shop_id,
            ShopRecoPlanGroup.status != GROUP_CANCELLED,
        )
    )
    if row is None:
        raise ProposalError(ERROR_GROUP, 404, "the group is not in the plan")
    return row


async def members_by_group(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID
) -> dict[uuid.UUID, list[tuple[ShopRecoPlanGroupMember, ShopRecoPlanCard, ShopProposal]]]:
    """Active members of every active group of the plan, in the order they were added."""
    stmt = (
        select(ShopRecoPlanGroupMember, ShopRecoPlanCard, ShopProposal)
        .join(ShopRecoPlanGroup, ShopRecoPlanGroup.id == ShopRecoPlanGroupMember.group_id)
        .join(ShopRecoPlanCard, ShopRecoPlanCard.id == ShopRecoPlanGroupMember.plan_card_id)
        .join(ShopProposal, ShopProposal.id == ShopRecoPlanCard.proposal_id)
        .where(
            ShopRecoPlanGroupMember.shop_id == shop_id,
            ShopRecoPlanGroup.plan_id == plan_id,
            ShopRecoPlanGroup.status != GROUP_CANCELLED,
            ShopRecoPlanGroupMember.removed_at.is_(None),
            ShopRecoPlanCard.removed_at.is_(None),
        )
        .order_by(ShopRecoPlanGroupMember.position, ShopRecoPlanGroupMember.added_at)
    )
    out: dict[uuid.UUID, list[tuple[ShopRecoPlanGroupMember, ShopRecoPlanCard, ShopProposal]]] = {}
    for m, c, p in (await session.execute(stmt)).all():
        out.setdefault(m.group_id, []).append((m, c, p))
    return out


def grouped_card_ids(
    by_group: Mapping[uuid.UUID, Sequence[tuple[ShopRecoPlanGroupMember, Any, Any]]],
) -> set[uuid.UUID]:
    return {m.plan_card_id for rows in by_group.values() for m, _, _ in rows}


# ------------------------------------------------------------------------------ periods


def periods(
    plan: ShopRecoPlan, groups: Sequence[ShopRecoPlanGroup], *, today: date
) -> dict[uuid.UUID, tuple[date, date]]:
    """``group id -> (first day, last day)``: a group starts on its own date, else the day after the
    previous group ends (the first one: the plan's date, else today); it lasts ``days`` days."""
    out: dict[uuid.UUID, tuple[date, date]] = {}
    cursor = plan.planned_date or today
    for g in groups:
        start = g.start_date or cursor
        end = start + timedelta(days=int(g.days) - 1)
        out[g.id] = (start, end)
        cursor = end + timedelta(days=1)
    return out


def check_days(days: int) -> int:
    if not GROUP_MIN_DAYS <= days <= GROUP_MAX_DAYS:
        raise ProposalError(
            ERROR_GROUP_DAYS,
            422,
            f"Nhóm chạy từ {GROUP_MIN_DAYS} đến {GROUP_MAX_DAYS} ngày "
            f"(ít nhất {GROUP_MIN_DAYS} ngày).",
        )
    return days


# ------------------------------------------------------------------------------ placing


def _next_letter(groups: Sequence[ShopRecoPlanGroup]) -> str:
    used = {g.letter for g in groups}
    last = max((LETTERS.index(x) for x in used if x in LETTERS), default=-1)
    for letter in LETTERS[last + 1 :] + LETTERS[: last + 1]:
        if letter not in used:
            return letter
    raise ProposalError("reco_group_full", 409, "Một kế hoạch có tối đa 26 nhóm.")


async def new_group(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan: ShopRecoPlan,
    groups: list[ShopRecoPlanGroup],
    *,
    actor: Mapping[str, Any],
    now: datetime,
    days: int = DEFAULT_DAYS,
    start: date | None = None,
) -> ShopRecoPlanGroup:
    g = ShopRecoPlanGroup(
        id=uuid.uuid4(),
        shop_id=shop_id,
        plan_id=plan.id,
        letter=_next_letter(groups),
        position=max((x.position for x in groups), default=0) + 1,
        start_date=start,
        days=check_days(days),
        status=GROUP_DRAFT,
        created_by=dict(actor),
        created_at=now,
        updated_at=now,
    )
    session.add(g)
    await session.flush()
    groups.append(g)
    return g


async def _keys_of_group(
    session: AsyncSession,
    shop_id: uuid.UUID,
    group: ShopRecoPlanGroup,
    cache: dict[uuid.UUID, set[tuple[str, str]]],
    payloads: dict[uuid.UUID, dict[str, Any]],
) -> set[tuple[str, str]]:
    if group.id in cache:
        return cache[group.id]
    held: set[tuple[str, str]] = set()
    rows = (
        await session.execute(
            select(ShopRecoPlanGroupMember, ShopRecoPlanCard)
            .join(ShopRecoPlanCard, ShopRecoPlanCard.id == ShopRecoPlanGroupMember.plan_card_id)
            .where(
                ShopRecoPlanGroupMember.group_id == group.id,
                ShopRecoPlanGroupMember.removed_at.is_(None),
            )
        )
    ).all()
    for _, card_row in rows:
        pid = card_row.proposal_id
        if pid not in payloads:
            payloads[pid] = await store.card_payload(session, shop_id, pid) or {}
        held |= {(f, s) for f, s, _ in exclusive_keys(payloads[pid])}
    cache[group.id] = held
    return held


async def place(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan: ShopRecoPlan,
    items: Sequence[Placement],
    *,
    actor: Mapping[str, Any],
    now: datetime,
    first: ShopRecoPlanGroup | None = None,
    days: int = DEFAULT_DAYS,
    start: date | None = None,
    after_index: int | None = None,
) -> list[Placed]:
    """Put each version in a group. All go to ``first`` (or one new group made with ``days`` /
    ``start``); a version whose exclusive field is already taken there moves to the next group,
    made on the way (the default period, right after the previous group)."""
    now = _naive(now)
    groups = await active_groups(session, shop_id, plan.id)
    if first is None:
        if after_index is not None and after_index + 1 < len(groups):
            first = groups[after_index + 1]
        else:
            first = await new_group(
                session, shop_id, plan, groups, actor=actor, now=now, days=days, start=start
            )
    base = groups.index(first)
    cache: dict[uuid.UUID, set[tuple[str, str]]] = {}
    payloads: dict[uuid.UUID, dict[str, Any]] = {}
    placed: list[Placed] = []
    count = max(0, sum(1 for _ in await _all_members(session, shop_id, plan.id)))
    for item in items:
        keys = {(f, s) for f, s, _ in exclusive_keys(item.payload)}
        label = ", ".join(sorted({lbl for _, _, lbl in exclusive_keys(item.payload)}))
        idx = base
        while True:
            if idx >= len(groups):
                await new_group(session, shop_id, plan, groups, actor=actor, now=now)
            group = groups[idx]
            held = await _keys_of_group(session, shop_id, group, cache, payloads)
            if not keys & held:
                break
            idx += 1
        count += 1
        session.add(
            ShopRecoPlanGroupMember(
                id=uuid.uuid4(),
                shop_id=shop_id,
                group_id=group.id,
                plan_card_id=item.row.id,
                version=item.version,
                position=count,
                added_at=now,
            )
        )
        cache[group.id] = (cache.get(group.id) or set()) | keys
        placed.append(Placed(item, group, label if idx > base else None))
    await session.flush()
    return placed


async def _all_members(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID
) -> list[ShopRecoPlanGroupMember]:
    by_group = await members_by_group(session, shop_id, plan_id)
    return [m for rows in by_group.values() for m, _, _ in rows]


# ------------------------------------------------------------------------------ edits


async def set_period(
    session: AsyncSession,
    shop_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    days: int | None,
    start: date | None,
    clear_start: bool,
    today: date,
    now: datetime,
) -> ShopRecoPlanGroup:
    g = await get_group(session, shop_id, group_id)
    if g.status == GROUP_APPROVED:
        raise ProposalError(ERROR_GROUP, 409, "Nhóm đã được xác nhận, không đổi được thời gian.")
    if days is not None:
        g.days = check_days(days)
    if start is not None:
        if start < today:
            raise ProposalError(
                ERROR_GROUP_DATE, 422, "Ngày bắt đầu của nhóm không được ở quá khứ."
            )
        g.start_date = start
    elif clear_start:
        g.start_date = None
    g.updated_at = _naive(now)
    await session.flush()
    return g


async def drop_members(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    plan_card_id: uuid.UUID,
    version: int | None,
    group_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Take a card (one version, or all) out of its groups; a group left empty is cancelled."""
    now = _naive(now)
    stmt = select(ShopRecoPlanGroupMember).where(
        ShopRecoPlanGroupMember.shop_id == shop_id,
        ShopRecoPlanGroupMember.plan_card_id == plan_card_id,
        ShopRecoPlanGroupMember.removed_at.is_(None),
    )
    if version is not None:
        stmt = stmt.where(ShopRecoPlanGroupMember.version == version)
    if group_id is not None:
        stmt = stmt.where(ShopRecoPlanGroupMember.group_id == group_id)
    rows = list(await session.scalars(stmt))
    touched = {m.group_id for m in rows}
    for m in rows:
        m.removed_at = now
    await session.flush()
    for gid in touched:
        left = await session.scalar(
            select(ShopRecoPlanGroupMember.id)
            .where(
                ShopRecoPlanGroupMember.group_id == gid,
                ShopRecoPlanGroupMember.removed_at.is_(None),
            )
            .limit(1)
        )
        if left is None:
            g = await session.get(ShopRecoPlanGroup, gid)
            if g is not None and g.status == GROUP_DRAFT:
                g.status = GROUP_CANCELLED
                g.updated_at = now
    await session.flush()
    return len(rows)


async def cancel_group(
    session: AsyncSession, shop_id: uuid.UUID, group_id: uuid.UUID, *, now: datetime
) -> None:
    """The group goes away; its cards stay in the plan, ungrouped."""
    g = await get_group(session, shop_id, group_id)
    if g.status == GROUP_APPROVED:
        raise ProposalError(ERROR_GROUP, 409, "Nhóm đã được xác nhận, không bỏ được.")
    members = await session.scalars(
        select(ShopRecoPlanGroupMember).where(
            ShopRecoPlanGroupMember.group_id == g.id, ShopRecoPlanGroupMember.removed_at.is_(None)
        )
    )
    for m in members:
        m.removed_at = _naive(now)
    g.status = GROUP_CANCELLED
    g.updated_at = _naive(now)
    await session.flush()


# ------------------------------------------------------------------------------ evaluation


async def entries_of(
    session: AsyncSession,
    shop_id: uuid.UUID,
    rows: Sequence[tuple[ShopRecoPlanGroupMember, ShopRecoPlanCard, ShopProposal]],
) -> list[Entry]:
    """The plan math's entries of a group: one per (card, version), the card's what-if inputs on the
    version they were set for."""
    out: list[Entry] = []
    for m, card_row, p in rows:
        payload = await store.card_payload(session, shop_id, p.id)
        if payload is None:
            continue
        base = {**payload, "code": p.code, "product_queue": p.product_queue}
        overrides = dict(card_row.inputs or {}) if m.version == card_row.chosen_version else {}
        out.append(Entry(entry_id(p.id, m.version), p.code, base, int(m.version), overrides))
    return out


def entry_id(card_id: uuid.UUID | str, version: int) -> str:
    return f"{card_id}@v{version}"


def split_entry_id(value: str) -> tuple[str, int | None]:
    head, _, tail = value.partition("@v")
    return head, int(tail) if tail.isdigit() else None


# ------------------------------------------------------------------------------ views


def member_json(
    m: ShopRecoPlanGroupMember,
    card_row: ShopRecoPlanCard,
    p: ShopProposal,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    vlist = versions.versions_of({**payload, "code": p.code})
    row = vlist[min(max(int(m.version), 1), len(vlist)) - 1] if vlist else {}
    return {
        "card_id": str(p.id),
        "plan_card_id": str(card_row.id),
        "entry_id": entry_id(p.id, m.version),
        "code": p.code,
        "version": int(m.version),
        "version_code": row.get("code") or (p.code and codes.version_code(p.code, int(m.version))),
        "version_label": row.get("label"),
        "title": payload.get("title"),
        "change_kind": payload.get("change_kind"),
        "family": payload.get("family"),
        "product_id": p.item_id,
        "n_targets": len(payload.get("targets") or []),
    }


def group_json(
    g: ShopRecoPlanGroup,
    window: tuple[date, date],
    members: Sequence[dict[str, Any]],
    *,
    aggregate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    first_code = next((m["code"] for m in members if m.get("code")), None)
    return {
        "id": str(g.id),
        "letter": g.letter,
        "name": f"Nhóm {g.letter}",
        "position": int(g.position),
        "code": g.code or (codes.group_code(first_code, g.letter) if first_code else None),
        "status": g.status,
        "days": int(g.days),
        "start": window[0].isoformat(),
        "end": window[1].isoformat(),
        "start_fixed": g.start_date is not None,
        "min_days": GROUP_MIN_DAYS,
        "members": list(members),
        "aggregate": None if aggregate is None else dict(aggregate),
    }


def export_rows(plan_out: Mapping[str, Any]) -> list[list[Any]]:
    """The rows of the plan's Excel export: group, group code, card code, version, version code,
    kind, title, product, first day, last day, days (a card with no group has an empty group)."""
    rows: list[list[Any]] = [
        [
            "Nhóm",
            "Mã nhóm",
            "Mã thẻ",
            "Phiên bản",
            "Mã phiên bản",
            "Loại thay đổi",
            "Tên thẻ",
            "Sản phẩm",
            "Bắt đầu",
            "Kết thúc",
            "Số ngày",
        ]
    ]
    plan = plan_out.get("plan") or {}
    grouped: set[tuple[str, int]] = set()
    for g in plan_out.get("groups") or []:
        for m in g["members"]:
            grouped.add((m["card_id"], m["version"]))
            rows.append(
                [
                    g["name"],
                    g["code"],
                    m["code"],
                    m["version"],
                    m["version_code"],
                    m["change_kind"],
                    m["title"],
                    m["product_id"],
                    g["start"],
                    g["end"],
                    g["days"],
                ]
            )
    for c in plan_out.get("cards") or []:
        if any(cid == c["card_id"] for cid, _ in grouped):
            continue
        rows.append(
            [
                "",
                "",
                c["code"],
                c["chosen_version"],
                c.get("chosen_version_code"),
                c["change_kind"],
                c["title"],
                c["product_id"],
                plan.get("planned_date"),
                "",
                "",
            ]
        )
    return rows


def export_workbook(plan_out: Mapping[str, Any]) -> bytes:
    """The export as an ``.xlsx`` (the stdlib writer of the seller-input template)."""
    from juli_backend.services.shop_inputs import xlsx_io

    rows = export_rows(plan_out)
    header = [(cell, xlsx_io.STYLE_HEADER) for cell in rows[0]]
    sheet = xlsx_io.SheetSpec(
        "Nhóm và phiên bản",
        [header, *rows[1:]],
        widths=[10, 18, 16, 10, 18, 22, 40, 16, 12, 12, 9],
    )
    return xlsx_io.write_workbook([sheet])


__all__ = [
    "DEFAULT_DAYS",
    "EXCLUSIVE_FIELDS",
    "Placed",
    "Placement",
    "active_groups",
    "cancel_group",
    "check_days",
    "drop_members",
    "entries_of",
    "entry_id",
    "exclusive_keys",
    "export_rows",
    "export_workbook",
    "get_group",
    "group_json",
    "grouped_card_ids",
    "member_json",
    "members_by_group",
    "new_group",
    "periods",
    "place",
    "set_period",
    "split_entry_id",
]
