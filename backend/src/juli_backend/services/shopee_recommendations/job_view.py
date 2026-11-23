"""K3 / K4 (batch-1123-a2): the one job a card shows the Demo, with its Vietnamese status.

``job = {job_id, role, kind, status, status_label, open_path, filled, total,
readback: {result, diffs}}`` on the card list, the card detail and Thực hiện. ``role`` is
``forward`` | ``revert`` | ``readback``; ``kind`` stays the fill-job kind (voucher, combo,
voucher_end, ...). The Demo opens ``https://banhang.shopee.vn{open_path}#juli-fill={job_id}``.

Which job: an open or finished revert job (the step the person acts on next) > the read-back job
of an executed card > the newest forward job (an unfinished one first). ``can_mark_done`` is
true whenever an approved card has a forward job (every kind).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_fill import (
    STATUS_CANCELLED,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services.shopee_recommendations import fill_queue, readback_compare

ROLE_FORWARD, ROLE_REVERT, ROLE_READBACK = "forward", "revert", "readback"
WAITING = "Chờ điền"
FILLED = "Đã điền · chờ bạn lưu"
SAVED = "Đã lưu · chờ xác minh"
MATCH = "Khớp"
MISMATCH = "Lệch"
FAILED = "Không điền được"
_PROMO_FORWARD = {"voucher": "voucher", "bundle_deal": "combo", "combo": "combo"}


def role_of(j: ShopeeFillJob) -> str:
    if j.target_key.startswith(fill_queue.REVERT_PREFIX):
        return ROLE_REVERT
    if j.target_key.startswith(fill_queue.READBACK_PREFIX):
        return ROLE_READBACK
    return ROLE_FORWARD


def status_label(role: str, status: str, result: str | None) -> str:
    if status == STATUS_FAILED:
        return FAILED
    if role == ROLE_READBACK and result == "match":
        return MATCH
    if role == ROLE_READBACK and result == "mismatch":
        return MISMATCH
    if role == ROLE_READBACK:
        return SAVED
    if status == STATUS_FILLED:
        return FILLED
    if status in (STATUS_SAVED, STATUS_CAPTURED):
        return SAVED
    return WAITING


def _progress(j: ShopeeFillJob) -> tuple[int | None, int | None]:
    prog = (j.payload or {}).get("progress") or {}
    total = prog.get("total")
    filled = prog.get("filled")
    if total is not None and j.status in (STATUS_FILLED, STATUS_SAVED, STATUS_CAPTURED):
        filled = total  # a saved form was filled to the end (E114: never "0/8" after a save)
    return (None if filled is None else int(filled)), (None if total is None else int(total))


def pick(rows: list[ShopeeFillJob]) -> ShopeeFillJob | None:
    live = [j for j in rows if j.status != STATUS_CANCELLED]
    reverts = [j for j in live if role_of(j) == ROLE_REVERT]
    if reverts:
        return max(reverts, key=lambda j: j.seq)
    readbacks = [j for j in live if role_of(j) == ROLE_READBACK]
    forward = [j for j in live if role_of(j) == ROLE_FORWARD]
    if readbacks and forward and all(j.status in (STATUS_SAVED, STATUS_CAPTURED) for j in forward):
        return max(readbacks, key=lambda j: j.seq)
    if forward:
        latest = max(j.version for j in forward)
        mine = [j for j in forward if j.version == latest]
        unfinished = [j for j in mine if j.status not in (STATUS_SAVED, STATUS_CAPTURED)]
        return (unfinished or mine)[0 if unfinished else -1]
    return max(readbacks, key=lambda j: j.seq) if readbacks else None


def _stored(j: ShopeeFillJob) -> dict[str, Any] | None:
    got = (j.payload or {}).get("compare")
    return got if isinstance(got, dict) else None


async def readback_result(
    session: AsyncSession, shop_id: uuid.UUID, rows: list[ShopeeFillJob]
) -> dict[str, Any]:
    """S-E110: the card's read-back result (stored once computed; computed from the newest
    captured read-back job + the forward job's payload otherwise)."""
    empty: dict[str, Any] = {"result": None, "diffs": []}
    done = [j for j in rows if role_of(j) == ROLE_READBACK and j.status == STATUS_CAPTURED]
    if not done:
        return empty
    back = max(done, key=lambda j: j.updated_at or j.created_at)
    kept = _stored(back)
    if kept is not None and kept.get("result"):
        return kept
    spec = back.payload or {}
    kind = {"voucher": "voucher", "combo": "combo"}.get(str(spec.get("forward_kind") or ""))
    if kind is None:
        return empty
    forward = [
        j
        for j in rows
        if role_of(j) == ROLE_FORWARD and j.kind == kind and j.status != STATUS_CANCELLED
    ]
    if not forward:
        return empty
    want = readback_compare.expected_of(
        kind, dict(max(forward, key=lambda j: j.version).payload or {})
    )
    row = await readback_compare.observed_row(
        session, shop_id, kind, dict(back.target or {}), back.created_at
    )
    if row is None or not want:
        return empty
    out = readback_compare.compare(want, readback_compare.observed_of(kind, row))
    if out["result"]:
        back.payload = {**spec, "compare": out}
        await session.flush()
    return out


def view(j: ShopeeFillJob, result: dict[str, Any]) -> dict[str, Any]:
    role = role_of(j)
    filled, total = _progress(j)
    return {
        "job_id": str(j.id),
        "role": role,
        "kind": j.kind,
        "status": j.status,
        "status_label": status_label(role, j.status, result.get("result")),
        "open_path": (j.payload or {}).get("open_path"),
        "filled": filled,
        "total": total,
        "readback": {"result": result.get("result"), "diffs": list(result.get("diffs") or [])},
    }


async def for_cards(
    session: AsyncSession, shop_id: uuid.UUID, card_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """``{card id: {"job": view | None, "can_mark_done": bool}}`` for every card id given."""
    ids = list(card_ids)
    by_card: dict[uuid.UUID, list[ShopeeFillJob]] = {i: [] for i in ids}
    if ids:
        for j in await session.scalars(
            select(ShopeeFillJob)
            .where(ShopeeFillJob.shop_id == shop_id, ShopeeFillJob.proposal_id.in_(ids))
            .order_by(ShopeeFillJob.version, ShopeeFillJob.seq)
        ):
            by_card[j.proposal_id].append(j)
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for cid, rows in by_card.items():
        chosen = pick(rows)
        result = await readback_result(session, shop_id, rows) if chosen is not None else {}
        out[cid] = {
            "job": None if chosen is None else view(chosen, result),
            "has_forward": any(
                role_of(j) == ROLE_FORWARD and j.status != STATUS_CANCELLED for j in rows
            ),
        }
    return out
