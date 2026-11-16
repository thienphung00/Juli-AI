"""Nhập thẻ đã làm ngoài Juli: preview and commit the owner's sheet (owner decision 2026-11-16).

``preview`` reads the ``.xlsx`` (``external_rows.read_sheet``), maps each row to the card(s) it
becomes (or a skip reason), marks the refs already imported, and writes nothing. It returns a
``token``; ``commit`` takes the same file and that token (a different file is refused), and for
each card not imported yet:

1. evaluates the row's builder spec **as of its start date** (``as_of`` = Ngày thực hiện - 1 day,
   ``now`` = that day; a future start is evaluated today) and saves it exactly like a Tự tạo card
   (``shopee_builder.service.choose`` -> ``manual.create_manual``), with ``origin = "external"``,
   ``external_ref`` = the row's Mã and ``run_days`` = Thời gian đo. The result frozen in the
   ``proposed`` event is the card's Dự kiến: Đo lường compares Thực tế against it;
2. a "Đã thực hiện" / "Đang thử nghiệm" row is then approved and executed **on its date**
   (``mark_executed(executed_at=...)``, ``readback = False``: nothing "after" to read back; the
   measurement clock starts at the execution), its change set measuring Thời gian đo days;
   a "Đề xuất" row stays a sent card the owner decides on in Đề xuất.

Option B (2026-11-16): the executed / running rows also land in ONE executed Kế hoạch per file,
"Đã làm ngoài Juli dd/mm–dd/mm" (``executed_plans``), each card at its own past start date and run
days; Đề xuất rows stay plain sent cards, outside the plan.

Idempotent on (shop, ``external_ref``): a ref already on a live card is never created twice (a
card the board reset withdrew does not count, so a reset followed by an import brings it back).
Each card is written in its own savepoint: a row that cannot be built is reported, the others
are kept. AuthZ: owner-only, never a reviewer / the sample shop (``board_reset.require_owner``).
Nothing commits (the route does).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import ACTOR_SELLER, EVENT_ACCEPTED
from juli_backend.models.models import Shop
from juli_backend.models.shop_proposals import STATUS_APPROVED, STATUS_WITHDRAWN, ShopProposal
from juli_backend.services.card_events import keys
from juli_backend.services.planned_changes import external_rows as er
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import SpecRefused
from juli_backend.services.shopee_recommendations import (
    board_reset,
    change_sets,
    config,
    executed_plans,
    manual,
    result_store,
    store,
)
from juli_backend.services.shopee_recommendations import service as reco_service
from juli_backend.services.shopee_recommendations.loader import load_env

ORIGIN_EXTERNAL = "external"
ERROR_FILE = "external_invalid_file"
ERROR_TOKEN = "external_file_changed"
ERROR_NO_DATA = "external_no_data"

_SPEC: TypeAdapter[Any] = TypeAdapter(sp.VersionSpec)


@dataclass
class Preview:
    file_hash: str
    token: str
    rows: list[er.RowPlan]
    existing: set[str] = field(default_factory=set)
    missing_columns: list[str] = field(default_factory=list)
    today: date | None = None

    def counts(self) -> dict[str, int]:
        cards = [c for r in self.rows for c in r.cards]
        return {
            "rows": len(self.rows),
            "cards": len(cards),
            "create": sum(1 for c in cards if c.ref not in self.existing),
            "exists": sum(1 for c in cards if c.ref in self.existing),
            "skipped": sum(1 for r in self.rows if r.skip),
        }


@dataclass
class CommitResult:
    file_hash: str
    created: int
    exists: int
    refused: int
    skipped: int
    executed: int
    cards: list[dict[str, Any]]


def token_of(shop_id: uuid.UUID, file_hash: str) -> str:
    return hashlib.sha256(f"external-import:{shop_id}:{file_hash}".encode()).hexdigest()[:32]


def _naive(now: datetime) -> datetime:
    return now.replace(tzinfo=None) if now.tzinfo else now


async def _facts(
    session: AsyncSession, shop_id: uuid.UUID, now: datetime, rows: list[Any]
) -> er.Facts:
    env = await load_env(session, shop_id, now=now)
    if env is None:
        raise ProposalError(ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    campaigns = [
        er.Campaign(c.key, c.name, tuple(c.products), float(c.spend))
        for c in env.view.ads.campaigns
    ]
    known = {c.key for c in campaigns}
    campaigns += [er.Campaign(k, s.name) for k, s in env.campaigns.items() if k not in known]
    price_items = sorted({r.items[0] for r in rows if r.items and r.status != er.STATUS_CANCELLED})
    variations = await builder.variation_rows_for(session, shop_id, env, price_items)
    return er.Facts(today=now.date(), campaigns=campaigns, variations=variations)


async def existing_refs(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """``external_ref`` -> card id of the shop's live outside-Juli cards (a reset one is gone)."""
    reset = await store.reset_card_ids(session, shop_id)
    out: dict[str, uuid.UUID] = {}
    for p, card in await store.list_cards(session, shop_id):
        ref = card.get("external_ref")
        if card.get("origin") != ORIGIN_EXTERNAL or not ref:
            continue
        if p.status == STATUS_WITHDRAWN and str(p.id) in reset:
            continue
        out[str(ref)] = p.id
    return out


