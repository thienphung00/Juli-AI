"""Thực hiện / Đo lường of Quyết định: where each approved card stands (P100 redesign round).

Nothing new is stored. The state of an approved card is derived from what the Connector and the
read-back already write:

- ``cho_dien``  approved, no fill job has been filled;
- ``da_dien``   the Connector filled the page (``shopee_fill_jobs`` ``filled`` / ``saved``) or the
                person marked "Đã làm"; waiting for the person's save / the Connector's read-back;
- ``khop``      a ``verified`` event: Seller Centre shows the card's values (the measurement clock
                starts then);
- ``lech``      a ``mismatch`` event: Seller Centre was read after the save and shows another value.

Progress is per fill job (a page of the card), not per field: the Connector reports a job status,
never "3 of 4 fields". ``derive_state`` and ``measurement_row`` are pure; the ``*_states`` functions
read the rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    EVENT_EXECUTED,
    EVENT_IMPACT_FINAL,
    EVENT_IMPACT_PRELIMINARY,
    EVENT_MISMATCH,
    EVENT_NOT_SEEN,
    EVENT_VERIFIED,
    CardEvent,
)
from juli_backend.models.shop_proposals import STATUS_APPROVED, STATUS_EXECUTED
from juli_backend.models.shopee_fill import (
    STATUS_CANCELLED,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services.card_events import verification
from juli_backend.services.ingest import status as ingest_status
from juli_backend.services.shopee_recommendations import connector_state, service, store

STATE_WAITING = "cho_dien"
STATE_FILLED = "da_dien"
STATE_MATCH = "khop"
STATE_MISMATCH = "lech"

VERDICT_RUNNING = "dang_do"
VERDICT_BELOW = "duoi_khoang"
VERDICT_INSIDE = "trong_khoang"
VERDICT_ABOVE = "vuot_khoang"
VERDICT_NONE = "chua_ket_luan"

#: What one fill job of each kind is, for "3/4 <noun> đã điền".
NOUN: dict[str, str] = {
    "title": "tiêu đề",
    "description_first_line": "mô tả",
    "voucher": "voucher",
    "ads_edit": "chiến dịch",
    "affiliate_commission": "sản phẩm",
    "combo": "combo",
}
#: card metric key -> the shared MetricKey of the screens (None: no chip).
CHIP_METRIC: dict[str, str | None] = {
    "views": "views",
    "ctr": "ctr",
    "ctor": "ctor",
    "aov": "aov",
    "orders": "orders",
    "gmv": "gmv",
    "ads_gmv": "gmv",
    "roas": None,
    "none": None,
}
_CONNECTOR_FRESH = timedelta(hours=26)


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def _first_difference(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> dict[str, Any]:
    for name, want in expected.items():
        got = observed.get(name)
        if name not in observed or not verification.same_value(want, got):
            return {"field": name, "observed": got, "expected": want}
    return {"field": None, "observed": None, "expected": None}


def derive_state(
    jobs: Sequence[Mapping[str, Any]],
    events: Iterable[tuple[str, datetime, Mapping[str, Any] | None]],
) -> dict[str, Any]:
    """The Thực hiện state of one approved card.

    ``jobs``: ``{status, kind}`` of its fill jobs; ``events``: ``(event_type, occurred_at,
    payload)``    of ``executed`` / ``verified`` / ``mismatch`` / ``not_seen``, any order.
    """
    live = [j for j in jobs if j["status"] != STATUS_CANCELLED]
    total = len(live)
    filled = sum(1 for j in live if j["status"] in (STATUS_FILLED, STATUS_SAVED, STATUS_CAPTURED))
    saved = sum(1 for j in live if j["status"] in (STATUS_SAVED, STATUS_CAPTURED))
    failed = sum(1 for j in live if j["status"] == STATUS_FAILED)
    fields = {"filled": 0, "total": 0}
    for j in live:
        prog = j.get("progress")
        if prog:
            fields["filled"] += min(prog["filled"], prog["total"])
            fields["total"] += prog["total"]
        else:
            fields["filled"] += (
                1 if j["status"] in (STATUS_FILLED, STATUS_SAVED, STATUS_CAPTURED) else 0
            )
            fields["total"] += 1
    ordered = sorted(
        (
            e
            for e in events
            if e[0] in (EVENT_EXECUTED, EVENT_VERIFIED, EVENT_MISMATCH, EVENT_NOT_SEEN)
        ),
        key=lambda e: _naive(e[1]),
    )
    executed = [e for e in ordered if e[0] == EVENT_EXECUTED]
    last_exec = executed[-1] if executed else None
    outcome = next(
        (
            e
            for e in reversed(ordered)
            if e[0] != EVENT_EXECUTED
            and last_exec is not None
            and _naive(e[1]) >= _naive(last_exec[1])
        ),
        None,
    )
    kinds = {j["kind"] for j in live}
    out: dict[str, Any] = {
        "jobs": {"total": total, "filled": filled, "saved": saved, "failed": failed},
        "fields": fields,
        "noun": NOUN.get(next(iter(kinds)), "mục") if len(kinds) == 1 else "mục",
        "executed_at": None if last_exec is None else _naive(last_exec[1]).isoformat() + "Z",
        "verified_at": None,
        "mismatch": None,
        "not_seen": False,
        "bad": None,
    }
    if outcome is not None and outcome[0] == EVENT_VERIFIED:
        out.update(state=STATE_MATCH, completed=4)
        payload = outcome[2] or {}
        at = payload.get("observed_at")
        out["verified_at"] = at if isinstance(at, str) else _naive(outcome[1]).isoformat() + "Z"
    elif outcome is not None and outcome[0] == EVENT_MISMATCH:
        payload = outcome[2] or {}
        out.update(
            state=STATE_MISMATCH,
            completed=3,
            bad=3,
            mismatch=_first_difference(
                payload.get("expected") or {}, payload.get("observed") or {}
            ),
        )
    elif last_exec is not None or saved:
        out.update(
            state=STATE_FILLED, completed=3, not_seen=bool(outcome and outcome[0] == EVENT_NOT_SEEN)
        )
    elif filled or fields["filled"]:
        out.update(state=STATE_FILLED, completed=2)
    else:
        out.update(state=STATE_WAITING, completed=1)
    return out


def verdict_of(impact_pct: float | None, p10: float | None, p90: float | None) -> str:
    if impact_pct is None or p10 is None or p90 is None:
        return VERDICT_NONE
    lo, hi = min(p10, p90), max(p10, p90)
    if impact_pct < lo:
        return VERDICT_BELOW
    if impact_pct > hi:
        return VERDICT_ABOVE
    return VERDICT_INSIDE


def measurement_row(
    card: Mapping[str, Any],
    *,
    started: datetime,
    today: date,
    window_days: int | None,
    window_closed: bool,
    reading: Mapping[str, Any] | None,
    final: bool,
) -> dict[str, Any]:
    """One Đo lường row: days measured, the card's Δ lợi nhuận band over the period against the
    reading, and the verdict. ``reading`` is the newest ``impact_*`` payload (``impact_pct`` is a
    fraction); the actual in đồng is the card's p50 profit scaled by how far the reading is from
    the predicted lift p50 (the card holds no measured profit)."""
    days = window_days or (card.get("measurement_plan") or {}).get("planned_days")
    start = started.date()
    measured = max(0, (today - start).days)
    if days:
        measured = min(measured, int(days))
    pm = card["predicted"]["money_per_month"]
    period = (int(days) / pm["days"]) if days and pm.get("days") else None

    def scaled(q: str) -> float | None:
        v = pm["total"][q]["dprofit"]
        return None if v is None or period is None else float(v) * period

    lift = ((card.get("predicted") or {}).get("lift") or {}).get("lift") or {}
    impact = None if reading is None else reading.get("impact_pct")
    p50, lift50 = scaled("p50"), lift.get("p50")
    actual = None
    if impact is not None and p50 is not None and lift50:
        actual = p50 * float(impact) / float(lift50)
    done = final or window_closed
    verdict = verdict_of(impact, lift.get("p10"), lift.get("p90")) if final else VERDICT_RUNNING
    if done and not final:
        verdict = VERDICT_NONE
    chip = CHIP_METRIC.get((card.get("metric") or {}).get("key") or "none")
    return {
        "started": start.isoformat(),
        "ends": None if not days else (start + timedelta(days=int(days))).isoformat(),
        "days": None if not days else int(days),
        "days_measured": measured,
        "done": done,
        "verdict": verdict,
        "impact_pct": impact,
        "lift": {q: lift.get(q) for q in ("p10", "p50", "p90")},
        "band": {"p10": scaled("p10"), "p50": p50, "p90": scaled("p90")},
        "actual": actual,
        "metrics": []
        if chip is None or impact is None
        else [{"metric": chip, "change_pct": impact}],
        "partial": bool(reading and reading.get("partial")),
    }


# ------------------------------------------------------------------------------------ reading


async def _events_by_card(
    session: AsyncSession, shop_id: uuid.UUID, card_ids: Sequence[uuid.UUID], types: Sequence[str]
) -> dict[uuid.UUID, list[CardEvent]]:
    out: dict[uuid.UUID, list[CardEvent]] = {}
    if not card_ids:
        return out
    rows = await session.scalars(
        select(CardEvent)
        .where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id.in_(list(card_ids)),
            CardEvent.event_type.in_(list(types)),
        )
        .order_by(CardEvent.occurred_at)
    )
    for e in rows:
        if e.card_id is not None:
            out.setdefault(e.card_id, []).append(e)
    return out


def _head(p: Any, card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "card_id": str(p.id),
        "code": p.code,
        "title": card["title"],
        "family": card["family"],
        "family_label": card["family_label"],
        "change_kind": card["change_kind"],
        "product_id": p.item_id,
        "status": p.status,
    }


async def connector_status(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, now: datetime
) -> dict[str, Any]:
    """The Connector line of the Thực hiện bar, from the dataset status the extension already feeds.
    ``seller_centre_open`` comes from the Connector's poll heartbeat (None when it is stale)."""
    rows = await ingest_status.dataset_status(session, shop_id=shop_id, platform=platform)
    seen = [r for r in rows if r.get("last_ingest_at")]
    last = max((r["last_ingest_at"] for r in seen), default=None)
    versions = [r["last_source_version"] for r in seen if r.get("last_source_version")]
    newest = None
    for v in versions:
        if newest is None or ingest_status.is_newer(v, newest):
            newest = v
    fresh = False
    if last:
        fresh = (
            now - _naive(datetime.fromisoformat(last.replace("Z", "+00:00"))) <= _CONNECTOR_FRESH
        )
    beat = await connector_state.read(session, shop_id, platform, now=now)
    return {
        "version": newest,
        "last_check_at": last,
        "connected": fresh or beat["alive"],
        "seller_centre_open": beat["seller_centre_open"],
        "reconcile_pending": beat["reconcile_pending"],
    }


