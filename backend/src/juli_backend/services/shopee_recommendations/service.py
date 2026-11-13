"""Recommendation use cases: generate + rank + persist, read, what-if, decide, execute.

Every function runs under the shop's tenant scope on the caller's session and never commits
(the route commits after its audit row). The approval cycle is ADR-118's (`shop_proposals`);
this module adds the card contents (frozen at `proposed`), the ranking and the journey events.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
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
    EVENT_IMPACT_FINAL,
    EVENT_IMPACT_PRELIMINARY,
    EVENT_MISMATCH,
    EVENT_NOT_SEEN,
    EVENT_VERIFIED,
    EVENT_WHATIF_ADJUSTED,
    CardEvent,
)
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_PLANNED,
    STATUS_REJECTED,
    STATUS_SENT,
    STATUS_WITHDRAWN,
    ShopProposal,
)
from juli_backend.models.shopee_plans import PLAN_DRAFT, ShopRecoPlan, ShopRecoPlanCard
from juli_backend.services.card_events import keys, verification
from juli_backend.services.shop_proposals import cycle as proposals
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.critical import build_critical
from juli_backend.services.shopee_recommendations import (
    change_sets,
    codes,
    combo,
    config,
    fill_queue,
    freshness,
    manual,
    plan_codes,
    product_queue,
    store,
    versions,
)
from juli_backend.services.shopee_recommendations import targets as multi
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
OPEN_STATUSES = product_queue.OPEN_STATUSES


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
    targets: dict[str, float | None] = {}
    for k in ("gmv_month", "orders_month", "aov_month", "margin_pct"):
        value = t.target(k)
        targets[k] = None if value is None else float(value)
    return month_gaps(
        targets=targets,
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
    max_cards: int | None = None,
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
        card["versions"] = versions.build_versions(env, c, card, now=now)
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
            mega_card["versions"] = [versions.version_of(mega_card, 1, versions.DEFAULT_LABEL)]
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
        dropped = next((d for d in result.dropped if d["id"] == "mega"), None)
        report.mega["dropped_by"] = None if dropped is None else dropped["reasons"]
    cycle_name = cycle or f"{env.as_of:%Y-%m}"
    kept_all = result.ordered if max_cards is None else result.ordered[:max_cards]
    if persist:
        await codes.backfill_codes(session, shop_id, now)  # cards that predate migration 116
    queued: set[str] = set()
    for r in kept_all:
        _, card = cards_by_id[r.id]
        card["rank"] = {
            "position": r.position,
            "score": r.score,
            "detail": r.detail,
            "mode": result.mode,
            "explore": r.explore,
        }
        card["product_queue"] = r.product_queue
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
                product_queue=r.product_queue,
            )
            report.card_ids.append(str(cid))
            report.persisted += 1
            queued.update(str(i) for i in card["scope"]["product_ids"][:1])
    if persist and queued:  # merge with the open cards earlier runs left on these products
        await product_queue.requeue_products(session, shop_id, queued, now)
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


def _version_brief(v: Mapping[str, Any]) -> dict[str, Any]:
    pm = ((v.get("predicted") or {}).get("money_per_month") or {}).get("total", {}).get("p50", {})
    return {
        "version": v["version"],
        "code": v.get("code"),
        "label": v.get("label"),
        "status": v.get("status"),
        "ranked": bool(v.get("ranked")),
        "inputs": v.get("inputs"),
        "floor_ok": (v.get("floor") or {}).get("ok"),
        "dprofit_month_p50": pm.get("dprofit"),
        "dgmv_month_p50": pm.get("dgmv"),
    }


LEGACY_COMBO = {
    "code": "combo_basket",
    "label": "Combo kiểu cũ (giỏ cố định)",
    "note": "Combo lưu trước khi Juli theo form Combo Khuyến Mãi của Shopee (danh sách sản phẩm, "
    "các mức Mua N). Vẫn đọc được; phương án mới dùng form Shopee.",
}


def legacy_of(card: Mapping[str, Any]) -> dict[str, str] | None:
    """P97 D85.15: a combo saved as a fixed basket (items x quantity, optional inline voucher and
    gift) is kept readable and marked; new combos are Shopee's tiers."""
    return dict(LEGACY_COMBO) if card.get("change_kind") == combo.KIND else None


def target_rows(card: Mapping[str, Any]) -> list[dict[str, Any]]:
    """P97 D85.13: a many-target card's rows without the per-target variants."""
    keys = (
        "id",
        "kind",
        "name",
        "ok",
        "refusal",
        "dgmv_p50",
        "dprofit_p50",
        "cost_month",
        "floor_ok",
    )
    return [{k: t.get(k) for k in keys} for t in card.get(multi.KEY) or []]


async def measurement_states(
    session: AsyncSession, shop_id: uuid.UUID, card_ids: Sequence[uuid.UUID]
) -> dict[str, dict[str, Any]]:
    """Per executed card: its change set and whether the measurement window has closed (the set is
    done or was cut) -- the card then reads as ``measured`` (``status``; ``execution_status`` keeps
    the proposal's own ``executed``)."""
    wanted = {str(c) for c in card_ids}
    out: dict[str, dict[str, Any]] = {}
    if not wanted:
        return out
    for cs in await change_sets.sets_for(session, shop_id):
        for cid in cs.card_ids or []:
            if str(cid) in wanted:
                out[str(cid)] = {
                    "change_set": str(cs.id),
                    "state": (cs.result or {}).get("state") or cs.status,
                    "label": (cs.result or {}).get("label"),
                    "window_days": cs.window_days,
                    "window_closed": cs.status in (change_sets.SET_DONE, change_sets.SET_CUT),
                }
    return out


