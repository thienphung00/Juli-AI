"""The fill queue (P97 D85.6): an approval queues one job per page the Connector must open.

``enqueue_for_approval`` is called by ``service._decide`` after a card version is approved and by
the group approval (T4). It turns the approved card into plain job rows (``shopee_fill_jobs``):
what the Connector types, validated here, and where (a Seller Centre path). The Connector polls
``GET /v1/ingest/fill-jobs`` for its token's shop only, opens the page with ``#juli-fill=<job id>``,
types, highlights and reports. The person presses Shopee's own save. Nothing here talks to Shopee.

Kinds filled: ``title`` / ``description_first_line`` (product edit page), ``voucher`` (new shop or
product voucher), ``ads_edit`` (budget / ROAS pencils of one campaign), ``affiliate_commission``
(bulk edit of the open campaign's commission). Combo is not queued yet (T4 reshapes the spec).

Server-side kill switch: ``CONNECTOR_FILL_LISTING`` (off: nothing is queued or served).
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_fill import (
    OPEN_STATUSES,
    STATUS_CANCELLED,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_OPENED,
    STATUS_QUEUED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import codes, config, store, versions

logger = logging.getLogger(__name__)

ENV_FLAG = "CONNECTOR_FILL_LISTING"  # same switch as fill.py (not imported: fill imports service)
_REF = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ERROR_JOB_UNKNOWN = "fill_job_unknown"
ERROR_JOB_STATE = "fill_job_state"
ERROR_JOB_BAD = "fill_job_bad"

MIN_DAILY_BUDGET = 100_000
VOUCHER_CODE_PREFIX = "ORYV"  # shown by Seller Centre as the fixed prefix of this shop's codes
MAX_PRODUCTS = 100
MAX_VOUCHER_NAME = 100
ICT = timedelta(hours=7)
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# TODO(P97 T3, combo): ``bundle_deal`` / combo cards are NOT queued. T4 reshapes the combo spec to
# Shopee's tiers (name <= 25, dates, "Mua N -> x % / d / gia dac biet" rows, order limit, product
# list). When that lands, add a ``combo`` job kind here and a filler in the Connector
# (``fill/fillers.ts``) on the ``ensureRows`` / ``pickProducts`` controls already built and tested
# against ``test/fixtures/fill/combo-tiers.html``; the form is /portal/marketing/bundle/new.
#: change kinds this queue fills, and the job kind each one becomes
_KIND_OF = {
    "title": "title",
    "description_first_line": "description_first_line",
    "min_spend_voucher": "voucher",
    "review_voucher": "voucher",
    "ads_budget": "ads_edit",
    "ads_roas_target": "ads_edit",
    "affiliate_commission": "affiliate_commission",
}
_TEXT_FIELDS = {
    "title": {
        "key": "title",
        "label": "Tên sản phẩm",
        "mode": "replace",
        "max_chars": config.MAX_TITLE_CHARS,
        "expected": "title",
    },
    "description_first_line": {
        "key": "description_first_line",
        "label": "Mô tả sản phẩm",
        "mode": "first_line",
        "max_chars": 500,
        "expected": "first_line",
    },
}
#: forward transitions the Connector may report (anything may fail)
_NEXT = {
    STATUS_QUEUED: {STATUS_OPENED, STATUS_FILLED, STATUS_FAILED},
    STATUS_OPENED: {STATUS_OPENED, STATUS_FILLED, STATUS_SAVED, STATUS_FAILED},
    STATUS_FILLED: {STATUS_FILLED, STATUS_SAVED, STATUS_CAPTURED, STATUS_FAILED},
    STATUS_SAVED: {STATUS_SAVED, STATUS_CAPTURED, STATUS_FAILED},
}


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def supported(change_kind: str) -> bool:
    return change_kind in _KIND_OF


def voucher_code_suffix(card_code: str, version: int) -> str:
    """Up to 5 characters A-Z 0-9 from the card code and version, stable and readable
    (``JC-2611-0007`` V1 -> base 36 of 2611 0007 x 8 + 0)."""
    parsed = codes.parse_code(card_code)
    if parsed is None:
        raise ValueError("not a card code")
    m = codes.CODE_RE.match(parsed[0])
    assert m is not None
    n = (int(m["yymm"]) * 10_000 + int(m["seq"])) * 8 + (max(version, 1) - 1) % 8
    n %= 36**5
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _B36[r] + out
    return out or "0"


def _shopee_time(moment: datetime) -> str:
    return moment.strftime("%H:%M %d-%m-%Y")


def voucher_window(now: datetime, days: int) -> tuple[str, str]:
    """Start at the next full hour GMT+7 at least an hour ahead; end one minute before ``days``
    days later. Format of Seller Centre's pickers: ``HH:mm DD-MM-YYYY``."""
    local = (now if now.tzinfo is None else now.astimezone(UTC).replace(tzinfo=None)) + ICT
    start = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    end = start + timedelta(days=max(int(days), 1)) - timedelta(minutes=1)
    return _shopee_time(start), _shopee_time(end)