async def execution_states(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, platform: str = "shopee"
) -> dict[str, Any]:
    """Thực hiện: every approved (and executed, not yet measured) card with its state."""
    rows = await store.list_cards(session, shop_id, statuses=[STATUS_APPROVED, STATUS_EXECUTED])
    ids = [p.id for p, _ in rows]
    measured = await service.measurement_states(session, shop_id, ids)
    events = await _events_by_card(
        session, shop_id, ids, (EVENT_EXECUTED, EVENT_VERIFIED, EVENT_MISMATCH, EVENT_NOT_SEEN)
    )
    jobs: dict[uuid.UUID, list[ShopeeFillJob]] = {}
    if ids:
        for j in await session.scalars(
            select(ShopeeFillJob)
            .where(ShopeeFillJob.shop_id == shop_id, ShopeeFillJob.proposal_id.in_(ids))
            .order_by(ShopeeFillJob.version, ShopeeFillJob.seq)
        ):
            jobs.setdefault(j.proposal_id, []).append(j)
    cards: list[dict[str, Any]] = []
    for p, card in rows:
        if (measured.get(str(p.id)) or {}).get("window_closed"):
            continue
        mine = jobs.get(p.id, [])
        latest = max((j.version for j in mine), default=None)
        mine = [j for j in mine if j.version == latest]
        state = derive_state(
            [
                {"status": j.status, "kind": j.kind, "progress": (j.payload or {}).get("progress")}
                for j in mine
            ],
            [(e.event_type, e.occurred_at, e.payload) for e in events.get(p.id, [])],
        )
        window = (measured.get(str(p.id)) or {}).get("window_days") or (
            card.get("measurement_plan") or {}
        ).get("planned_days")
        open_job = next(
            (
                j
                for j in mine
                if j.status not in (STATUS_CANCELLED, STATUS_CAPTURED)
                and (j.payload or {}).get("open_path")
            ),
            None,
        )
        cards.append(
            {
                **_head(p, card),
                **state,
                "measure_days": window,
                "measure_start": (state["verified_at"] or "")[:10] or None,
                "open_job": None
                if open_job is None
                else {"id": str(open_job.id), "open_path": open_job.payload["open_path"]},
            }
        )
    counts: dict[str, int] = {}
    for c in cards:
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    return {
        "platform": platform,
        "connector": await connector_status(session, shop_id, platform, now),
        "cards": cards,
        "counts": counts,
    }