def _summary(
    p: ShopProposal,
    card: dict[str, Any],
    meta: dict[str, Any] | None = None,
    measuring: Mapping[str, Any] | None = None,
    plan_codes_: Mapping[uuid.UUID, str | None] | None = None,
    measurement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pm = card["predicted"]["money_per_month"]
    product = p.item_id
    stale_why = freshness.card_stale_reason(card)
    return {
        "id": str(p.id),
        "code": p.code,
        "external_ref": card.get("external_ref"),
        "product_id": product,
        "product_queue": p.product_queue,
        "origin": card.get("origin") or store.ORIGIN_ENGINE,
        "created_by": card.get("created_by"),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "chosen_version": (meta or {}).get("chosen_version"),
        "acknowledged_breaches": (meta or {}).get("acknowledged_breaches"),
        "groups": (meta or {}).get("groups"),
        "measurement": measurement,
        "plan_id": None if p.lever_plan_id is None else str(p.lever_plan_id),
        "plan_code": (plan_codes_ or {}).get(p.lever_plan_id) if p.lever_plan_id else None,
        "product_measuring": (
            measuring.get(product) if measuring and product and p.status in OPEN_STATUSES else None
        ),
        "versions": [_version_brief(v) for v in versions.versions_of(card)],
        "status": "measured" if (measurement or {}).get("window_closed") else p.status,
        "execution_status": p.status,
        "cycle": p.cycle,
        "family": card["family"],
        "family_label": card["family_label"],
        "change_kind": card["change_kind"],
        "legacy": legacy_of(card),
        "targets": target_rows(card),
        "fill": card.get("fill"),
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
        "stale": bool((meta or {}).get("stale")) or stale_why is not None,
        "stale_reason": (meta or {}).get("stale_reason") or stale_why,
        "computed_at": (card.get("freshness") or {}).get("computed_at"),
        "engine_version": (card.get("freshness") or {}).get("engine_version"),
        "bundle": card.get("bundle", False),
        "sent_at": None if p.sent_at is None else p.sent_at.isoformat() + "Z",
    }


#: Internals a seller never sees (ADR-121 d.1: "ranges and results, never the model or method").
_SELLER_HIDDEN_TOP = (
    "model_version",
    "rank_inputs",
    "candidate_extra",
    "gap_pct",
    "generated_at",
    "rank",
)
_SELLER_HIDDEN_LIFT = ("factor", "source", "range_scale", "gap_bucket", "sim")


def _scrub(out: dict[str, Any]) -> dict[str, Any]:
    """Drop the internals from one evaluation (a card, or one of its versions)."""
    out = {k: v for k, v in out.items() if k not in _SELLER_HIDDEN_TOP}
    pred = dict(out.get("predicted") or {})
    pred.pop("model_version", None)
    pred.pop("sim", None)
    lift = dict(pred.get("lift") or {})
    for k in _SELLER_HIDDEN_LIFT:
        lift.pop(k, None)
    if "predicted" in out:
        pred["lift"] = lift
        out["predicted"] = pred
    plan = dict(out.get("measurement_plan") or {})
    for k in ("mde_14", "mde_28", "mde_at_plan", "mde_max", "alpha", "power", "baseline_days"):
        plan.pop(k, None)
    if "measurement_plan" in out:
        out["measurement_plan"] = plan
    return out


def seller_view(card: dict[str, Any]) -> dict[str, Any]:
    """The card as the client's manager sees it: certain, predicted range ("dự kiến"), five
    numbers, floor, plan label and execution sheet -- without the model version, calibration
    source / factor, simulation run or ranking internals; each version likewise."""
    out = _scrub(dict(card))
    if out.get("versions"):
        out["versions"] = [_scrub(dict(v)) for v in out["versions"]]
    return out


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


#: What a journey row carries beyond its type and time: the read-back's observation and the
#: impact reading (never the method, the controls or the standard error).
_JOURNEY_FIELDS: dict[str, tuple[str, ...]] = {
    EVENT_VERIFIED: ("change_kind", "expected", "observed", "observed_at", "executed_at"),
    EVENT_MISMATCH: ("change_kind", "expected", "observed", "observed_at", "executed_at"),
    EVENT_NOT_SEEN: ("change_kind", "expected", "executed_at", "deadline"),
    EVENT_IMPACT_PRELIMINARY: ("impact_pct", "confidence", "reason", "post_days", "bundle"),
    EVENT_IMPACT_FINAL: ("impact_pct", "confidence", "reason", "post_days", "bundle"),
}


def journey_payload(event_type: str, payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    fields = _JOURNEY_FIELDS.get(event_type)
    if fields is None or not payload:
        return None
    return {k: payload[k] for k in fields if k in payload}


async def verification_states(
    session: AsyncSession, shop_id: uuid.UUID, card_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """``pending`` | ``verified`` | ``mismatch`` | ``not_seen`` per executed card whose changes
    the Connector can read back (a card with none, or not yet executed, has no entry)."""
    if not card_ids:
        return {}
    rows = (
        await session.execute(
            select(CardEvent.card_id, CardEvent.event_type, CardEvent.payload).where(
                CardEvent.shop_id == shop_id,
                CardEvent.card_id.in_(list(card_ids)),
                CardEvent.event_type.in_(
                    [EVENT_EXECUTED, EVENT_VERIFIED, EVENT_MISMATCH, EVENT_NOT_SEEN]
                ),
            )
        )
    ).all()
    readable: Counter[uuid.UUID] = Counter()
    seen: dict[uuid.UUID, Counter[str]] = {}
    for r in rows:
        if r.event_type == EVENT_EXECUTED:
            kind = ((r.payload or {}).get("change") or {}).get("change_kind")
            if kind in verification.CHANGE_KINDS:
                readable[r.card_id] += 1
        else:
            seen.setdefault(r.card_id, Counter())[r.event_type] += 1
    out: dict[uuid.UUID, str] = {}
    for cid, n in readable.items():
        c = seen.get(cid, Counter())
        if c[EVENT_MISMATCH]:
            out[cid] = EVENT_MISMATCH
        elif c[EVENT_NOT_SEEN]:
            out[cid] = EVENT_NOT_SEEN
        elif c[EVENT_VERIFIED] >= n:
            out[cid] = EVENT_VERIFIED
        else:
            out[cid] = "pending"
    return out


async def list_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    audience: str,
    family: str | None = None,
    section: str | None = None,
    status: str | None = None,
    xep_theo: str = "diem",
    product_id: str | None = None,
    queue: str = "top",
    now: datetime | None = None,
) -> dict[str, Any]:
    """The cards. Default (``queue="top"``): one open card per product -- the one with
    ``product_queue`` 1 (the Quyết định view); cards that are closed or not about one product
    stay. ``queue="all"`` or a ``product_id`` returns every card (of that product): the Sản phẩm
    page, each with its place in the queue."""
    if xep_theo not in XEP_THEO:
        raise ProposalError(ERROR_BAD_INPUT, 422, f"xep_theo must be one of {list(XEP_THEO)}")
    if queue not in ("top", "all"):
        raise ProposalError(ERROR_BAD_INPUT, 422, "queue must be top or all")
    rows = await store.list_cards(session, shop_id)
    states = await verification_states(session, shop_id, [p.id for p, _ in rows])
    measuring = await product_queue.measuring(
        session,
        shop_id,
        _naive(now or datetime.now(UTC)),
        None if product_id is None else [product_id],
    )
    measured = await measurement_states(session, shop_id, [p.id for p, _ in rows])
    plan_codes_ = await plan_codes.plan_codes_for(
        session, shop_id, [p.lever_plan_id for p, _ in rows]
    )
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    behind = 0
    for p, card in rows:
        if audience == "seller" and p.status in SELLER_HIDDEN:
            continue
        if product_id is not None and p.item_id != product_id:
            continue
        if product_id is None and queue == "top" and (p.product_queue or 1) > 1:
            behind += 1
            continue
        if family and card["family"] != family:
            continue
        if section and card.get("wiring_key") != section:
            continue
        if status and p.status != status:
            continue
        meta = await store.card_meta(session, shop_id, p.id)
        summary = _summary(p, card, meta, measuring, plan_codes_, measured.get(str(p.id)))
        summary["verification"] = {"state": states.get(p.id)}
        if audience == "seller":
            rank_ = card.get("rank") or {}
            summary["rank"] = {
                "position": rank_.get("position"),
                "explore": bool(rank_.get("explore")),
            }
        out.append((summary, card))
    if product_id is not None:
        out.sort(key=lambda t: (t[0]["product_queue"] or 10**6, _xep_key(t[1], xep_theo)))
    else:
        out.sort(key=lambda t: (_xep_key(t[1], xep_theo), t[0]["id"]))
    summaries = [s for s, _ in out]
    groups: dict[str, int] = Counter(s["family"] for s in summaries)
    sections: dict[str, int] = Counter(s["section"] or "-" for s in summaries)
    return {
        "platform": "shopee",
        "xep_theo": xep_theo,
        "cards": summaries,
        "queue": queue if product_id is None else "product",
        "counts": {
            "family": dict(groups),
            "section": dict(sections),
            "total": len(summaries),
            "queued_behind": behind,
        },
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
            select(
                CardEvent.event_type,
                CardEvent.occurred_at,
                CardEvent.reason_code,
                CardEvent.payload,
            )
            .where(CardEvent.shop_id == shop_id, CardEvent.card_id == card_id)
            .order_by(CardEvent.occurred_at)
        )
    ).all()
    full = {**card, "code": p.code, "product_queue": p.product_queue}
    full["versions"] = versions.versions_of(full)
    out = {
        **_summary(
            p,
            full,
            meta,
            await product_queue.measuring(
                session, shop_id, _naive(datetime.now(UTC)), [p.item_id] if p.item_id else []
            ),
            await plan_codes.plan_codes_for(session, shop_id, [p.lever_plan_id]),
            (await measurement_states(session, shop_id, [p.id])).get(str(p.id)),
        ),
        "card": seller_view(full) if audience == "seller" else full,
        "journey": [
            {
                "event": e.event_type,
                "at": e.occurred_at.isoformat(),
                "reason_code": e.reason_code,
                "payload": journey_payload(e.event_type, e.payload),
            }
            for e in events
        ],
    }
    approved = await _approved_with(session, shop_id, card_id)
    if approved is not None:
        out["approved_with"] = approved
    states = await verification_states(session, shop_id, [card_id])
    out["verification"] = {"state": states.get(card_id)}
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
    version: int | None = None,
) -> dict[str, Any]:
    """Recompute the whole card with other inputs (every input change recomputes everything,
    contract 7) on the SAME history window the card was proposed on; records `whatif_adjusted`.
    ``version`` (1-based, default 1) names the version the inputs move; only that version is
    recomputed, the others come back as frozen."""
    now = _naive(now)
    p, card = await _proposal(session, shop_id, card_id)
    card = {**card, "code": p.code, "product_queue": p.product_queue}
    if p.status in (STATUS_EXECUTED, STATUS_WITHDRAWN, "superseded"):
        raise ProposalError("reco_card_closed", 409, f"a {p.status} card can no longer be adjusted")
    check_title_input(card, inputs)
    as_of = date.fromisoformat(card["as_of"])
    env = await load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise ProposalError(ERROR_NO_DATA, 409, "shop has no Shopee numbers")
    new_card = recompute_card(env, card, inputs, now=now, version=version)
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
            code=p.code,
            payload={
                "version": new_card.get("version", 1),
                "inputs": inputs,
                "before_inputs": versions.versions_of(card)[(version or 1) - 1].get("inputs")
                or card["inputs"],
                "dprofit_month_p50": new_card["rank_inputs"]["dprofit_p50"],
                "floor_ok": new_card["floor"]["ok"],
            },
            family=card["family"],
            card=card,
            change_kind=card["change_kind"],
            subject=subject,
        )
    return new_card


