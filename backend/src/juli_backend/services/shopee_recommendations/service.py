"""Recommendation use cases: generate + rank + persist, read, what-if, decide, execute.

Every function runs under the shop's tenant scope on the caller's session and never commits
(the route commits after its audit row). The approval cycle is ADR-118's (`shop_proposals`);
this module adds the card contents (frozen at `proposed`), the ranking and the journey events.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    ACTOR_JULI,
    ACTOR_SELLER,
    ACTOR_SYSTEM,
    DISMISS_REASON_CODES,
    EVENT_ACCEPTED,
    EVENT_DISMISSED,
    EVENT_EDITED,
    EVENT_EXECUTED,
    EVENT_EXPIRED,
    EVENT_WHATIF_ADJUSTED,
    CardEvent,
)
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_REJECTED,
    STATUS_SENT,
    STATUS_WITHDRAWN,
    ShopProposal,
)
from juli_backend.services.card_events import keys
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.critical import build_critical
from juli_backend.services.shopee_recommendations import config, store
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.generators import generate
from juli_backend.services.shopee_recommendations.kinds import KINDS, spec
from juli_backend.services.shopee_recommendations.learning import executed_change_days
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.mega import (
    MegaWindow,
    build_mega_card,
    candidate_of_card,
    children_from_card,
    fit_children,
    select_children,
    window_from_card,
)
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.ranking import (
    Gaps,
    RankInput,
    RankResult,
    month_days_of,
    month_gaps,
    rank,
)

ERROR_NO_DATA = "reco_no_data"
ERROR_UNKNOWN_CARD = "reco_card_not_found"
ERROR_BAD_INPUT = "reco_invalid"
SELLER_HIDDEN = (STATUS_DRAFT, STATUS_WITHDRAWN, "superseded")


def _naive(now: datetime) -> datetime:
    return now.replace(tzinfo=None) if now.tzinfo else now


def short_id(value: str | uuid.UUID) -> str:
    """A stable short hash for printing a product id without naming it."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:8]


# ----------------------------------------------------------------------------- inputs


def _rank_input(card_id: str, card: dict[str, Any], env: RecoEnv) -> RankInput:
    ri = card["rank_inputs"]
    acc = env.acceptance.rate(card["change_kind"]) if env.acceptance else None
    return RankInput(
        id=card_id,
        kind=card["change_kind"],
        family=card["family"],
        items=tuple(card["scope"]["product_ids"]),
        floor_breach=ri["floor_breach"],
        dprofit_p50=ri["dprofit_p50"],
        spend_after=ri["spend_after"],
        spend_cap=ri["spend_cap"],
        in_stock=ri["in_stock"],
        kpi_p25=ri["kpi_p25"],
        dgmv_p25=ri["dgmv_p25"],
        acceptance=acc,
        kg_value=ri.get("kg_value"),
    )


def gaps_of(env: RecoEnv) -> Gaps:
    view = env.view
    t = env.rules
    margin = view.profit.margin_pct
    return month_gaps(
        targets={
            k: (None if t.target(k) is None else float(t.target(k)))
            for k in ("gmv_month", "orders_month", "aov_month", "margin_pct")
        },  # type: ignore[arg-type]
        gmv_30d=float(env.shop_gmv_30d),
        orders_30d=float(env.shop_orders_30d),
        margin_pct=None if margin is None else float(margin),
        window_days=env.window_days,
        month_days=month_days_of(env.as_of.year, env.as_of.month),
    )


def apply_acceptance_defaults(env: RecoEnv, cand: Candidate) -> None:
    """Move numeric slider defaults toward what approved cards ended with (>= 3 adjustments);
    reverted when the moved inputs break a floor. Never touches an effect estimate."""
    if env.acceptance is None:
        return
    from juli_backend.services.shopee_recommendations.evaluate import evaluate

    moved: dict[str, float] = {}
    original = dict(cand.inputs)
    for sl in spec(cand.kind).sliders:
        base = cand.inputs.get(sl.key)
        if not isinstance(base, int | float) or isinstance(base, bool):
            continue
        new = env.acceptance.default_for(cand.kind, sl.key, float(base), sl.minimum, sl.maximum)
        if new != base:
            step = sl.step or 1
            new = round(new / step) * step
            cand.inputs[sl.key] = int(new) if float(new).is_integer() else new
            moved[sl.key] = new
    if moved:
        ev = evaluate(env, cand)
        if ev.refusal or ev.breaches:
            cand.inputs.clear()
            cand.inputs.update(original)
        else:
            cand.extra["default_source"] = dict.fromkeys(moved, "acceptance")