async def preview_import(
    session: AsyncSession,
    shop: Shop,
    data: bytes,
    *,
    user_id: uuid.UUID,
    reviewer: bool,
    now: datetime,
) -> Preview:
    """Read and map the file; writes nothing."""
    await board_reset.require_owner(session, shop, user_id, reviewer=reviewer)
    now = _naive(now)
    file_hash = hashlib.sha256(data).hexdigest()
    token = token_of(shop.id, file_hash)
    try:
        rows, missing = er.read_sheet(data, now.date())
    except er.SheetError as exc:
        raise ProposalError(ERROR_FILE, 422, str(exc)) from None
    if missing:
        return Preview(file_hash, token, [], missing_columns=missing)
    facts = await _facts(session, shop.id, now, rows)
    plans = er.plan_rows(rows, facts)
    existing = set(await existing_refs(session, shop.id))
    return Preview(file_hash, token, plans, existing, today=now.date())


def _when(on: date) -> datetime:
    return datetime.combine(on, time.min)


def forecast_day(on: date | None, today: date) -> date:
    """The day a card's Dự kiến is made on: its start date (a future one: today); the evaluation
    reads only the data before it (``as_of`` = that day - 1)."""
    return min(on or today, today)


async def _approve_and_execute(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    card: dict[str, Any],
    row: er.SheetRow,
    ref: str,
    *,
    user_id: uuid.UUID,
    now: datetime,
    plan_key: str,
) -> uuid.UUID:
    """Returns the id of the executed Kế hoạch the card now belongs to."""
    assert row.on is not None
    at = _when(row.on)
    p = await session.get(ShopProposal, card_id)
    assert p is not None
    # Option B: the card joins the import's executed Kế hoạch at its own (past) start date; the
    # past date is allowed here only (origin "external", ``allow_past``)
    plan = await executed_plans.attach_executed(
        session,
        shop_id,
        p,
        key=plan_key,
        on=row.on,
        actor=manual.Actor("seller", user_id),
        now=now,
        allow_past=True,
    )
    approval = await proposals.record_approval(
        session,
        p,
        decision=STATUS_APPROVED,
        channel="in_app",
        decided_at=at,
        now=now,
        decided_by_user_id=user_id,
        note=f"external {ref}",
        snapshot_extra={
            "code": p.code,
            "external_ref": ref,
            "chosen_version": 1,
            "plan_id": str(plan.id),
            "plan_code": plan.code,
        },
    )
    items = card["scope"]["product_ids"]
    await store.write_event(
        session,
        shop_id,
        card_id,
        event_type=EVENT_ACCEPTED,
        actor=ACTOR_SELLER,
        occurred_at=at,
        dedup_key=keys.accepted(approval.id),
        payload={
            "approval_id": str(approval.id),
            "chosen_version": 1,
            "imported": True,
            "external_ref": ref,
            "approved_with": {
                "inputs": card["inputs"],
                "execution_sheet": card["execution_sheet"],
            },
        },
        family=card["family"],
        card=card,
        change_kind=card["change_kind"],
        subject=("item", str(items[0])) if items else ("shop", str(card_id)),
        code=p.code,
    )
    # the forecast made as of the start date is the one the measurement is judged against
    await result_store.freeze_at_approval(session, shop_id, card_id, card, 1)
    await reco_service.mark_executed(
        session,
        shop_id,
        card_id,
        now=now,
        executed_at=at,
        user_id=user_id,
        evidence_ref=f"external:{ref}",
        payload_extra={"imported": True, "readback": False, "external_ref": ref},
    )
    if row.days:
        await _set_window(session, shop_id, card_id, row.days, now=now)
    return plan.id