def check_title_input(card: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
    """A title input is refused above ``MAX_TITLE_CHARS`` (P91 D-4: 100) with a 422."""
    if card.get("change_kind") != "title" or "title" not in inputs:
        return
    n = len(str(inputs["title"] or "").strip())
    if n == 0 or n > config.MAX_TITLE_CHARS:
        raise ProposalError(
            "reco_title_length",
            422,
            f"the title has {n} characters; it must have 1 to {config.MAX_TITLE_CHARS}",
        )


def recompute_card(
    env: RecoEnv,
    card: dict[str, Any],
    inputs: dict[str, Any],
    *,
    now: datetime,
    version: int | None = None,
    rebuild_versions: bool = False,
    keep_parts: bool = False,
) -> dict[str, Any] | None:
    """The card evaluated again. ``version`` moves that version's inputs and replaces only that
    version in ``versions``; ``rebuild_versions`` regenerates every alternative (a replacement
    card made after an import changed the numbers)."""
    if card["family"] == "mega_sale":
        return _recompute_mega(env, card, inputs, now)
    vlist = versions.versions_of(card)
    number = version or 1
    if not 1 <= number <= len(vlist):
        raise ProposalError("reco_version_unknown", 422, f"the card has {len(vlist)} version(s)")
    cand = candidate_of_card(card)
    cand.inputs = _merge_inputs(vlist[number - 1].get("inputs") or cand.inputs, inputs)
    row_targets = vlist[number - 1].get(multi.KEY)
    if row_targets:  # P97 D85.13: one card, a row per target
        out = multi.recompute(env, row_targets, inputs, now=now, merge_inputs=_merge_inputs)
    else:
        out = build_card(env, cand, now=now)
    if out is None:
        return None
    parts = out.pop(
        "_parts", None
    )  # the plan's joint layer asks for them (keep_parts), nobody stores them
    out["id"] = card["id"]
    out["code"] = card.get("code")
    out["rank"] = card.get("rank")
    out["metric"] = card["metric"]
    out["wiring"] = card["wiring"]
    if cand.kind == combo.KIND:  # a combo is named by its products, not by the generic label
        out["title"] = manual.combo_title(env, cand)
    for key in ("origin", "created_by", "primary", "acknowledged_breaches"):
        if key in card:  # who made the card travels with every recompute
            out[key] = card[key]
    if rebuild_versions:
        out["versions"] = versions.build_versions(env, cand, out, now=now)
    else:
        label = vlist[number - 1].get("label") or versions.DEFAULT_LABEL
        code = vlist[number - 1].get("code")
        old = vlist[number - 1]
        new = versions.version_of(out, number, label, code=code)
        # the manual fields (P98: and the builder spec the plan reads back)
        for key in ("index", "chosen", "change_kind", "items", "extra", "spec", multi.KEY):
            if key in old:
                new[key] = old[key]
        if "title" in old:
            new["title"] = out["title"]
        if "metrics" in old:
            new["metrics"] = manual.metrics_of(out)
        vlist[number - 1] = new
        out["versions"] = vlist
    out["version"] = number
    versions.annotate_same_notes(out["versions"])
    if keep_parts and parts:
        out["_parts"] = parts
    return out


def refresh_card(env: RecoEnv, card: dict[str, Any], *, now: datetime) -> dict[str, Any] | None:
    """Every version of the card evaluated again on ``env`` with its OWN inputs (a manual card
    keeps its variants; the engine's alternatives are not regenerated). The top level is V1."""
    if card["family"] == "mega_sale":
        return _recompute_mega(env, card, {}, now)
    cur: dict[str, Any] = card
    vlist = versions.versions_of(card)
    for n in range(len(vlist), 0, -1):  # descending: the top level ends as version 1
        if vlist[n - 1].get("status") == versions.STATUS_REFUSED and n > 1:
            continue
        res = recompute_card(env, cur, {}, now=now, version=n)
        if res is None:
            if n == 1:
                return None
            old = versions.versions_of(cur)
            old[n - 1] = versions.refused_version(
                n, old[n - 1].get("label") or "", old[n - 1].get("inputs") or {}, "no_longer_valid"
            )
            cur = {**cur, "versions": old}
            continue
        cur = res
    return cur


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
        out["code"] = card.get("code")
        out["rank"] = card.get("rank")
        out["versions"] = [versions.version_of(out, 1, versions.DEFAULT_LABEL)]
        out["version"] = 1
    return out


async def _requeue(session: AsyncSession, p: ShopProposal, now: datetime) -> None:
    """A status changed: renumber the product's queue (the next card moves up)."""
    if p.item_id:
        await product_queue.requeue_products(session, p.shop_id, [p.item_id], now)


async def requeue(session: AsyncSession, shop_id: uuid.UUID, *, now: datetime) -> int:
    """The idempotent re-queue the beat / Ops can run: returns how many cards changed place."""
    return await product_queue.requeue_shop(session, shop_id, _naive(now))


async def backfill_codes(session: AsyncSession, shop_id: uuid.UUID, *, now: datetime) -> int:
    """Code the Shopee proposals that predate migration 116 (created_at order; idempotent)."""
    return await codes.backfill_codes(session, shop_id, _naive(now))


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


#: Why Ops takes a card off the list ("Gỡ thẻ"): not fitting, a duplicate, already done outside
#: Juli, anything else.
WITHDRAW_REASONS: tuple[str, ...] = ("not_fit", "duplicate", "done_outside", "other")


async def _detach_from_plan(session: AsyncSession, p: ShopProposal, now: datetime) -> None:
    """A planned card leaves its draft plan before it is withdrawn (a confirmed plan keeps it)."""
    row = await session.scalar(
        select(ShopRecoPlanCard).where(
            ShopRecoPlanCard.shop_id == p.shop_id,
            ShopRecoPlanCard.proposal_id == p.id,
            ShopRecoPlanCard.removed_at.is_(None),
        )
    )
    plan = await session.get(ShopRecoPlan, row.plan_id) if row is not None else None
    if row is None or plan is None or plan.status != PLAN_DRAFT:
        raise ProposalError(
            "reco_card_in_confirmed_plan",
            409,
            "the card belongs to a confirmed plan: take it out of the plan first",
        )
    row.removed_at = now
    plan.updated_at = now
    p.status = row.prior_status
    p.lever_plan_id = None
    await store.set_meta(session, p.shop_id, p.id, {"plan_id": None})


async def withdraw(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    now: datetime,
    reason_code: str | None = None,
    note: str | None = None,
    by: str | None = None,
) -> None:
    """Ops takes a card off the list: it closes as ``withdrawn`` (a planned card leaves its
    draft plan first), the reason is kept on the card, and the product's next card moves up."""
    reason = reason_code or "other"
    if reason not in WITHDRAW_REASONS:
        raise ProposalError(
            ERROR_BAD_INPUT, 422, f"reason_code must be one of {list(WITHDRAW_REASONS)}"
        )
    now = _naive(now)
    p, _ = await _proposal(session, shop_id, card_id)
    if p.status == STATUS_PLANNED:
        await _detach_from_plan(session, p, now)
    await proposals.withdraw(session, p, now=now)
    await store.set_meta(
        session,
        shop_id,
        card_id,
        {
            "withdrawn": {
                "reason_code": reason,
                "note": (note or "").strip()[:300] or None,
                "by": by,
                "at": now.isoformat(),
            }
        },
    )
    await _requeue(session, p, now)


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
    chosen_version: int = 1,
    chosen_versions: list[int] | None = None,
    acknowledge_breaches: bool = False,
) -> dict[str, Any]:
    """The client's decision in the app: ``approve`` one version of the card (``chosen_version``,
    default 1; optionally with adjusted what-if inputs), ``request_change`` or ``dismiss``
    (ADR-107 reason, optional). ``chosen_versions`` (P94) approves several versions as Nhóm A
    when the card can have more than one live value. The chosen version is recorded on the
    approval snapshot and in the card events."""
    now = _naive(now)
    p, card = await _proposal(session, shop_id, card_id)
    code = p.code
    subject = _subject_of(card, card_id)
    result = await _decide(
        session, shop_id, card_id, p, card, subject, decision, user_id, now, inputs,
        reason_code, note, chosen_version, code, acknowledge_breaches, chosen_versions,
    )  # fmt: skip
    await _requeue(session, p, now)
    return result