# --------------------------------------------------------------------------- generate


@dataclass
class GenerationReport:
    as_of: date
    generated: int = 0
    persisted: int = 0
    by_family: Counter[str] = field(default_factory=Counter)
    by_kind: Counter[str] = field(default_factory=Counter)
    rank: RankResult | None = None
    mega: dict[str, Any] | None = None
    top: list[dict[str, Any]] = field(default_factory=list)
    card_ids: list[str] = field(default_factory=list)
    skipped_refusals: Counter[str] = field(default_factory=Counter)

    def json(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "generated": self.generated,
            "persisted": self.persisted,
            "by_family": dict(self.by_family),
            "by_kind": dict(self.by_kind),
            "ranking": None if self.rank is None else self.rank.json(),
            "top": self.top,
            "mega": self.mega,
            "refusals": dict(self.skipped_refusals),
        }


async def executed_days(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> frozenset[date]:
    """Days a verified change was running (from its verified time for the card's plan, 14 days
    when it has none): the flow baseline leaves them out so it does not learn them as normal."""
    rows = (
        await session.execute(
            select(CardEvent.card_id, CardEvent.occurred_at).where(
                CardEvent.shop_id == shop_id,
                CardEvent.event_type == "verified",
                CardEvent.card_id.is_not(None),
            )
        )
    ).all()
    changes: list[tuple[datetime, int]] = []
    plan_days: dict[uuid.UUID, int] = {}
    for r in rows:
        if r.card_id not in plan_days:
            meta = await store.card_meta(session, shop_id, r.card_id)
            plan_days[r.card_id] = int(meta.get("plan_days") or 14)
        changes.append((_naive(r.occurred_at), plan_days[r.card_id]))
    return executed_change_days(changes, first, last)


async def build_candidates(
    session: AsyncSession, shop_id: uuid.UUID, env: RecoEnv
) -> tuple[list[Candidate], dict[str, Any]]:
    window = env.view.window
    series = await loaders.load_flow_series(session, shop_id, window.end)
    skip = await executed_days(session, shop_id, window.end - timedelta(days=399), window.end)
    if skip:
        series = {k: {d: v for d, v in s.items() if d not in skip} for k, s in series.items()}
    critical = build_critical(env.ctx, env.view, series)
    cands = generate(env, critical)
    for c in cands:
        apply_acceptance_defaults(env, c)
    return cands, critical


async def generate_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    as_of: date | None = None,
    cycle: str | None = None,
    top_n: int = config.DEFAULT_TOP_N,
    explore_slot: bool = False,
    mega_window: MegaWindow | None = None,
    mega_budget_cap: Decimal | None = None,
    persist: bool = True,
    max_cards: int = 40,
    staff_id: uuid.UUID | None = None,
    env: RecoEnv | None = None,
) -> GenerationReport:
    """Generate, rank and (optionally) persist the shop's cards as ``draft`` proposals."""
    now = _naive(now)
    env = env or await load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise ProposalError(ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    cands, _critical = await build_candidates(session, shop_id, env)
    report = GenerationReport(as_of=env.as_of)
    built: list[tuple[Candidate, dict[str, Any]]] = []
    for c in cands:
        card = build_card(env, c, now=now)
        if card is None:
            report.skipped_refusals[c.kind] += 1
            continue
        built.append((c, card))
    report.generated = len(built)
    cards_by_id = {f"c{i}": (c, card) for i, (c, card) in enumerate(built)}
    gaps = gaps_of(env)
    inputs = [_rank_input(cid, card, env) for cid, (_, card) in cards_by_id.items()]
    result = rank(inputs, gaps, locked=env.locked, top_n=top_n, explore_slot=explore_slot)
    kept = [r.id for r in result.ordered]
    mega_card: dict[str, Any] | None = None
    consumed: set[str] = set()
    if mega_window is not None:
        pool = [cards_by_id[i][1] for i in kept]
        chosen = select_children(pool)
        ids = [i for i in kept if cards_by_id[i][1] in chosen]
        children = [cards_by_id[i][0] for i in ids]
        cap = mega_budget_cap if mega_budget_cap is not None else env.daily_cap
        children, removed = fit_children(env, children, mega_window, cap)
        ids = [i for i in ids if any(cards_by_id[i][0] is c for c in children)]
        mega_card = build_mega_card(
            env,
            children,
            mega_window,
            now=now,
            budget_cap_per_day=cap,
            child_ids=[f"child-{n + 1}" for n in range(len(children))],
        )
        if mega_card is not None:
            consumed = set(ids)
            mega_input = _rank_input("mega", mega_card, env)
            mega_input.mega_children_items = tuple(mega_card["locked_items"])
            rest = [i for i in inputs if i.id not in consumed]
            result = rank(
                [*rest, mega_input], gaps, locked=env.locked, top_n=top_n, explore_slot=explore_slot
            )
            cards_by_id["mega"] = (children[0], mega_card)
            report.mega = {
                "children": len(ids),
                "kinds": [c.kind for c in children],
                "window": mega_window.json(),
                "consumed_cards": len(consumed),
                "dropped_to_fit": removed,
            }
    report.rank = result
    ranked = {r.id: r for r in result.ordered}
    if report.mega is not None:
        report.mega["ranked"] = "mega" in ranked
    cycle_name = cycle or f"{env.as_of:%Y-%m}"
    kept_all = result.ordered[:max_cards]
    for r in kept_all:
        _, card = cards_by_id[r.id]
        card["rank"] = {
            "position": r.position,
            "score": r.score,
            "detail": r.detail,
            "mode": result.mode,
            "explore": r.explore,
        }
        report.by_family[card["family"]] += 1
        report.by_kind[card["change_kind"]] += 1
        if persist:
            cid = await store.save_card(
                session,
                shop_id,
                card,
                cycle=cycle_name,
                position=r.position,
                now=now,
                staff_id=staff_id,
            )
            report.card_ids.append(str(cid))
            report.persisted += 1
    for r in result.ordered[:5]:
        _, card = cards_by_id[r.id]
        report.top.append(
            {
                "position": r.position,
                "ref": short_id(card["scope"]["product_ids"][0])
                if card["scope"]["product_ids"]
                else short_id(r.id),
                "family": card["family"],
                "kind": card["change_kind"],
                "score": round(r.score, 6),
                "mode": result.mode,
                "dgmv_p25": round(card["rank_inputs"]["dgmv_p25"]),
                "plan": card["measurement_plan"]["label"],
            }
        )
    return report


# ------------------------------------------------------------------------------- read


def _summary(
    p: ShopProposal, card: dict[str, Any], meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    pm = card["predicted"]["money_per_month"]
    return {
        "id": str(p.id),
        "status": p.status,
        "cycle": p.cycle,
        "family": card["family"],
        "family_label": card["family_label"],
        "change_kind": card["change_kind"],
        "title": card["title"],
        "reason": card["reason"],
        "section": card.get("wiring_key"),
        "metric": card["metric"],
        "scope": card["scope"],
        "rank": card.get("rank"),
        "certain_summary": {
            "dprofit_month": pm["certain"]["dprofit"],
            "dgmv_month": pm["certain"]["dgmv"],
        },
        "predicted_summary": {
            "dgmv_month": {q: pm["predicted"][q]["dgmv"] for q in ("p10", "p50", "p90")},
            "dprofit_month": {q: pm["total"][q]["dprofit"] for q in ("p10", "p50", "p90")},
            "label": "Dự kiến",
            "effect_days": pm["days"],
        },
        "floor_ok": card["floor"]["ok"],
        "plan": card["measurement_plan"]["label"],
        "stale": bool((meta or {}).get("stale")),
        "bundle": card.get("bundle", False),
        "sent_at": None if p.sent_at is None else p.sent_at.isoformat() + "Z",
    }


XEP_THEO = ("diem", "gmv_per_day", "profit_per_day", "bien", "orders", "aov")


def _xep_key(card: dict[str, Any], xep_theo: str) -> float:
    pm = card["predicted"]["money_per_month"]["total"]["p50"]
    days = card["predicted"]["money_per_month"]["days"] or 30
    five = card.get("five_numbers") or {}
    if xep_theo == "gmv_per_day":
        return -(pm["dgmv"] / days)
    if xep_theo == "profit_per_day":
        return -((pm["dprofit"] or 0.0) / days)
    if xep_theo == "bien":
        return -(card["rank_inputs"]["kpi_p25"].get("bien", 0.0))
    if xep_theo == "orders":
        return -(pm["dorders"] or 0.0)
    if xep_theo == "aov":
        return -(card["rank_inputs"]["kpi_p25"].get("aov", 0.0))
    del five
    return float((card.get("rank") or {}).get("position", 10**6))


async def list_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    audience: str,
    family: str | None = None,
    section: str | None = None,
    status: str | None = None,
    xep_theo: str = "diem",
) -> dict[str, Any]:
    if xep_theo not in XEP_THEO:
        raise ProposalError(ERROR_BAD_INPUT, 422, f"xep_theo must be one of {list(XEP_THEO)}")
    rows = await store.list_cards(session, shop_id)
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for p, card in rows:
        if audience == "seller" and p.status in SELLER_HIDDEN:
            continue
        if family and card["family"] != family:
            continue
        if section and card.get("wiring_key") != section:
            continue
        if status and p.status != status:
            continue
        meta = await store.card_meta(session, shop_id, p.id)
        out.append((_summary(p, card, meta), card))
    out.sort(key=lambda t: (_xep_key(t[1], xep_theo), t[0]["id"]))
    summaries = [s for s, _ in out]
    groups: dict[str, int] = Counter(s["family"] for s in summaries)
    sections: dict[str, int] = Counter(s["section"] or "-" for s in summaries)
    return {
        "platform": "shopee",
        "xep_theo": xep_theo,
        "cards": summaries,
        "counts": {"family": dict(groups), "section": dict(sections), "total": len(summaries)},
    }


async def _proposal(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> tuple[ShopProposal, dict[str, Any]]:
    p = await session.scalar(
        select(ShopProposal).where(ShopProposal.id == card_id, ShopProposal.shop_id == shop_id)
    )
    card = await store.card_payload(session, shop_id, card_id) if p is not None else None
    if p is None or card is None:
        raise ProposalError(ERROR_UNKNOWN_CARD, 404)
    return p, card


async def card_detail(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, *, audience: str
) -> dict[str, Any]:
    p, card = await _proposal(session, shop_id, card_id)
    if audience == "seller" and p.status in SELLER_HIDDEN:
        raise ProposalError(ERROR_UNKNOWN_CARD, 404)
    meta = await store.card_meta(session, shop_id, card_id)
    events = (
        await session.execute(
            select(CardEvent.event_type, CardEvent.occurred_at, CardEvent.reason_code)
            .where(CardEvent.shop_id == shop_id, CardEvent.card_id == card_id)
            .order_by(CardEvent.occurred_at)
        )
    ).all()
    out = {
        **_summary(p, card, meta),
        "card": card,
        "journey": [
            {"event": e.event_type, "at": e.occurred_at.isoformat(), "reason_code": e.reason_code}
            for e in events
        ],
    }
    final = await _final_override(session, shop_id, card_id)
    if final is not None:
        out["approved_with"] = {"inputs": final["inputs"]}
    return out


# ----------------------------------------------------------------------------- what-if


def _merge_inputs(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for k, v in new.items():
        merged[k] = v
    return merged


async def recompute(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    inputs: dict[str, Any],
    *,
    now: datetime,
    record: bool = True,
    actor: str = ACTOR_SELLER,
) -> dict[str, Any]:
    """Recompute the whole card with other inputs (every input change recomputes everything,
    contract 7) on the SAME history window the card was proposed on; records `whatif_adjusted`."""
    now = _naive(now)
    p, card = await _proposal(session, shop_id, card_id)
    if p.status in (STATUS_EXECUTED, STATUS_WITHDRAWN, "superseded"):
        raise ProposalError("reco_card_closed", 409, f"a {p.status} card can no longer be adjusted")
    as_of = date.fromisoformat(card["as_of"])
    env = await load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise ProposalError(ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    new_card = recompute_card(env, card, inputs, now=now)
    if new_card is None:
        raise ProposalError(ERROR_BAD_INPUT, 422, "these inputs cannot be evaluated")
    if record:
        subject = (
            ("item", card["scope"]["product_ids"][0])
            if card["scope"]["product_ids"]
            else ("shop", "")
        )
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_WHATIF_ADJUSTED,
            actor=actor,
            occurred_at=now,
            dedup_key=f"whatif:{card_id}:{uuid.uuid4()}",
            payload={
                "inputs": inputs,
                "before_inputs": card["inputs"],
                "dprofit_month_p50": new_card["rank_inputs"]["dprofit_p50"],
                "floor_ok": new_card["floor"]["ok"],
            },
            family=card["family"],
            change_kind=card["change_kind"],
            subject=subject,
        )
    return new_card


def recompute_card(
    env: RecoEnv, card: dict[str, Any], inputs: dict[str, Any], *, now: datetime
) -> dict[str, Any] | None:
    if card["family"] == "mega_sale":
        return _recompute_mega(env, card, inputs, now)
    cand = candidate_of_card(card)
    cand.inputs = _merge_inputs(cand.inputs, inputs)
    out = build_card(env, cand, now=now)
    if out is not None:
        out["id"] = card["id"]
        out["rank"] = card.get("rank")
        out["metric"] = card["metric"]
        out["wiring"] = card["wiring"]
    return out


def _recompute_mega(
    env: RecoEnv, card: dict[str, Any], inputs: dict[str, Any], now: datetime
) -> dict[str, Any] | None:
    children = children_from_card(card)
    ids = [c["child_id"] for c in card["children"]]
    sources = [c.get("source_card_id") for c in card["children"]]
    remove = set(inputs.get("remove", []))
    edits = inputs.get("children", {})
    keep = [(c, i, s) for c, i, s in zip(children, ids, sources, strict=True) if i not in remove]
    for c, i, _ in keep:
        if i in edits:
            c.inputs = _merge_inputs(c.inputs, edits[i])
    cap = inputs.get("budget_cap_per_day", card["inputs"].get("budget_cap_per_day"))
    out = build_mega_card(
        env,
        [c for c, _, _ in keep],
        window_from_card(card),
        now=now,
        budget_cap_per_day=None if cap is None else Decimal(str(cap)),
        child_ids=[i for _, i, _ in keep],
        source_card_ids=[s for _, _, s in keep],
    )
    if out is not None:
        out["id"] = card["id"]
        out["rank"] = card.get("rank")
    return out


# ---------------------------------------------------------------------------- publish


async def publish(
    session: AsyncSession, shop_id: uuid.UUID, card_ids: list[uuid.UUID] | None, *, now: datetime
) -> list[str]:
    """Ops sends draft cards to the client (`draft` -> `sent`); None = every draft."""
    now = _naive(now)
    out: list[str] = []
    rows = await store.list_cards(session, shop_id, statuses=[STATUS_DRAFT])
    for p, _ in rows:
        if card_ids is not None and p.id not in card_ids:
            continue
        await proposals.send(session, p, now=now)
        out.append(str(p.id))
    return out


async def withdraw(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, *, now: datetime
) -> None:
    p, _ = await _proposal(session, shop_id, card_id)
    await proposals.withdraw(session, p, now=_naive(now))


# ---------------------------------------------------------------------------- decide


def _subject_of(card: dict[str, Any], card_id: uuid.UUID) -> tuple[str, str]:
    items = card["scope"]["product_ids"]
    return ("item", str(items[0])) if items else ("shop", str(card_id))


def _final_vs_default(card: dict[str, Any], final: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in (final or {}).items():
        base = card["inputs"].get(k)
        if (
            isinstance(v, int | float)
            and isinstance(base, int | float)
            and not isinstance(v, bool)
            and base
        ):
            out[k] = float(v) / float(base)
    return out


async def decide(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    decision: str,
    user_id: uuid.UUID,
    now: datetime,
    inputs: dict[str, Any] | None = None,
    reason_code: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """The client's decision in the app: ``approve`` (optionally with adjusted what-if inputs),
    ``request_change`` or ``dismiss`` (ADR-107 reason, optional)."""
    now = _naive(now)
    p, card = await _proposal(session, shop_id, card_id)
    subject = _subject_of(card, card_id)
    if decision == "approve":
        final_card = card
        if inputs:
            final_card = (
                await recompute(session, shop_id, card_id, inputs, now=now, record=False) or card
            )
            if not final_card["floor"]["ok"]:
                raise ProposalError(
                    "reco_floor_breach", 422, "inputs put a SKU under its floor price"
                )
        approval = await proposals.record_approval(
            session,
            p,
            decision=STATUS_APPROVED,
            channel="in_app",
            decided_at=now,
            now=now,
            decided_by_user_id=user_id,
            note=note,
        )
        final = {
            "inputs": final_card["inputs"],
            "execution_sheet": final_card["execution_sheet"],
            "change": final_card["change"],
        }
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_ACCEPTED,
            actor=ACTOR_SELLER,
            occurred_at=now,
            dedup_key=keys.accepted(approval.id),
            payload={
                "approval_id": str(approval.id),
                "final": final if inputs else None,
                "final_vs_default": _final_vs_default(card, inputs or {}),
            },
            family=card["family"],
            change_kind=card["change_kind"],
            subject=subject,
        )
        await store.set_meta(session, shop_id, card_id, {"approved_at": now.isoformat()})
        return {"id": str(card_id), "status": p.status, "approval_id": str(approval.id)}
    if decision == "request_change":
        approval = await proposals.record_approval(
            session,
            p,
            decision=STATUS_CHANGES_REQUESTED,
            channel="in_app",
            decided_at=now,
            now=now,
            decided_by_user_id=user_id,
            note=note,
        )
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_EDITED,
            actor=ACTOR_SELLER,
            occurred_at=now,
            dedup_key=f"edited:{approval.id}",
            payload={"request": note or "", "approval_id": str(approval.id)},
            family=card["family"],
            change_kind=card["change_kind"],
            subject=subject,
        )
        return {"id": str(card_id), "status": p.status, "approval_id": str(approval.id)}
    if decision == "dismiss":
        code = reason_code or "unspecified"
        if code not in DISMISS_REASON_CODES:
            raise ProposalError(
                ERROR_BAD_INPUT, 422, f"reason_code must be one of {list(DISMISS_REASON_CODES)}"
            )
        approval = await proposals.record_approval(
            session,
            p,
            decision=STATUS_REJECTED,
            channel="in_app",
            decided_at=now,
            now=now,
            decided_by_user_id=user_id,
            note=note or code,
        )
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_DISMISSED,
            actor=ACTOR_SELLER,
            occurred_at=now,
            dedup_key=keys.dismissed(card_id),
            payload={"approval_id": str(approval.id)},
            family=card["family"],
            change_kind=card["change_kind"],
            subject=subject,
            reason_code=code,
        )
        return {
            "id": str(card_id),
            "status": p.status,
            "approval_id": str(approval.id),
            "reason_code": code,
        }
    raise ProposalError(ERROR_BAD_INPUT, 422, "decision must be approve, request_change or dismiss")


async def expire_old(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, days: int = 7
) -> int:
    """A card sent more than ``days`` ago with no decision gets an `expired` event (ADR-107 4)."""
    now = _naive(now)
    n = 0
    for p, card in await store.list_cards(session, shop_id, statuses=[STATUS_SENT]):
        if p.sent_at is not None and now - p.sent_at >= timedelta(days=days):
            ok = await store.write_event(
                session,
                shop_id,
                p.id,
                event_type=EVENT_EXPIRED,
                actor=ACTOR_SYSTEM,
                occurred_at=now,
                dedup_key=keys.expired(p.id),
                payload={"sent_at": p.sent_at.isoformat()},
                family=card["family"],
                change_kind=card["change_kind"],
                subject=_subject_of(card, p.id),
            )
            n += int(ok)
    return n


# --------------------------------------------------------------------------- executed


async def _final_override(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> dict[str, Any] | None:
    ev = await session.scalar(
        select(CardEvent)
        .where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id == card_id,
            CardEvent.event_type == EVENT_ACCEPTED,
        )
        .order_by(CardEvent.occurred_at.desc())
    )
    final = (ev.payload or {}).get("final") if ev else None
    return final


async def mark_executed(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    now: datetime,
    executed_at: datetime | None = None,
    user_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    voucher_id: str | None = None,
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    """ "Đã làm": a person saved the change in Seller Centre. Records the execution
    (ADR-118) and one `executed` event per change in the sheet, each carrying
    ``change = {change_kind, target, expected}`` for the Connector's read-back."""
    now = _naive(now)
    when = _naive(executed_at) if executed_at else now
    p, card = await _proposal(session, shop_id, card_id)
    if p.status != STATUS_APPROVED:
        raise ProposalError("proposal_bad_state", 409, f"a {p.status} card cannot be marked done")
    final = await _final_override(session, shop_id, card_id)
    sheet = (final or {}).get("execution_sheet") or card["execution_sheet"]
    changes = [dict(c) for c in sheet["changes"]]
    for c in changes:
        if c["change_kind"] == "voucher":
            if not voucher_id:
                raise ProposalError(
                    ERROR_BAD_INPUT, 422, "voucher_id is required to verify a voucher"
                )
            c["target"] = {**c["target"], "voucher_id": voucher_id}
    role = "client_representative" if user_id is not None else "juli_operator"
    execution = await proposals.record_execution(
        session,
        p,
        executed_at=when,
        executor_role=role,
        channel="in_app" if user_id else "ops",
        now=now,
        executed_by_user_id=user_id,
        recorded_by_user_id=user_id,
        recorded_by_staff_id=staff_id,
        evidence_ref=evidence_ref,
    )
    subject = _subject_of(card, card_id)
    for n, change in enumerate(changes):
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_EXECUTED,
            actor=ACTOR_SELLER if user_id else ACTOR_SYSTEM,
            occurred_at=when,
            dedup_key=f"assisted:{card_id}:{execution.id}:{n}",
            payload={
                "change": change,
                "execution_id": str(execution.id),
                "executor_role": role,
                "bundle": card.get("bundle", False),
            },
            family=card["family"],
            change_kind=card["change_kind"],
            subject=subject,
        )
    await store.set_meta(session, shop_id, card_id, {"executed_at": when.isoformat()})
    return {
        "id": str(card_id),
        "status": p.status,
        "execution_id": str(execution.id),
        "events": len(changes),
    }


async def learning_overview(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    from juli_backend.services.shopee_recommendations import learning

    states = await store.load_calibrations(session, shop_id)
    acceptance = await store.load_acceptance(session, shop_id)
    sim = await store.load_sim(session, shop_id)
    return {
        "calibration": learning.coverage_report(states),
        "acceptance": acceptance.json(),
        "sim": None if sim is None else sim.summary(),
        "note": "Chấp nhận / bỏ qua chỉ đổi giá trị mặc định và thứ tự xếp hạng, không phải bằng chứng hiệu quả.",  # noqa: E501
    }


async def sim_summary(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    sim = await store.load_sim(session, shop_id)
    return {"active": None if sim is None else sim.summary()}


__all__ = [
    "learning_overview",
    "sim_summary",
    "KINDS",
    "ACTOR_JULI",
    "GenerationReport",
    "build_candidates",
    "card_detail",
    "decide",
    "expire_old",
    "generate_cards",
    "list_cards",
    "mark_executed",
    "publish",
    "recompute",
    "short_id",
    "withdraw",
]