async def _set_window(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, days: int, *, now: datetime
) -> None:
    """The change set measures Thời gian đo days (a set shared with another card: the longest),
    within the set's 3-90 day bounds; a single card's reading still runs its own ``run_days``
    (``verdict.run_days``), so a 1-day voucher is read over its 1 day."""
    meta = await store.card_meta(session, shop_id, card_id)
    set_id = meta.get("change_set")
    if not set_id:
        return
    cs = await change_sets.get(session, shop_id, uuid.UUID(str(set_id)))
    want = min(max(days, config.WINDOW_MIN_DAYS), config.WINDOW_MAX_DAYS)
    alone = list(cs.card_ids or []) == [str(card_id)]
    cs.window_days = want if alone else max(int(cs.window_days or 0), want)
    cs.window_source = "custom"
    cs.updated_at = now
    for cid in cs.card_ids or []:
        await store.set_meta(
            session,
            shop_id,
            uuid.UUID(str(cid)),
            {"window_days": cs.window_days, "plan_days": cs.window_days},
        )
    await session.flush()


async def _create(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan: er.CardPlan,
    row: er.SheetRow,
    *,
    user_id: uuid.UUID,
    now: datetime,
    plan_key: str,
) -> dict[str, Any]:
    spec = _SPEC.validate_python(plan.spec)
    day = forecast_day(row.on, now.date())
    as_of = day - timedelta(days=1)
    executed = row.status in er.EXECUTED_STATUSES
    # an executed row is recorded on its own day; a proposal is sent today (so it does not
    # expire at once) but still evaluated as of its start date
    card_now = _when(day) if executed and day < now.date() else now
    extra: dict[str, Any] = {
        "external_ref": plan.ref,
        "external": {
            "row": row.row,
            "ref": row.ref,
            "category": row.category,
            "status": row.status,
            "started_on": row.on.isoformat() if row.on else None,
            "run_days": row.days,
            "forecast_as_of": as_of.isoformat(),
        },
    }
    if row.days:
        extra["run_days"] = row.days
    out = await builder.choose(
        session,
        shop_id,
        [spec],
        0,
        primary=False,
        acknowledge_breaches=True,
        actor=manual.Actor("seller", user_id),
        as_of=as_of,
        now=card_now,
        origin=ORIGIN_EXTERNAL,
        card_extra=extra,
    )
    card_id = uuid.UUID(out["id"])
    await store.set_meta(
        session, shop_id, card_id, {"external_ref": plan.ref, "external": extra["external"]}
    )
    plan_id = None
    if executed:
        plan_id = await _approve_and_execute(
            session, shop_id, card_id, out["card"], row, plan.ref,
            user_id=user_id, now=now, plan_key=plan_key,
        )  # fmt: skip
    p = await session.get(ShopProposal, card_id)
    return {
        "card_id": str(card_id),
        "code": out.get("code"),
        "status": None if p is None else p.status,
        "executed_on": row.on.isoformat() if executed and row.on else None,
        "forecast_as_of": as_of.isoformat(),
        "plan_id": None if plan_id is None else str(plan_id),
    }