_EXCLUSIVE_KINDS = frozenset({"title", "price", "cover", "description", "main_image", "discount"})


def _one_live_value(card: dict[str, Any]) -> bool:
    """P94: title, price, cover, one discount, one budget or ROAS cannot share a group."""
    kind = str(card.get("change_kind") or "")
    return kind in _EXCLUSIVE_KINDS or "budget" in kind or "roas" in kind


async def _decide(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    p: ShopProposal,
    card: dict[str, Any],
    subject: tuple[str, str],
    decision: str,
    user_id: uuid.UUID,
    now: datetime,
    inputs: dict[str, Any] | None,
    reason_code: str | None,
    note: str | None,
    chosen_version: int,
    code: str | None,
    acknowledge_breaches: bool = False,
    chosen_versions: list[int] | None = None,
) -> dict[str, Any]:
    if decision == "approve":
        vlist = versions.versions_of(card)
        picked = list(dict.fromkeys(chosen_versions or [chosen_version]))
        if not picked:
            picked = [chosen_version]
        for version in picked:
            if not 1 <= version <= len(vlist):
                raise ProposalError(
                    "reco_version_unknown", 422, f"the card has {len(vlist)} version(s)"
                )
            if vlist[version - 1].get("status") == versions.STATUS_REFUSED:
                raise ProposalError(
                    "reco_version_unavailable",
                    422,
                    f"version {version} is {vlist[version - 1].get('status')} "
                    "and cannot be approved",
                )
        if len(picked) > 1 and _one_live_value(card):
            raise ProposalError(
                "reco_group_exclusive",
                422,
                "this card can keep only one live value; approve the next option as the next group",
            )
        chosen_version = picked[0]
        chosen = vlist[chosen_version - 1]
        final_card = versions.overlay(card, chosen) if chosen_version != 1 else card
        if inputs:
            final_card = (
                await recompute(
                    session,
                    shop_id,
                    card_id,
                    inputs,
                    now=now,
                    record=False,
                    version=chosen_version,
                )
                or final_card
            )
        breaches = versions.breaches_of(final_card)
        if breaches and not acknowledge_breaches:
            kinds = ", ".join(sorted({b["type"] for b in breaches}))
            raise ProposalError(
                "reco_breach_not_acknowledged",
                422,
                f"this version breaches the {kinds}; send acknowledge_breaches to approve it "
                f"({len(breaches)} breach(es): {breaches})",
            )
        acknowledged = (
            {"by": str(user_id), "at": now.isoformat(), "breaches": breaches} if breaches else None
        )
        vcode = chosen.get("code") or (code and codes.version_code(code, chosen_version))
        group = None
        if len(picked) > 1:
            group = {
                "name": "A",
                "versions": picked,
                "version_codes": [
                    (vlist[n - 1].get("code") or (code and codes.version_code(code, n)))
                    for n in picked
                ],
            }
        snapshot_extra = {
            "code": code,
            "chosen_version": chosen_version,
            "chosen_version_code": vcode,
            "chosen_inputs": final_card["inputs"],
            "chosen_change": final_card["change"],
            "acknowledged_breaches": acknowledged,
            **({"group": group} if group else {}),
        }
        approval = await proposals.record_approval(
            session,
            p,
            decision=STATUS_APPROVED,
            channel="in_app",
            decided_at=now,
            now=now,
            decided_by_user_id=user_id,
            note=note,
            snapshot_extra=snapshot_extra,
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
            code=code,
            payload={
                "approval_id": str(approval.id),
                "code": code,
                "chosen_version": chosen_version,
                "chosen_version_code": vcode,
                **({"group": group} if group else {}),
                "acknowledged_breaches": acknowledged,
                "final": final if (inputs or chosen_version != 1) else None,
                "approved_with": {
                    "inputs": final_card["inputs"],
                    "execution_sheet": final_card["execution_sheet"],
                },
                "final_vs_default": _final_vs_default(card, inputs or {}),
            },
            family=card["family"],
            card=card,
            change_kind=card["change_kind"],
            subject=subject,
        )
        await store.set_meta(
            session,
            shop_id,
            card_id,
            {
                "approved_at": now.isoformat(),
                "chosen_version": chosen_version,
                "acknowledged_breaches": acknowledged,
                **({"group": group} if group else {}),
            },
        )
        await fill_queue.enqueue_after_decision(
            session, shop_id=shop_id, proposal_id=card_id, picked=picked,
            final_card=final_card, group_name=str(group["name"]) if group else None, now=now,
        )  # fmt: skip
        return {
            "id": str(card_id),
            "code": code,
            "status": p.status,
            "approval_id": str(approval.id),
            "chosen_version": chosen_version,
            **({"group": group} if group else {}),
        }
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
            code=code,
            payload={"request": note or "", "approval_id": str(approval.id)},
            family=card["family"],
            card=card,
            change_kind=card["change_kind"],
            subject=subject,
        )
        return {"id": str(card_id), "status": p.status, "approval_id": str(approval.id)}
    if decision == "dismiss":
        dcode = reason_code or "unspecified"
        if dcode not in DISMISS_REASON_CODES:
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
            note=note or dcode,
            # a card sent back for a change can still be dropped by the seller
            from_states=frozenset({STATUS_SENT, STATUS_CHANGES_REQUESTED}),
        )
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_DISMISSED,
            actor=ACTOR_SELLER,
            occurred_at=now,
            dedup_key=keys.dismissed(card_id),
            code=p.code,
            payload={"approval_id": str(approval.id)},
            family=card["family"],
            card=card,
            change_kind=card["change_kind"],
            subject=subject,
            reason_code=dcode,
        )
        return {
            "id": str(card_id),
            "status": p.status,
            "approval_id": str(approval.id),
            "reason_code": dcode,
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
                code=p.code,
                payload={"sent_at": p.sent_at.isoformat()},
                family=card["family"],
                card=card,
                change_kind=card["change_kind"],
                subject=_subject_of(card, p.id),
            )
            n += int(ok)
            if ok:
                await _requeue(session, p, now)
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