def _ids(raw: Any) -> list[str]:
    out: list[str] = []
    for v in raw or []:
        s = str(v).strip()
        if re.fullmatch(r"\d{1,20}", s) and s not in out:
            out.append(s)
    return out[:MAX_PRODUCTS]


def _num(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if float(value) == int(value) else float(value)


def _voucher_payload(
    card: dict[str, Any], inputs: dict[str, Any], code: str, version: int, now: datetime,
    product_ids: list[str],
) -> dict[str, Any] | None:  # fmt: skip
    pct, value = _num(inputs.get("pct")), _num(inputs.get("value"))
    if pct is None and (value is None or value <= 0):
        return None
    days = int(_num(inputs.get("days")) or config.VOUCHER_DAYS)
    starts, ends = voucher_window(now, days)
    discount: dict[str, Any]
    if pct is not None:
        mx = _num(inputs.get("max_value"))
        discount = {
            "type": "percent",
            "value": pct,
            "max": {"mode": "limited", "value": int(mx)} if mx else {"mode": "unlimited"},
        }
    else:
        discount = {"type": "amount", "value": int(value or 0)}
    usage = int(_num(inputs.get("quantity")) or 0)
    if usage < 1:
        return None
    return {
        "usecase": 2 if product_ids else 1,
        "name": f"{code} V{version} — {card.get('title') or 'voucher'}"[:MAX_VOUCHER_NAME],
        "code_suffix": voucher_code_suffix(code, version),
        "starts_at": starts,
        "ends_at": ends,
        "voucher_type": "promotion",
        "discount": discount,
        "min_spend": int(_num(inputs.get("min_spend")) or 0),
        "usage_total": usage,
        "per_buyer": int(_num(inputs.get("per_user_limit")) or 1),
        "display": "private" if product_ids else "multi",
        "product_ids": product_ids,
    }


async def campaign_id_of(
    session: AsyncSession, shop_id: uuid.UUID, campaign_key: str | None
) -> tuple[str | None, str | None]:
    """``(campaign_id, page variant)`` of a report campaign: the newest ``ads_campaign_daily``
    row of that segment carries ``extra.campaign_id``; a group campaign ("Chiến dịch nhóm")
    is edited on ``manual-mpd``, the others on ``manual``."""
    if not campaign_key:
        return None, None
    rows = (
        await session.scalars(
            select(PlatformDailyMetric)
            .where(
                PlatformDailyMetric.shop_id == shop_id,
                PlatformDailyMetric.dataset == "ads_campaign_daily",
                PlatformDailyMetric.segment == campaign_key,
            )
            .order_by(PlatformDailyMetric.day.desc(), PlatformDailyMetric.captured_at.desc())
            .limit(5)
        )
    ).all()
    for r in rows:
        cid = (r.extra or {}).get("campaign_id")
        if cid is not None and re.fullmatch(r"\d{1,20}", str(cid)):
            group = "nhóm" in (r.platform_source or "").casefold()
            return str(cid), "manual-mpd" if group else "manual"
    return None, None


def _ads_payload(
    kind: str, inputs: dict[str, Any], campaign_id: str, variant: str
) -> tuple[dict[str, Any] | None, str | None]:
    """``(payload, error)``: a budget under Shopee's minimum is a failed job, not a payload."""
    payload: dict[str, Any] = {
        "campaign_id": campaign_id,
        "variant": variant,
        "open_path": f"/portal/marketing/pas/product/{variant}/{campaign_id}",
    }
    if kind == "ads_budget":
        budget = _num(inputs.get("daily_budget"))
        if budget is None:
            return None, "budget_missing"
        if budget == 0:
            payload["budget"] = {"mode": "unlimited"}
        elif budget < MIN_DAILY_BUDGET:
            return None, "budget_below_minimum"
        else:
            payload["budget"] = {"mode": "daily", "value": int(budget)}
    else:
        roas = _num(inputs.get("roas_target"))
        if roas is None or not 0 < roas <= 100:
            return None, "roas_missing"
        payload["roas"] = {"mode": "custom", "value": float(roas)}
    return payload, None


def _card_text(card: dict[str, Any], change_kind: str) -> str:
    spec = _TEXT_FIELDS[change_kind]
    for change in (card.get("execution_sheet") or {}).get("changes") or []:
        if change.get("change_kind") == change_kind:
            return str((change.get("expected") or {}).get(spec["expected"]) or "").strip()
    return ""


async def build_jobs(
    session: AsyncSession,
    shop_id: uuid.UUID,
    p: ShopProposal,
    card: dict[str, Any],
    version: int,
    targets: list[dict[str, Any]] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """Plain dicts ``{kind, target, target_key, payload, status, error}`` (no database writes)."""
    change_kind = str(card.get("change_kind"))
    kind = _KIND_OF.get(change_kind)
    if kind is None or not p.code:
        return []
    base_inputs = dict(card.get("inputs") or {})
    scope_items = _ids(card.get("scope", {}).get("product_ids"))
    given = [t for t in (targets or []) if isinstance(t, dict)]
    jobs: list[dict[str, Any]] = []

    def job(target: dict[str, Any], key: str, payload: dict[str, Any], error: str | None = None):
        jobs.append(
            {
                "kind": kind,
                "target": target,
                "target_key": key[:80],
                "payload": payload,
                "status": STATUS_FAILED if error else STATUS_QUEUED,
                "error": error,
            }
        )

    if kind in _TEXT_FIELDS:
        spec = _TEXT_FIELDS[kind]
        value = _card_text(card, kind)
        items = [_ids([t.get("item_id")]) for t in given] or [scope_items[:1]]
        for item_ids in items:
            if not item_ids:
                continue
            ok = bool(value) and "\n" not in value and len(value) <= int(str(spec["max_chars"]))
            field = {k: spec[k] for k in ("key", "label", "mode", "max_chars")}
            job(
                {"item_id": item_ids[0]},
                f"{kind}:{item_ids[0]}",
                {
                    "open_path": f"/portal/product/{item_ids[0]}",
                    "fields": [{**field, "value": value}],
                },
                None if ok else "text_not_fillable",
            )
    elif kind == "voucher":
        groups = [_ids(t.get("product_ids") or [t.get("item_id")]) for t in given] or [[]]
        for n, vids in enumerate(groups):
            inputs = {**base_inputs, **((given[n].get("inputs") or {}) if given else {})}
            payload = _voucher_payload(card, inputs, p.code, version, now, vids)
            usecase = 2 if vids else 1
            key = f"voucher:{usecase}:{','.join(vids) or 'shop'}"
            if payload is None:
                job({"product_ids": vids}, key, {}, "voucher_incomplete")
                continue
            payload["open_path"] = f"/portal/marketing/vouchers/new?usecase={usecase}"
            job({"product_ids": vids}, key, payload)
    elif kind == "ads_edit":
        scope = card.get("scope") or {}
        change_target = (card.get("change") or {}).get("target") or {}
        wanted = given or [{}]
        for t in wanted:
            cid = str(t.get("campaign_id") or change_target.get("campaign_id") or "")
            variant = str(t.get("variant") or "")
            if not cid:
                cid_found, variant_found = await campaign_id_of(
                    session, shop_id, str(t.get("campaign_key") or scope.get("campaign_key") or "")
                )
                cid, variant = cid_found or "", variant or variant_found or ""
            if not re.fullmatch(r"\d{1,20}", cid):
                job({"campaign_key": scope.get("campaign_key")}, f"ads:{scope.get('campaign_key')}",
                    {}, "campaign_unknown")  # fmt: skip
                continue
            payload, error = _ads_payload(
                change_kind, {**base_inputs, **(t.get("inputs") or {})}, cid,
                variant if variant in ("manual", "manual-mpd") else "manual",
            )  # fmt: skip
            job({"campaign_id": cid}, f"ads:{change_kind}:{cid}", payload or {}, error)
    elif kind == "affiliate_commission":
        ids: list[str] = []
        for t in given:
            ids += _ids(t.get("product_ids") or [t.get("item_id")])
        ids = list(dict.fromkeys(ids or scope_items))[:MAX_PRODUCTS]
        pct = _num(base_inputs.get("commission_pct"))
        error = None if ids and pct is not None and 0 < pct <= 50 else "commission_incomplete"
        job(
            {"product_ids": ids},
            "affiliate:" + ",".join(ids)[:60],
            {
                "open_path": "/portal/web-seller-affiliate/open_campaign",
                "product_ids": ids,
                "commission_pct": pct,
            }
            if not error
            else {},
            error,
        )
    return jobs


async def _card_for(
    session: AsyncSession, shop_id: uuid.UUID, p: ShopProposal, version: int
) -> dict[str, Any] | None:
    card = await store.card_payload(session, shop_id, p.id)
    if card is None:
        return None
    vlist = versions.versions_of(card)
    if version != 1 and 1 <= version <= len(vlist):
        return versions.overlay(card, vlist[version - 1])
    return card


async def enqueue_for_approval(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    version: int,
    targets: list[dict[str, Any]] | None = None,
    group_code: str | None = None,
    card: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[ShopeeFillJob]:
    """Queue the fill jobs of one approved card version. Idempotent per (card, version, target).

    ``targets``: optional list of ``{item_id | product_ids | campaign_id | campaign_key,
    inputs?}`` (a card with many targets, D85.13); none = the card's own scope. ``card``: the
    final card when the caller already holds it (adjusted inputs). Returns the rows (new and
    existing). Does nothing unless ``CONNECTOR_FILL_LISTING`` is on."""
    if not enabled():
        return []
    p = await session.scalar(
        select(ShopProposal).where(ShopProposal.id == proposal_id, ShopProposal.shop_id == shop_id)
    )
    if p is None:
        raise ProposalError("reco_unknown_card", 404)
    final = card or await _card_for(session, shop_id, p, version)
    if final is None:
        raise ProposalError("reco_unknown_card", 404)
    when = now or datetime.now(UTC)
    specs = await build_jobs(session, shop_id, p, final, version, targets, when)
    existing = {
        j.target_key: j
        for j in await session.scalars(
            select(ShopeeFillJob).where(
                ShopeeFillJob.shop_id == shop_id,
                ShopeeFillJob.proposal_id == proposal_id,
                ShopeeFillJob.version == version,
            )
        )
    }
    base_seq = len(existing)
    out: list[ShopeeFillJob] = list(existing.values()) if not specs else []
    for n, s in enumerate(specs):
        row = existing.get(s["target_key"])
        if row is None:
            row = ShopeeFillJob(
                shop_id=shop_id,
                proposal_id=proposal_id,
                version=version,
                group_code=group_code,
                kind=s["kind"],
                target=s["target"],
                target_key=s["target_key"],
                seq=base_seq + n,
                payload=s["payload"],
                status=s["status"],
                error=s["error"],
                created_at=when.replace(tzinfo=None),
                updated_at=when.replace(tzinfo=None),
            )
            session.add(row)
        out.append(row)
    await session.flush()
    return out


async def enqueue_after_decision(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    picked: list[int],
    final_card: dict[str, Any],
    group_name: str | None,
    now: datetime,
) -> None:
    """The single hook ``service._decide`` calls after an approval: queue the first version from
    the card the person approved (adjusted inputs kept), the others of a group from the card.
    A queue failure never undoes the approval (logged; the card can still be filled by hand)."""
    if not enabled():
        return
    try:
        async with session.begin_nested():
            for n, version in enumerate(picked):
                await enqueue_for_approval(
                    session,
                    shop_id=shop_id,
                    proposal_id=proposal_id,
                    version=version,
                    group_code=group_name,
                    card=final_card if n == 0 else None,
                    now=now,
                )
    except Exception:  # noqa: BLE001 - the approval stands whatever the queue does
        logger.exception("fill_enqueue_failed", extra={"shop_id": str(shop_id)})


# ----------------------------------------------------------------------------- reading / reporting


def job_json(j: ShopeeFillJob, code: str | None = None, title: str | None = None) -> dict[str, Any]:
    return {
        "id": str(j.id),
        "card_id": str(j.proposal_id),
        "code": code,
        "title": title,
        "version": j.version,
        "group_code": j.group_code,
        "kind": j.kind,
        "target": j.target,
        "seq": j.seq,
        "status": j.status,
        "captured_ref": j.captured_ref,
        "error": j.error,
        "payload": j.payload,
        "open_path": (j.payload or {}).get("open_path"),
    }


async def resolve_voucher_captures(session: AsyncSession, shop_id: uuid.UUID) -> int:
    """Fallback capture (D85.6): the Connector's voucher list reader has posted the new voucher
    (``extra.voucher_code`` = Seller Centre's fixed prefix + our code suffix): its ``voucher_id``
    becomes the filled / saved job's ``captured_ref``. Nothing is typed by the person."""
    pending = (
        await session.scalars(
            select(ShopeeFillJob).where(
                ShopeeFillJob.shop_id == shop_id,
                ShopeeFillJob.kind == "voucher",
                ShopeeFillJob.status.in_((STATUS_FILLED, STATUS_SAVED)),
            )
        )
    ).all()
    if not pending:
        return 0
    rows = (
        await session.scalars(
            select(PlatformPromotion)
            .where(PlatformPromotion.shop_id == shop_id, PlatformPromotion.promo_type == "voucher")
            .order_by(PlatformPromotion.captured_at.desc())
            .limit(400)
        )
    ).all()
    by_suffix: dict[str, str] = {}
    for r in rows:
        extra = r.extra or {}
        vid, vcode = extra.get("voucher_id"), str(extra.get("voucher_code") or "").upper()
        if vid is not None and len(vcode) > len(VOUCHER_CODE_PREFIX):
            by_suffix.setdefault(vcode[len(VOUCHER_CODE_PREFIX) :], str(vid))
    done = 0
    for j in pending:
        found = by_suffix.get(str((j.payload or {}).get("code_suffix") or "").upper())
        if found and _REF.match(found):
            j.captured_ref, j.status = found, STATUS_CAPTURED
            j.updated_at = datetime.now(UTC).replace(tzinfo=None)
            done += 1
    if done:
        await session.flush()
    return done


async def jobs_for_shop(
    session: AsyncSession, shop_id: uuid.UUID, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Jobs the Connector may still work on, oldest approval first (the route checks the switch)."""
    await resolve_voucher_captures(session, shop_id)
    await resolve_voucher_captures(session, shop_id)
    rows = (
        await session.execute(
            select(ShopeeFillJob, ShopProposal.code, ShopProposal.subject_label)
            .join(ShopProposal, ShopProposal.id == ShopeeFillJob.proposal_id)
            .where(ShopeeFillJob.shop_id == shop_id, ShopeeFillJob.status.in_(OPEN_STATUSES))
            .order_by(ShopeeFillJob.created_at, ShopeeFillJob.seq)
            .limit(limit)
        )
    ).all()
    return [job_json(j, c, t) for j, c, t in rows]


async def jobs_of_card(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every job of a card (the Demo checklist), approval order."""
    await resolve_voucher_captures(session, shop_id)
    await resolve_voucher_captures(session, shop_id)
    rows = (
        await session.scalars(
            select(ShopeeFillJob)
            .where(ShopeeFillJob.shop_id == shop_id, ShopeeFillJob.proposal_id == proposal_id)
            .order_by(ShopeeFillJob.version, ShopeeFillJob.seq)
        )
    ).all()
    return [job_json(j) for j in rows]


async def report(
    session: AsyncSession,
    shop_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    status: str,
    captured_ref: str | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The Connector's progress on one job (own shop only)."""
    j = await session.scalar(
        select(ShopeeFillJob).where(ShopeeFillJob.id == job_id, ShopeeFillJob.shop_id == shop_id)
    )
    if j is None:
        raise ProposalError(ERROR_JOB_UNKNOWN, 404)
    if captured_ref is not None and not _REF.match(captured_ref):
        raise ProposalError(ERROR_JOB_BAD, 422)
    if status not in _NEXT.get(j.status, set()) and status != j.status:
        raise ProposalError(ERROR_JOB_STATE, 409, f"{j.status} -> {status}")
    j.status = status
    if captured_ref is not None:
        j.captured_ref = captured_ref
    if status == STATUS_FAILED:
        j.error = (error or "failed")[:64]
    j.updated_at = (now or datetime.now(UTC)).replace(tzinfo=None)
    await session.flush()
    return job_json(j)


async def cancel(session: AsyncSession, shop_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
    j = await session.scalar(
        select(ShopeeFillJob).where(ShopeeFillJob.id == job_id, ShopeeFillJob.shop_id == shop_id)
    )
    if j is None:
        raise ProposalError(ERROR_JOB_UNKNOWN, 404)
    if j.status in (STATUS_CAPTURED, STATUS_CANCELLED):
        raise ProposalError(ERROR_JOB_STATE, 409)
    j.status = STATUS_CANCELLED
    await session.flush()
    return job_json(j)


async def captured_ref_of(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID, kind: str
) -> str | None:
    """The id the Connector captured after the person saved (newest first), so read-back
    starts without the person typing it (``mark_executed`` falls back to this)."""
    return await session.scalar(
        select(ShopeeFillJob.captured_ref)
        .where(
            ShopeeFillJob.shop_id == shop_id,
            ShopeeFillJob.proposal_id == proposal_id,
            ShopeeFillJob.kind == kind,
            ShopeeFillJob.captured_ref.is_not(None),
        )
        .order_by(ShopeeFillJob.updated_at.desc())
        .limit(1)
    )