async def commit_import(
    session: AsyncSession,
    shop: Shop,
    data: bytes,
    *,
    token: str,
    user_id: uuid.UUID,
    reviewer: bool,
    now: datetime,
) -> CommitResult:
    """Create the preview's new cards (see the module docstring). Never commits."""
    now = _naive(now)
    preview = await preview_import(session, shop, data, user_id=user_id, reviewer=reviewer, now=now)
    if token != preview.token:
        raise ProposalError(ERROR_TOKEN, 409, "the file is not the one that was previewed")
    if preview.missing_columns:
        raise ProposalError(
            ERROR_FILE, 422, "missing columns: " + ", ".join(preview.missing_columns)
        )
    cards: list[dict[str, Any]] = []
    counts = {"created": 0, "exists": 0, "refused": 0, "executed": 0}
    done = set(preview.existing)
    plan_key = f"{executed_plans.KEY_EXTERNAL}:{preview.file_hash}"
    plan_ids: dict[str, uuid.UUID] = {}
    for rp in preview.rows:
        for plan in rp.cards:
            base = {
                "ref": plan.ref,
                "row": rp.row.row,
                "change_kind": plan.kind,
                "status": rp.row.status,
                "run_days": rp.row.days,
            }
            if plan.ref in done:
                counts["exists"] += 1
                cards.append({**base, "action": "exists", "reason": "exists"})
                continue
            try:
                async with session.begin_nested():
                    got = await _create(
                        session, shop.id, plan, rp.row, user_id=user_id, now=now, plan_key=plan_key
                    )
            except (ProposalError, SpecRefused, ValidationError, builder.NoShopeeData) as exc:
                counts["refused"] += 1
                message = getattr(exc, "detail", None) or type(exc).__name__
                cards.append(
                    {**base, "action": "refused", "reason": "build_failed", "message": message}
                )
                continue
            done.add(plan.ref)
            counts["created"] += 1
            if got["executed_on"]:
                counts["executed"] += 1
            if got["plan_id"]:
                plan_ids[got["plan_id"]] = uuid.UUID(got["plan_id"])
            cards.append({**base, "action": "created", **got})
    for plan_id in plan_ids.values():
        await executed_plans.refresh(session, shop.id, plan_id, now=now)
    if counts["created"]:
        await reco_service.requeue(session, shop.id, now=now)
    await session.flush()
    return CommitResult(
        file_hash=preview.file_hash,
        created=counts["created"],
        exists=counts["exists"],
        refused=counts["refused"],
        skipped=sum(1 for r in preview.rows if r.skip),
        executed=counts["executed"],
        cards=cards,
    )


# ------------------------------------------------------------------------------- JSON


def row_json(rp: er.RowPlan, existing: set[str], today: date) -> dict[str, Any]:
    r = rp.row
    return {
        "row": r.row,
        "ref": r.ref,
        "category": r.category,
        "items": list(r.items),
        "shop_wide": r.shop_wide,
        "status": r.status,
        "status_label": er.STATUS_LABELS[r.status],
        "started_on": r.on.isoformat() if r.on else None,
        "run_days": r.days,
        "forecast_as_of": (forecast_day(r.on, today) - timedelta(days=1)).isoformat(),
        "skipped": rp.skip is not None,
        "reason": rp.skip,
        "reason_label": er.SKIP_LABELS.get(rp.skip or "") if rp.skip else None,
        "cards": [
            {
                "ref": c.ref,
                "change_kind": c.kind,
                "action": "exists" if c.ref in existing else "create",
            }
            for c in rp.cards
        ],
    }


def preview_json(preview: Preview) -> dict[str, Any]:
    today = preview.today or date.today()
    return {
        "file_hash": preview.file_hash,
        "token": preview.token,
        "missing_columns": preview.missing_columns,
        "counts": preview.counts(),
        "rows": [row_json(r, preview.existing, today) for r in preview.rows if not r.skip],
        "skipped": [row_json(r, preview.existing, today) for r in preview.rows if r.skip],
    }


def commit_json(result: CommitResult) -> dict[str, Any]:
    return {
        "file_hash": result.file_hash,
        "created": result.created,
        "exists": result.exists,
        "refused": result.refused,
        "skipped": result.skipped,
        "executed": result.executed,
        "cards": result.cards,
    }


__all__ = [
    "ERROR_FILE",
    "ERROR_NO_DATA",
    "ERROR_TOKEN",
    "ORIGIN_EXTERNAL",
    "CommitResult",
    "Preview",
    "commit_import",
    "commit_json",
    "existing_refs",
    "preview_import",
    "preview_json",
    "token_of",
]