async def _approved_with(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> dict[str, Any] | None:
    """The inputs and the execution sheet the card was approved with (stored on the `accepted`
    event, so the sheet a person follows is the one for the approved inputs)."""
    ev = await session.scalar(
        select(CardEvent)
        .where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id == card_id,
            CardEvent.event_type == EVENT_ACCEPTED,
        )
        .order_by(CardEvent.occurred_at.desc())
    )
    if ev is None:
        return None
    payload = ev.payload or {}
    if payload.get("approved_with"):
        return dict(payload["approved_with"])
    final = payload.get("final")
    return (
        None
        if not final
        else {"inputs": final["inputs"], "execution_sheet": final["execution_sheet"]}
    )


async def _chosen(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> tuple[int | None, str | None]:
    """(chosen version, its code) from the card's latest `accepted` event."""
    ev = await session.scalar(
        select(CardEvent)
        .where(
            CardEvent.shop_id == shop_id,
            CardEvent.card_id == card_id,
            CardEvent.event_type == EVENT_ACCEPTED,
        )
        .order_by(CardEvent.occurred_at.desc())
    )
    payload = (ev.payload or {}) if ev else {}
    return payload.get("chosen_version"), payload.get("chosen_version_code")


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
    payload_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """ "Đã làm": a person saved the change in Seller Centre. Records the execution
    (ADR-118) and one `executed` event per change in the sheet, each carrying
    ``change = {change_kind, target, expected}`` for the Connector's read-back."""
    now = _naive(now)
    when = _naive(executed_at) if executed_at else now
    p, card = await _proposal(session, shop_id, card_id)
    if p.status != STATUS_APPROVED:
        raise ProposalError("proposal_bad_state", 409, f"a {p.status} card cannot be marked done")
    approved = await _approved_with(session, shop_id, card_id)
    sheet = (approved or {}).get("execution_sheet") or card["execution_sheet"]
    changes = [dict(c) for c in sheet["changes"]]
    for c in changes:
        if c["change_kind"] == "voucher":
            voucher_id = voucher_id or await fill_queue.captured_ref_of(
                session, shop_id, card_id, "voucher"
            )
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
    chosen_version, chosen_code = await _chosen(session, shop_id, card_id)
    # the card joins the change set of its product (or the shop) for that day; a running
    # measurement of the same product is cut today (P91 D-7)
    cset = await change_sets.attach_execution(session, shop_id, p, card, executed_at=when, now=now)
    plan_code = (
        (await plan_codes.plan_codes_for(session, shop_id, [p.lever_plan_id])).get(p.lever_plan_id)
        if p.lever_plan_id
        else None
    )
    for n, change in enumerate(changes):
        await store.write_event(
            session,
            shop_id,
            card_id,
            event_type=EVENT_EXECUTED,
            actor=ACTOR_SELLER if user_id else ACTOR_SYSTEM,
            occurred_at=when,
            dedup_key=f"assisted:{card_id}:{execution.id}:{n}",
            code=p.code,
            payload={
                "chosen_version": chosen_version or 1,
                "chosen_version_code": chosen_code,
                "change": change,
                "execution_id": str(execution.id),
                "executor_role": role,
                "bundle": card.get("bundle", False),
                "change_set": str(cset.id),
                "plan_id": None if p.lever_plan_id is None else str(p.lever_plan_id),
                "plan_code": plan_code,
                **(payload_extra or {}),
            },
            family=card["family"],
            card=card,
            change_kind=card["change_kind"],
            subject=subject,
        )
    await store.set_meta(session, shop_id, card_id, {"executed_at": when.isoformat()})
    await _requeue(session, p, now)  # executed closes the card for the queue at once
    from juli_backend.services.shopee_recommendations import plans

    plan_done = await plans.on_executed(session, shop_id, p, now=now)
    return {
        "id": str(card_id),
        "code": p.code,
        "plan_code": plan_code,
        "status": p.status,
        "execution_id": str(execution.id),
        "events": len(changes),
        "change_set": change_sets.to_json(cset, now=now),
        "plan_executed": plan_done,
    }


#: Event types that make up a card's status history for the export.
_HISTORY_FIELDS = ("chosen_version", "chosen_version_code", "inputs", "before_inputs", "version")


async def card_by_code(
    session: AsyncSession, shop_id: uuid.UUID, code: str, *, audience: str = "ops"
) -> dict[str, Any]:
    """One card by its code (``JC-2611-0007``, or a version code ``JC-2611-0007-V2``): everything a
    row of the later Excel export needs -- the versions with their inputs and numbers, the
    chosen version, the inputs before and after, the status history and the verification state."""
    parsed = codes.parse_code(code)
    if parsed is None:
        raise ProposalError(ERROR_UNKNOWN_CARD, 404)
    base, wanted = parsed
    p = await session.scalar(
        select(ShopProposal).where(ShopProposal.shop_id == shop_id, ShopProposal.code == base)
    )
    payload = await store.card_payload(session, shop_id, p.id) if p is not None else None
    if p is None or payload is None or (audience == "seller" and p.status in SELLER_HIDDEN):
        raise ProposalError(ERROR_UNKNOWN_CARD, 404)
    card = {**payload, "code": base, "product_queue": p.product_queue}
    vlist = versions.versions_of(card)
    for v in vlist:
        v["code"] = v.get("code") or codes.version_code(base, int(v["version"]))
    events = (
        await session.execute(
            select(
                CardEvent.event_type,
                CardEvent.occurred_at,
                CardEvent.actor,
                CardEvent.reason_code,
                CardEvent.payload,
            )
            .where(CardEvent.shop_id == shop_id, CardEvent.card_id == p.id)
            .order_by(CardEvent.occurred_at)
        )
    ).all()
    chosen_n, chosen_code = await _chosen(session, shop_id, p.id)
    approved = await _approved_with(session, shop_id, p.id)
    meta = await store.card_meta(session, shop_id, p.id)
    shown = vlist[(chosen_n or 1) - 1] if 0 < (chosen_n or 1) <= len(vlist) else vlist[0]
    verification_ = (await verification_states(session, shop_id, [p.id])).get(p.id)
    history = [
        {
            "event": e.event_type,
            "at": e.occurred_at.isoformat(),
            "actor": e.actor,
            "reason_code": e.reason_code,
            "payload": {
                **(journey_payload(e.event_type, e.payload) or {}),
                **{k: e.payload[k] for k in _HISTORY_FIELDS if e.payload and k in e.payload},
            },
        }
        for e in events
        if e.event_type != "proposed"
    ]
    out: dict[str, Any] = {
        "code": base,
        "id": str(p.id),
        "status": p.status,
        "cycle": p.cycle,
        "family": card["family"],
        "change_kind": card["change_kind"],
        "title": card["title"],
        "product_id": p.item_id,
        "product_queue": p.product_queue,
        "origin": card.get("origin") or store.ORIGIN_ENGINE,
        "plan_id": None if p.lever_plan_id is None else str(p.lever_plan_id),
        "plan_code": (
            (await plan_codes.plan_codes_for(session, shop_id, [p.lever_plan_id])).get(
                p.lever_plan_id
            )
            if p.lever_plan_id
            else None
        ),
        "planned_date": p.planned_start.isoformat() if p.planned_start else None,
        "groups": (meta or {}).get("groups"),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "sent_at": p.sent_at.isoformat() if p.sent_at else None,
        "supersedes_code": card.get("supersedes_code"),
        "versions": [_version_brief(v) for v in vlist],
        "chosen_version": chosen_n,
        "chosen_version_code": chosen_code,
        "inputs": {
            "default": card["inputs"],
            "chosen": shown.get("inputs"),
            "approved": (approved or {}).get("inputs"),
        },
        "change": {
            "target": (shown.get("change") or {}).get("target"),
            "before": (shown.get("change") or {}).get("before"),
            "after": (shown.get("change") or {}).get("after"),
        },
        "status_history": [
            {"event": "proposed", "at": events[0].occurred_at.isoformat() if events else None},
            *history,
        ],
        "verification": {"state": verification_},
        "card": seller_view(card) if audience == "seller" else card,
    }
    if wanted is not None:
        if not 1 <= wanted <= len(vlist):
            raise ProposalError(ERROR_UNKNOWN_CARD, 404)
        out["selected_version"] = vlist[wanted - 1]
    return out


async def learning_overview(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    from juli_backend.services.shopee_recommendations import learning

    states = await store.load_calibrations(session, shop_id)
    acceptance = await store.load_acceptance(session, shop_id)
    manual_acceptance = await store.load_acceptance(session, shop_id, origin="manual")
    observations = await store.load_observations(session, shop_id)
    sim = await store.load_sim(session, shop_id)
    return {
        "calibration": learning.coverage_report(states),
        "calibration_manual": learning.coverage_report(learning.calibrate(observations, "manual")),
        "acceptance": acceptance.json(),
        "acceptance_manual": manual_acceptance.json(),
        "sim": None if sim is None else sim.summary(),
        "note": "Chấp nhận / bỏ qua chỉ đổi giá trị mặc định và thứ tự xếp hạng, không phải bằng "
        "chứng hiệu quả.",
    }


async def sim_summary(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    sim = await store.load_sim(session, shop_id)
    return {"active": None if sim is None else sim.summary()}


__all__ = [
    "learning_overview",
    "seller_view",
    "sim_summary",
    "KINDS",
    "ACTOR_JULI",
    "GenerationReport",
    "build_candidates",
    "card_by_code",
    "card_detail",
    "decide",
    "expire_old",
    "generate_cards",
    "list_cards",
    "mark_executed",
    "publish",
    "recompute",
    "requeue",
    "backfill_codes",
    "short_id",
    "withdraw",
    "WITHDRAW_REASONS",
]
