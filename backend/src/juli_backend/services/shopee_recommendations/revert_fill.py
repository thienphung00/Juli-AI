"""batch-1118g F3.1 / F3.2: revert-fill jobs and read-back jobs of an EXECUTED card.

Contract (``fasttrack-notes/2026-11-18/briefs-1118g/_common.md`` B and C):

* ``revert_fill`` queues the undo of an executed card. Text kinds (title, description first line)
  keep their kind and carry ``payload.mode = "revert"`` with the captured before value;
  ``voucher_end`` / ``combo_end`` ask the Connector to HIGHLIGHT Kết thúc / Xóa (it never presses
  it); an affiliate commission goes back to its before value. ``target_key`` is always
  ``revert:<kind>:<id>``. Without a before value the job is ``failed`` (``revert_value_unknown``).
* ``readback`` jobs (``target_key = readback:<...>``) ask the Connector to open the page read-only
  and post the dataset through the ingest; the ingest then verifies the card at once.
* ``revert_state`` is ``card_detail.revert``: ``ready`` only when every revert job is saved /
  captured AND a read-back made after it shows the original value (text), the object ended or
  gone (voucher) -- a combo has no list reader, its revert job's ``saved`` is the evidence.

The serving rule lives in ``fill_queue._servable_card_jobs``. No migration: the jobs are rows of
``shopee_fill_jobs`` told apart by ``target_key`` prefix and ``payload.mode``.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import EVENT_EXECUTED, CardEvent
from juli_backend.models.platform_data import PlatformItem, PlatformPromotion
from juli_backend.models.shop_proposals import STATUS_EXECUTED, ShopProposal
from juli_backend.models.shopee_fill import (
    OPEN_STATUSES,
    STATUS_CANCELLED,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services.ingest.mapping import SHOPEE_PROMO_TYPES
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import fill_queue, fill_refs, store
from juli_backend.services.shopee_recommendations.fill_queue import (
    READBACK_PREFIX,
    REVERT_PREFIX,
    job_json,
)

MODE_REVERT = "revert"
MODE_READBACK = "readback"
KIND_READBACK = "readback"
KIND_VOUCHER_END = "voucher_end"
KIND_COMBO_END = "combo_end"
#: batch-1123-a F: the end of a Chương Trình Của Shop / Flash Sale Của Shop / Deal Sốc (Mua Kèm
#: Deal Sốc or Mua Để Nhận Quà) row, shown on the list and pressed by the person
KIND_DISCOUNT_END = "discount_end"
KIND_FLASH_SALE_END = "flash_sale_end"
KIND_DEAL_END = "deal_end"
#: ends and undos without a reader: the Connector seeing the save / the row ended is the evidence
#: (as for a combo)
NO_READER_REVERTS = (
    KIND_COMBO_END,
    KIND_DISCOUNT_END,
    KIND_FLASH_SALE_END,
    KIND_DEAL_END,
    "price",
    "cover_image",
    "variation_set",
)
VOUCHER_LIST_PATH = "/portal/marketing/vouchers/list"
COMBO_LIST_PATH = "/portal/marketing/bundle/list"
AFFILIATE_PATH = "/portal/web-seller-affiliate/open_campaign"
ERROR_NOT_EXECUTED = "card_not_executed"
ERROR_VALUE_UNKNOWN = "revert_value_unknown"
ERROR_TARGET_UNKNOWN = "revert_target_unknown"
ERROR_NOT_CONFIRMED = "revert_not_confirmed"
ERROR_ALREADY_REVERTED = "reco_already_reverted"
DATASET_ITEMS = "item_catalog"
DATASET_COMBOS = "combo_list"  # the Connector's combo list reader (S-E118)
COMBO_CHANGE_KINDS = ("bundle_deal", "combo", "combo_multi")
#: programme kinds: the executed change carries K1 ids / names, but no list reader confirms them
#: (D5: a save nobody reads is never a match), so no read-back job is queued
PROGRAMME_KINDS = ("product_discount", "flash_sale", "add_on", "gift")
DATASET_VOUCHERS = "voucher_list"  # the Connector's vouchers reader posts ingest `voucher_settings`
_ENDED_WORDS = ("end", "expire", "delete", "finish", "het", "kết thúc", "ket thuc")
_BEFORE_KEY = {"title": "title", "description_first_line": "first_line"}


is_aux = fill_queue.is_aux


def _naive(now: datetime) -> datetime:
    return now.replace(tzinfo=None)


async def _card_jobs(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID
) -> list[ShopeeFillJob]:
    return list(
        (
            await session.scalars(
                select(ShopeeFillJob)
                .where(ShopeeFillJob.shop_id == shop_id, ShopeeFillJob.proposal_id == proposal_id)
                .order_by(ShopeeFillJob.version, ShopeeFillJob.seq)
            )
        ).all()
    )


def _latest_forward(rows: list[ShopeeFillJob]) -> tuple[list[ShopeeFillJob], int]:
    forward = [j for j in rows if not is_aux(j)]
    if not forward:
        return [], 1
    latest = max(j.version for j in forward)
    return [j for j in forward if j.version == latest and j.status != STATUS_CANCELLED], latest


def _num(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------- revert jobs


def _revert_spec(
    j: ShopeeFillJob, before: dict[str, Any], executed_ref: str | None = None
) -> dict[str, Any] | None:
    """One forward job -> ``{kind, target, target_key, payload, error}`` of its undo, or ``None``
    for a kind the Connector does not undo (ads: by hand)."""
    payload = j.payload or {}
    target = dict(j.target or {})
    seen = payload.get("before_values") or {}
    if j.kind in fill_queue._TEXT_FIELDS:
        field = fill_queue._TEXT_FIELDS[j.kind]
        item_id = str(target.get("item_id") or "")
        value = seen.get(field["key"])
        if value in (None, ""):
            value = before.get(_BEFORE_KEY[j.kind])
        if not item_id:
            return None
        ok = isinstance(value, str) and value.strip() != "" and "\n" not in value
        spec_field = {k: field[k] for k in ("key", "label", "mode", "max_chars")}
        return {
            "kind": j.kind,
            "target": {"item_id": item_id},
            "target_key": f"{REVERT_PREFIX}{j.kind}:{item_id}",
            "payload": {
                "mode": MODE_REVERT,
                "open_path": f"/portal/product/{item_id}",
                "fields": [{**spec_field, "value": str(value).strip() if ok else ""}],
            },
            "error": None if ok else ERROR_VALUE_UNKNOWN,
        }
    if j.kind == "voucher":
        vid, code = fill_refs.split_ref(j.captured_ref or executed_ref)
        code = code or payload.get("voucher_code")
        suffix = payload.get("code_suffix") or (fill_refs.voucher_suffix(code) if code else None)
        name = payload.get("name")
        body = {
            "mode": MODE_REVERT,
            "open_path": VOUCHER_LIST_PATH,
            "code_suffix": suffix,
            "name": name,
        }
        if vid:
            body["voucher_id"] = vid
        if code:
            body["code"] = code
        return {
            "kind": KIND_VOUCHER_END,
            "target": fill_refs.voucher_target(vid, code or suffix, name),
            "target_key": f"{REVERT_PREFIX}voucher:{vid or suffix or j.seq}",
            "payload": body,
            "error": None if (vid or suffix or name) else ERROR_TARGET_UNKNOWN,
        }
    if j.kind == "combo":
        combo_id = fill_refs.split_ref(j.captured_ref)[0] or ""
        name = str(payload.get("name") or "")
        body: dict[str, Any] = {"mode": MODE_REVERT, "open_path": COMBO_LIST_PATH, "name": name}
        if combo_id:
            body["combo_id"] = combo_id
        return {
            "kind": KIND_COMBO_END,
            "target": {"combo_id": combo_id} if combo_id else {"name": name},
            "target_key": f"{REVERT_PREFIX}combo:{combo_id or name[:50] or j.seq}",
            "payload": body,
            "error": None if (combo_id or name) else ERROR_TARGET_UNKNOWN,
        }
    promo = _promo_revert_spec(j, payload, target, seen)
    if promo is not None:
        return promo
    if j.kind == "affiliate_commission":
        ids = [str(i) for i in (payload.get("product_ids") or target.get("product_ids") or [])]
        value = _num(seen.get("commission_pct"))
        if value is None:
            value = _num(before.get("commission_pct"))
        return {
            "kind": "affiliate_commission",
            "target": {"product_ids": ids},
            "target_key": f"{REVERT_PREFIX}affiliate_commission:{ids[0] if ids else j.seq}",
            "payload": {
                "mode": MODE_REVERT,
                "open_path": AFFILIATE_PATH,
                "product_ids": ids,
                "commission_pct": value,
            },
            "error": None if (ids and value is not None) else ERROR_VALUE_UNKNOWN,
        }
    return None


def _end_spec(
    j: ShopeeFillJob, kind: str, open_path: str, body: dict[str, Any], label: str
) -> dict[str, Any]:
    """The end of a programme row: by the id Shopee gave it when known, else what the list shows."""
    ref = str(j.captured_ref or "")
    if ref.isdigit():
        body = {**body, "id": ref}
    ok = bool(body.get("id") or body.get("name") or body.get("slot"))
    return {
        "kind": kind,
        "target": {"id": ref} if ref.isdigit() else {"name": body.get("name") or label},
        "target_key": f"{REVERT_PREFIX}{j.kind}:{(ref if ref.isdigit() else label)[:50] or j.seq}",
        "payload": {"mode": MODE_REVERT, "open_path": open_path, **body},
        "error": None if ok else ERROR_TARGET_UNKNOWN,
    }


def price_key(variation_id: str) -> str:
    """The Connector's report key of a variation's price (``price_`` + its letters and digits,
    the same rule as ``priceKey`` in the Connector's fillers.ts)."""
    return "price_" + re.sub(r"[^a-z0-9]", "", variation_id.lower())[:30]


def _old_prices(payload: dict[str, Any], seen: dict[str, Any]) -> list[dict[str, Any]]:
    """F2: each variation's price before the fill: what the Connector read on the page before it
    wrote (``price:<variation id>``), else the catalogue's price kept in the job."""
    kept = {str(r.get("variation_id")): r for r in payload.get("old_prices") or []}
    out: list[dict[str, Any]] = []
    for v in payload.get("variations") or []:
        vid = str(v.get("variation_id") or "")
        digits = "".join(ch for ch in str(seen.get(price_key(vid)) or "") if ch.isdigit())
        price = int(digits) if digits else (kept.get(vid) or {}).get("price")
        if not price:
            return []
        out.append(
            {
                "variation_id": vid,
                "price": int(price),
                **({"name": v["name"]} if v.get("name") else {}),
            }
        )
    return out


def _page(item_id: str) -> dict[str, Any]:
    return {"mode": MODE_REVERT, "open_path": f"/portal/product/{item_id}", "item_id": item_id}


def _promo_revert_spec(
    j: ShopeeFillJob, payload: dict[str, Any], target: dict[str, Any], seen: dict[str, Any]
) -> dict[str, Any] | None:
    """batch-1123-a F: the undo of a price / programme / product-page job, or ``None``."""
    item_id = str(payload.get("item_id") or target.get("item_id") or "")
    if j.kind == "price":
        old = _old_prices(payload, seen)
        return {
            "kind": "price",
            "target": {"item_id": item_id},
            "target_key": f"{REVERT_PREFIX}price:{item_id or j.seq}",
            "payload": {**_page(item_id), "variations": old},
            "error": None if (item_id and old) else ERROR_VALUE_UNKNOWN,
        }
    if j.kind == "product_discount":
        name = str(payload.get("name") or "")
        return _end_spec(
            j, KIND_DISCOUNT_END, fill_queue.DISCOUNT_LIST_OPEN_PATH, {"name": name}, name
        )
    if j.kind in ("add_on", "gift"):
        name = str(payload.get("name") or "")
        deal = {"name": name, "deal_type": j.kind}
        return _end_spec(j, KIND_DEAL_END, fill_queue.DEAL_LIST_OPEN_PATH, deal, name)
    if j.kind == "flash_sale":
        slot = payload.get("slot") or {}
        body: dict[str, Any] = (
            {"slot": {"day": slot.get("day"), "label": slot.get("label")}} if slot else {}
        )
        label = f"{slot.get('day')} {slot.get('label')}" if slot else ""
        return _end_spec(j, KIND_FLASH_SALE_END, fill_queue.FLASH_SALE_LIST_PATH, body, label)
    if j.kind == "cover_image":
        cover = str(payload.get("old_cover_url") or "")
        return {
            "kind": "cover_image",
            "target": {"item_id": item_id},
            "target_key": f"{REVERT_PREFIX}cover_image:{item_id or j.seq}",
            "payload": {**_page(item_id), "old_cover_url": cover},
            "error": None if (item_id and cover) else ERROR_VALUE_UNKNOWN,
        }
    if j.kind == "variation_set":
        added = [o.get("name") for o in payload.get("options") or [] if o.get("name")]
        return {
            "kind": "variation_set",
            "target": {"item_id": item_id},
            "target_key": f"{REVERT_PREFIX}variation_set:{item_id or j.seq}",
            "payload": {
                **_page(item_id),
                "remove_options": added,
                "old_variations": payload.get("old_variations") or [],
            },
            "error": None if (item_id and added) else ERROR_VALUE_UNKNOWN,
        }
    return None


async def _proposal(session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID) -> ShopProposal:
    p = await session.scalar(
        select(ShopProposal).where(ShopProposal.id == card_id, ShopProposal.shop_id == shop_id)
    )
    if p is None:
        raise ProposalError("reco_unknown_card", 404)
    return p


async def _executed_voucher_id(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> str | None:
    """The voucher id (digits) or, when the person typed a code, that code, as "Đã làm"
    recorded it (typed, or the Connector's captured one)."""
    events = await session.scalars(
        select(CardEvent).where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id == card_id,
            CardEvent.event_type == EVENT_EXECUTED,
        )
    )
    for event in events:
        change = (event.payload or {}).get("change") or {}
        target = change.get("target") or {}
        got = target.get("voucher_id") or target.get("voucher_code")
        if change.get("change_kind") == "voucher" and got:
            return str(got)
    return None


async def revert_fill(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, *, now: datetime
) -> dict[str, Any]:
    """Queue the undo of an executed card (idempotent: an existing revert job is reused, a
    failed / cancelled one is queued again). Returns ``{card_id, jobs, ready}``."""
    if not fill_queue.enabled():
        raise ProposalError("fill_disabled", 404)
    p = await _proposal(session, shop_id, card_id)
    if p.status != STATUS_EXECUTED:
        raise ProposalError(ERROR_NOT_EXECUTED, 409, f"a {p.status} card cannot be reverted")
    if (await store.card_meta(session, shop_id, card_id)).get("reverted"):
        raise ProposalError(ERROR_ALREADY_REVERTED, 409)
    moment = _naive(now)
    rows = await _card_jobs(session, shop_id, card_id)
    forward, version = _latest_forward(rows)
    existing = {j.target_key: j for j in rows if j.target_key.startswith(REVERT_PREFIX)}
    seq = len(rows)
    executed_ref = await _executed_voucher_id(session, shop_id, card_id)
    for fwd in forward:
        spec = _revert_spec(fwd, dict(p.change_before or {}), executed_ref)
        if spec is None:
            continue
        status = STATUS_FAILED if spec["error"] else STATUS_QUEUED
        row = existing.get(spec["target_key"])
        if row is None:
            seq += 1
            session.add(
                ShopeeFillJob(
                    shop_id=shop_id,
                    proposal_id=card_id,
                    version=version,
                    group_code=fwd.group_code,
                    kind=spec["kind"],
                    target=spec["target"],
                    target_key=spec["target_key"],
                    seq=seq,
                    payload=spec["payload"],
                    status=status,
                    error=spec["error"],
                    created_at=moment,
                    updated_at=moment,
                )
            )
        elif row.status in (STATUS_FAILED, STATUS_CANCELLED):
            row.payload, row.status, row.error = spec["payload"], status, spec["error"]
            row.claimed_by_token_id, row.lease_until, row.updated_at = None, None, moment
    await session.flush()
    state = await revert_state(session, shop_id, card_id)
    return {"card_id": str(card_id), **(state or {"jobs": [], "ready": False})}


# ----------------------------------------------------------------------------- read-back jobs


def _readback_of_change(kind: str, target: dict[str, Any]) -> dict[str, Any] | None:
    """The read-back of one change (``{change_kind, target}`` of an executed event or a revert
    job): key, page and dataset. ``None`` for a kind no reader covers (combo: no list reader)."""
    if kind in ("title", "description_first_line"):
        item_id = str(target.get("item_id") or "")
        if not item_id:
            return None
        return {
            "key": f"{READBACK_PREFIX}{item_id}",
            "open_path": f"/portal/product/{item_id}",
            "target": {"item_id": item_id},
            "datasets": [DATASET_ITEMS],
        }
    if kind == "voucher":
        vid = str(target.get("voucher_id") or "")
        code = str(target.get("voucher_code") or target.get("code") or "")
        name = str(target.get("name") or "")
        ref = vid or code or name[:40]
        if not ref:
            return None
        return {
            "key": f"{READBACK_PREFIX}voucher:{ref}",
            "open_path": VOUCHER_LIST_PATH,
            "target": {k: v for k, v in target.items() if v},
            "datasets": [DATASET_VOUCHERS],
            "forward_kind": "voucher",
        }
    if kind in COMBO_CHANGE_KINDS:
        cid = str(target.get("combo_id") or "")
        name = str(target.get("combo_name") or target.get("name") or "")
        ref = cid or name[:40]
        if not ref:
            return None
        return {
            "key": f"{READBACK_PREFIX}combo:{ref}",
            "open_path": COMBO_LIST_PATH,
            "target": {"combo_id": cid} if cid else {"combo_name": name},
            "datasets": [DATASET_COMBOS],
            "forward_kind": "combo",
        }
    if kind == "affiliate_commission":
        ids = [str(i) for i in (target.get("product_ids") or [])]
        if not ids:
            return None
        return {
            "key": f"{READBACK_PREFIX}affiliate:{ids[0]}",
            "open_path": AFFILIATE_PATH,
            "target": {"product_ids": ids},
            "datasets": [DATASET_ITEMS],
        }
    return None


async def _upsert_readbacks(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    specs: list[dict[str, Any]],
    now: datetime,
) -> list[ShopeeFillJob]:
    """One ``readback`` job per spec (deduplicated by ``target_key``); an open one is kept, a
    finished one is queued again (the same row: the key is unique per card version)."""
    if not specs:
        return []
    moment = _naive(now)
    rows = await _card_jobs(session, shop_id, card_id)
    _, version = _latest_forward(rows)
    existing = {j.target_key: j for j in rows if j.version == version}
    seq = len(rows)
    out: list[ShopeeFillJob] = []
    for spec in {s["key"]: s for s in specs}.values():
        payload = {
            "mode": MODE_READBACK,
            "open_path": spec["open_path"],
            "target": spec["target"],
            "datasets": spec["datasets"],
            "forward_kind": spec.get("forward_kind"),
        }
        row = existing.get(spec["key"])
        if row is None:
            seq += 1
            row = ShopeeFillJob(
                shop_id=shop_id,
                proposal_id=card_id,
                version=version,
                kind=KIND_READBACK,
                target=spec["target"],
                target_key=spec["key"][:80],
                seq=seq,
                payload=payload,
                status=STATUS_QUEUED,
                created_at=moment,
                updated_at=moment,
            )
            session.add(row)
        elif row.status not in OPEN_STATUSES:
            row.payload, row.status, row.error = payload, STATUS_QUEUED, None
            row.captured_ref, row.claimed_by_token_id, row.lease_until = None, None, None
            row.updated_at = moment
        out.append(row)
    await session.flush()
    return out


async def queue_readback_after_executed(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, *, now: datetime
) -> list[ShopeeFillJob]:
    """Contract C: after "Đã làm" queue the read-back of what the card changed (one job per
    object), from the ``executed`` events' ``change`` (so a card filled by hand has one too)."""
    if not fill_queue.enabled():
        return []
    events = await session.scalars(
        select(CardEvent).where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id == card_id,
            CardEvent.event_type == EVENT_EXECUTED,
        )
    )
    specs = []
    for event in events:
        change = (event.payload or {}).get("change") or {}
        spec = _readback_of_change(str(change.get("change_kind")), dict(change.get("target") or {}))
        if spec is not None:
            specs.append(spec)
    return await _upsert_readbacks(session, shop_id, card_id, specs, now)