async def measurement_states(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> dict[str, Any]:
    """Đo lường: every executed card whose clock has started (verified, or executed for kinds with
    no read-back), running or finished."""
    rows = await store.list_cards(session, shop_id, statuses=[STATUS_EXECUTED])
    ids = [p.id for p, _ in rows]
    meta = await service.measurement_states(session, shop_id, ids)
    events = await _events_by_card(
        session,
        shop_id,
        ids,
        (EVENT_EXECUTED, EVENT_VERIFIED, EVENT_IMPACT_PRELIMINARY, EVENT_IMPACT_FINAL),
    )
    cards: list[dict[str, Any]] = []
    for p, card in rows:
        ev = events.get(p.id, [])
        verified = [e for e in ev if e.event_type == EVENT_VERIFIED]
        executed = [e for e in ev if e.event_type == EVENT_EXECUTED]
        if verified:
            started = max(_naive(e.occurred_at) for e in verified)
        elif executed and not any(
            ((e.payload or {}).get("change") or {}).get("change_kind") in verification.CHANGE_KINDS
            for e in executed
        ):
            started = min(_naive(e.occurred_at) for e in executed)
        else:
            continue
        final = [e for e in ev if e.event_type == EVENT_IMPACT_FINAL]
        prelim = [e for e in ev if e.event_type == EVENT_IMPACT_PRELIMINARY]
        newest = (final or prelim)[-1] if (final or prelim) else None
        m = meta.get(str(p.id)) or {}
        cards.append(
            {
                **_head(p, card),
                **measurement_row(
                    card,
                    started=started,
                    today=now.date(),
                    window_days=m.get("window_days"),
                    window_closed=bool(m.get("window_closed")),
                    reading=None if newest is None else newest.payload,
                    final=bool(final),
                ),
                "label": m.get("label"),
            }
        )
    return {"platform": "shopee", "cards": cards}


__all__ = [
    "derive_state",
    "execution_states",
    "measurement_row",
    "measurement_states",
    "verdict_of",
]