async def queue_readback_after_revert(
    session: AsyncSession, shop_id: uuid.UUID, revert: ShopeeFillJob, *, now: datetime
) -> list[ShopeeFillJob]:
    """Contract C: a revert job is ``saved``: read the object back again (read-only)."""
    kind = {
        KIND_VOUCHER_END: "voucher",
        KIND_COMBO_END: "combo",
    }.get(revert.kind, revert.kind)
    target = dict(revert.target or {})
    spec = _readback_of_change(kind, target)
    if spec is None:
        return []
    return await _upsert_readbacks(session, shop_id, revert.proposal_id, [spec], now)


async def queue_pending_readbacks(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> int:
    """ "Đối chiếu ngay": a read-back for every executed card still waiting for its verdict."""
    from juli_backend.services.card_events import verification

    pending = {c.card_id for c in await verification.pending_changes(session, shop_id, now)}
    n = 0
    for card_id in sorted(pending, key=str):
        n += len(await queue_readback_after_executed(session, shop_id, card_id, now=now))
    return n


# ------------------------------------------------------------------------------ card_detail


def _same(a: Any, b: Any) -> bool:
    return " ".join(str(a or "").split()) == " ".join(str(b or "").split())


async def _item_matches(
    session: AsyncSession, shop_id: uuid.UUID, job: ShopeeFillJob, since: datetime
) -> bool:
    item_id = str((job.target or {}).get("item_id") or "")
    row = await session.scalar(
        select(PlatformItem).where(
            PlatformItem.shop_id == shop_id,
            PlatformItem.item_id == item_id,
            PlatformItem.variation_id == "",
        )
    )
    if row is None or row.captured_at is None or row.captured_at < since:
        return False
    want = ((job.payload or {}).get("fields") or [{}])[0].get("value")
    if job.kind == "title":
        return _same(row.name, want)
    return _same((row.extra or {}).get("description_first_line"), want)


async def _voucher_ended(
    session: AsyncSession,
    shop_id: uuid.UUID,
    voucher_id: str,
    since: datetime,
    code_suffix: str = "",
) -> bool:
    """A voucher list captured AFTER the revert was saved exists and either lacks the voucher or
    shows it ended. No such capture (or none at all) = not confirmed."""
    after = [
        p
        for p in (
            await session.scalars(
                select(PlatformPromotion).where(
                    PlatformPromotion.shop_id == shop_id,
                    PlatformPromotion.promo_type == SHOPEE_PROMO_TYPES["Voucher"],
                    PlatformPromotion.captured_at >= since,
                )
            )
        )
        if (p.extra or {}).get("voucher_id") is not None
    ]
    if not after:
        return False
    suffix = code_suffix.upper()

    def is_ours(p: PlatformPromotion) -> bool:
        x = p.extra or {}
        if voucher_id and voucher_id != "None":
            return str(x.get("voucher_id")) == voucher_id
        return bool(suffix) and str(x.get("voucher_code") or "").upper().endswith(suffix)

    mine = [p for p in after if is_ours(p)]
    if not mine:
        return True  # a list read after the save does not hold it
    newest = max(mine, key=lambda p: p.captured_at)
    word = str(newest.status or "").lower()
    return any(w in word for w in _ENDED_WORDS) or (
        newest.ends_at is not None and newest.ends_at <= newest.captured_at
    )


async def _affiliate_matches(
    session: AsyncSession, shop_id: uuid.UUID, job: ShopeeFillJob, since: datetime
) -> bool:
    want = _num((job.payload or {}).get("commission_pct"))
    for item_id in (job.payload or {}).get("product_ids") or []:
        row = await session.scalar(
            select(PlatformItem).where(
                PlatformItem.shop_id == shop_id,
                PlatformItem.item_id == str(item_id),
                PlatformItem.variation_id == "",
            )
        )
        extra = (row.extra or {}) if row else {}
        seen = _num(extra.get("affiliate_commission_pct"))
        read_at = str(extra.get("affiliate_commission_pct_at") or "")
        if want is None or seen is None or abs(seen - want) > 0.01:
            return False
        if not read_at or read_at < since.isoformat():  # read before the revert was saved
            return False
    return True


async def revert_state(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> dict[str, Any] | None:
    """``card_detail.revert``: ``{jobs, ready}``; ``None`` while no revert job exists."""
    rows = await _card_jobs(session, shop_id, card_id)
    reverts = [j for j in rows if j.target_key.startswith(REVERT_PREFIX)]
    if not reverts:
        return None
    live = [j for j in reverts if j.status != STATUS_CANCELLED]
    ready = bool(live) and all(j.status in (STATUS_SAVED, STATUS_CAPTURED) for j in live)
    if ready:
        readbacks = {j.target_key: j for j in rows if j.target_key.startswith(READBACK_PREFIX)}
        for j in live:
            if not await _confirmed(session, shop_id, j, readbacks):
                ready = False
                break
    # D5: ready on the Connector's own save signal only (no reader) is said apart from a read-back
    saved = [j for j in live if j.kind in NO_READER_REVERTS]
    return {
        "jobs": [job_json(j) for j in reverts],
        "ready": ready,
        "confirmed_by": ("saved_on_shopee" if saved else "readback") if ready else None,
    }


async def _confirmed(
    session: AsyncSession,
    shop_id: uuid.UUID,
    revert: ShopeeFillJob,
    readbacks: dict[str, ShopeeFillJob],
) -> bool:
    """The read-back made after ``revert`` was saved shows the original value / ended object."""
    if revert.kind in NO_READER_REVERTS:
        return True  # no list / page reader: the Connector saw the row ended / the save
    kind = "voucher" if revert.kind == KIND_VOUCHER_END else revert.kind
    spec = _readback_of_change(kind, dict(revert.target or {}))
    back = None if spec is None else readbacks.get(spec["key"][:80])
    if back is None or back.status != STATUS_CAPTURED or back.updated_at < revert.updated_at:
        return False
    if revert.kind in ("title", "description_first_line"):
        return await _item_matches(session, shop_id, revert, revert.updated_at)
    if revert.kind == KIND_VOUCHER_END:
        tgt = revert.target or {}
        return await _voucher_ended(
            session,
            shop_id,
            str(tgt.get("voucher_id") or ""),
            back.updated_at,
            str(tgt.get("code_suffix") or ""),
        )
    return await _affiliate_matches(session, shop_id, revert, revert.updated_at)


__all__ = [
    "ERROR_NOT_CONFIRMED",
    "is_aux",
    "queue_pending_readbacks",
    "queue_readback_after_executed",
    "queue_readback_after_revert",
    "revert_fill",
    "revert_state",
]
