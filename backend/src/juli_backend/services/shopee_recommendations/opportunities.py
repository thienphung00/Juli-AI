"""Stored opportunities: what the card run found, and what happened to each candidate.

Batch-1124-c-data, track OPP. Every candidate of a run is one ``shopee_opportunities`` row with an
outcome (published / ranked_out / below_band / refused / duplicate). Chat and later screens read
these rows instead of running the engine per answer.

- ``Ledger`` collects the rows during ``service.generate_cards`` and ``save`` writes them: an
  upsert on (shop, run date, kind, item key, variant key), so a rerun adds nothing. A ``daily``
  write replaces any row of the key; an ``on_demand`` write never replaces a ``daily`` row.
- ``list_opportunities`` reads rows.
- ``generate_for`` runs the same pipeline as the daily run for named products and persists only
  opportunity rows (no card, no queue).
- ``compare`` prices exactly four versions of one kind, or gives the reason each is missing.
- ``draft_card`` rebuilds the card of one stored opportunity (read-only).

Estimates come from the card's stored result (``result_store``); NULL = unknown, never 0.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_opportunities import (
    OUTCOMES,
    SOURCES,
    ShopeeOpportunity,
)
from juli_backend.services.metrics import DERIVATION_VERSION
from juli_backend.services.shopee_recommendations import result_store, versions
from juli_backend.services.shopee_recommendations.model import Candidate

PUBLISHED, RANKED_OUT, BELOW_BAND, REFUSED, DUPLICATE = OUTCOMES
DAILY, ON_DEMAND = SOURCES
#: the seller's day (GMT+7), the run date
LOCAL_OFFSET = timedelta(hours=7)
#: ``reason`` of a candidate cut by the daily card cap
REASON_MAX_CARDS = "max_cards"
REASON_NO_OPPORTUNITY = "no_opportunity"
#: kinds the engine cannot price for the whole shop: they need one product's floor / stock
REASON_NEEDS_PRODUCT = "needs_product_floor"


def run_day(now: datetime) -> date:
    return (now + LOCAL_OFFSET).date()


# ------------------------------------------------------------------------------- keys


def item_key_of(items: Sequence[str]) -> str:
    """Sorted product ids joined by ``,``; ``''`` = the whole shop."""
    return ",".join(sorted(str(i) for i in items))


def point_of(inputs: Mapping[str, Any] | None) -> str:
    """A version point as text: the numeric inputs ``k=v`` sorted by name."""
    if not inputs:
        return ""
    return ",".join(
        f"{k}={inputs[k]:g}" if isinstance(inputs[k], float) else f"{k}={inputs[k]}"
        for k in sorted(inputs)
        if isinstance(inputs[k], int | float) and not isinstance(inputs[k], bool)
    )


def variant_key_of(campaign_key: str | None, point: Mapping[str, Any] | None = None) -> str:
    """``'<campaign_key>|<version point>'``, or ``''`` when both are empty."""
    pt = point_of(point)
    if not campaign_key and not pt:
        return ""
    return f"{campaign_key or ''}|{pt}"


def campaign_of(variant_key: str) -> str | None:
    head = variant_key.split("|", 1)[0]
    return head or None


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:  # NaN / garbage: unknown, never 0
        return None


#: O3: the shop-wide kinds and why the engine has no shop-scope candidate of the kind when it has
#: none. flash_sale / program_registration are priced on one product's discount floor and stock;
#: a shop-wide price needs a per-product floor the engine does not have at shop level.
SHOP_KIND_REFUSALS: dict[str, str] = {
    "program_registration": REASON_NEEDS_PRODUCT,
    "flash_sale": REASON_NEEDS_PRODUCT,
    "min_spend_voucher": "no_shop_voucher_candidate",
    "voucher_cap": "no_live_voucher",
}


def record_shop_refusals(ledger: Ledger, cands: Sequence[Candidate]) -> None:
    """A shop-wide kind with no shop-scope candidate gets a ``refused`` shop row with its reason
    (never "needs a product", never an invented estimate)."""
    have = {c.kind for c in cands if not c.items}
    for kind, reason in SHOP_KIND_REFUSALS.items():
        if kind not in have:
            ledger.add(Candidate(kind=kind), REFUSED, reason=reason)


# ----------------------------------------------------------------------------- ledger


@dataclass
class Draft:
    """One candidate's row before it is written."""

    kind: str
    scope: str
    item_key: str
    variant_key: str
    item_ids: list[str]
    inputs: dict[str, Any]
    outcome: str
    delta_gmv: Decimal | None = None
    delta_profit: Decimal | None = None
    cost: Decimal | None = None
    score: Decimal | None = None
    reason: str | None = None
    card_code: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.kind, self.item_key, self.variant_key)


def estimate_of(
    card: Mapping[str, Any] | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(ΔGMV, Δ lợi nhuận, chi phí) of a built card: its stored result's P50s and ``cost_total``."""
    if not card:
        return None, None, None
    block = card.get(result_store.KEY)
    if block is None:  # no stored result: unknown, never the money layer's other basis
        return None, None, None
    gmv = result_store.p50(block, "gmv")
    profit = result_store.p50(block, "profit")
    cost = block.get("cost_total")
    return _dec(gmv), _dec(profit), _dec(cost)


class Ledger:
    """The rows of one run, filled at every outcome point of ``generate_cards``."""

    def __init__(self, run_date: date, source: str = DAILY) -> None:
        self.run_date, self.source = run_date, source
        self.drafts: dict[tuple[str, str, str], Draft] = {}

    def add(
        self,
        cand: Candidate,
        outcome: str,
        *,
        card: Mapping[str, Any] | None = None,
        reason: str | None = None,
        score: float | None = None,
        card_code: str | None = None,
    ) -> Draft:
        items = [str(i) for i in cand.items]
        gmv, profit, cost = estimate_of(card)
        draft = Draft(
            kind=cand.kind,
            scope="product" if items else "shop",
            item_key=item_key_of(items),
            variant_key=variant_key_of(cand.campaign_key),
            item_ids=sorted(items),
            inputs=_json(dict(cand.inputs)),
            outcome=outcome,
            delta_gmv=gmv,
            delta_profit=profit,
            cost=cost,
            score=None if score is None else Decimal(str(round(score, 6))),
            reason=reason,
            card_code=card_code,
        )
        self.drafts[draft.key] = draft
        return draft

    def get(self, cand: Candidate) -> Draft | None:
        return self.drafts.get(
            (
                cand.kind,
                item_key_of([str(i) for i in cand.items]),
                variant_key_of(cand.campaign_key),
            )
        )

    async def save(self, session: AsyncSession, shop_id: uuid.UUID, *, now: datetime) -> int:
        return await save_drafts(
            session, shop_id, self.run_date, list(self.drafts.values()), self.source, now=now
        )


async def save_drafts(
    session: AsyncSession,
    shop_id: uuid.UUID,
    run_date: date,
    drafts: Sequence[Draft],
    source: str,
    *,
    now: datetime,
) -> int:
    """Upsert the rows (idempotent per key). A ``daily`` write replaces any row of the key; an
    ``on_demand`` write never replaces a ``daily`` row. Returns the rows inserted or updated."""
    if not drafts:
        return 0
    existing = {
        (r.kind, r.item_key, r.variant_key): r
        for r in (
            await session.execute(
                select(ShopeeOpportunity).where(
                    ShopeeOpportunity.shop_id == shop_id, ShopeeOpportunity.run_date == run_date
                )
            )
        ).scalars()
    }
    touched = 0
    for d in drafts:
        row = existing.get(d.key)
        if row is not None and row.source == DAILY and source == ON_DEMAND:
            continue
        if (
            row is not None
            and row.outcome == PUBLISHED
            and d.outcome == DUPLICATE
            and d.card_code == row.card_code
        ):
            continue  # the rerun met the card this very row published: same fact, not a change
        fields = {
            "scope": d.scope,
            "item_ids": d.item_ids,
            "delta_gmv": d.delta_gmv,
            "delta_profit": d.delta_profit,
            "cost": d.cost,
            "inputs": d.inputs,
            "outcome": d.outcome,
            "score": d.score,
            "reason": d.reason,
            "card_code": d.card_code,
            "derivation_version": DERIVATION_VERSION,
            "source": source,
        }
        if row is None:
            session.add(
                ShopeeOpportunity(
                    shop_id=shop_id,
                    run_date=run_date,
                    kind=d.kind,
                    item_key=d.item_key,
                    variant_key=d.variant_key,
                    created_at=now,
                    updated_at=now,
                    **fields,
                )
            )
        else:
            changed = False
            for k, v in fields.items():
                if getattr(row, k) != v:
                    setattr(row, k, v)
                    changed = True
            if not changed:
                continue  # a rerun on the same data writes nothing
            row.updated_at = now
        touched += 1
    await session.flush()
    return touched


# ------------------------------------------------------------------------------- read


@dataclass(frozen=True)
class Opportunity:
    id: uuid.UUID
    kind: str
    scope: str
    item_ids: list[str]
    delta_gmv: Decimal | None
    delta_profit: Decimal | None
    cost: Decimal | None
    inputs: dict[str, Any]
    outcome: str
    reason: str | None
    card_code: str | None
    run_date: date
    score: Decimal | None = None
    source: str = DAILY
    variant_key: str = ""


def _opp(r: ShopeeOpportunity) -> Opportunity:
    return Opportunity(
        id=r.id,
        kind=r.kind,
        scope=r.scope,
        item_ids=[str(i) for i in (r.item_ids or [])],
        delta_gmv=r.delta_gmv,
        delta_profit=r.delta_profit,
        cost=r.cost,
        inputs=dict(r.inputs or {}),
        outcome=r.outcome,
        reason=r.reason,
        card_code=r.card_code,
        run_date=r.run_date,
        score=r.score,
        source=r.source,
        variant_key=r.variant_key,
    )


async def list_opportunities(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    kind: str | None = None,
    item_id: str | None = None,
    run_date: date | None = None,
) -> list[Opportunity]:
    """The shop's stored opportunities of one run (the newest run when ``run_date`` is None),
    best Δ lợi nhuận first; a row with no estimate comes last."""
    if run_date is None:
        run_date = await session.scalar(
            select(ShopeeOpportunity.run_date)
            .where(ShopeeOpportunity.shop_id == shop_id)
            .order_by(ShopeeOpportunity.run_date.desc())
            .limit(1)
        )
        if run_date is None:
            return []
    stmt = select(ShopeeOpportunity).where(
        ShopeeOpportunity.shop_id == shop_id, ShopeeOpportunity.run_date == run_date
    )
    if kind is not None:
        stmt = stmt.where(ShopeeOpportunity.kind == kind)
    rows = [_opp(r) for r in (await session.execute(stmt)).scalars()]
    if item_id is not None:
        rows = [r for r in rows if str(item_id) in r.item_ids]
    rows.sort(key=lambda o: (o.delta_profit is None, -(o.delta_profit or 0), o.kind, o.variant_key))
    return rows


# ---------------------------------------------------------------------- on-demand run


async def generate_for(
    session: AsyncSession,
    shop_id: uuid.UUID,
    products: Sequence[str],
    *,
    now: datetime | None = None,
    as_of: date | None = None,
    env: Any = None,
) -> list[Opportunity]:
    """The daily run's pipeline (candidates -> card -> route -> result -> rank -> dedupe) for the
    named products only. Persists nothing but opportunity rows (``source`` ``on_demand``, never
    over a daily row); no card, no product queue. An empty ``products`` means the shop-scope
    candidates (no product)."""
    from juli_backend.services.shopee_recommendations import service

    moment = (now or datetime.now()).replace(tzinfo=None)
    await service.generate_cards(
        session,
        shop_id,
        now=moment,
        as_of=as_of,
        persist=False,
        record_source=ON_DEMAND,
        only_products=[str(p) for p in products],
        env=env,
    )
    day = run_day(moment)
    wanted = {str(p) for p in products}
    out = await list_opportunities(session, shop_id, run_date=day)
    return [o for o in out if (wanted & set(o.item_ids)) or (not wanted and o.scope == "shop")]


# --------------------------------------------------------------------------- compare


@dataclass
class CompareOption:
    """One of the four versions: its figures, or the reason it has none."""

    version: int
    label: str
    inputs: dict[str, Any]
    status: str
    delta_gmv: Decimal | None = None
    delta_profit: Decimal | None = None
    cost: Decimal | None = None
    reason: str | None = None
    breaches: list[dict[str, Any]] = field(default_factory=list)
    lever: str = ""
    card_code: str | None = None

    @property
    def option(self) -> int:
        """CHAT's contract name for the option number (1 = the engine's default)."""
        return self.version

    def json(self) -> dict[str, Any]:
        return {
            "option": self.version,
            "lever": self.lever,
            "version": self.version,
            "card_code": self.card_code,
            "label": self.label,
            "inputs": self.inputs,
            "status": self.status,
            "delta_gmv": self.delta_gmv,
            "delta_profit": self.delta_profit,
            "cost": self.cost,
            "reason": self.reason,
            "breaches": self.breaches,
        }


@dataclass
class CompareResult:
    kind: str
    item_id: str | None
    options: list[CompareOption]
    reason: str | None = None  # why there are no options at all

    def json(self) -> dict[str, Any]:
        return {"options": [o.json() for o in self.options], "reason": self.reason}

    def __getitem__(self, key: str) -> Any:  # ``result["options"]`` reads like the JSON shape
        return self.json()[key] if key != "options" else self.options


COMPARE_KINDS: tuple[str, ...] = (
    "product_discount",
    "min_spend_voucher",
    "voucher_cap",
    "ads_budget",
    "ads_roas_target",
)
N_OPTIONS = 4


def _option(v: Mapping[str, Any], lever: str = "") -> CompareOption:
    block = v.get(result_store.KEY)
    status = str(v.get("status") or "")
    reason: str | None = None
    breaches: list[dict[str, Any]] = []
    if status == versions.STATUS_REFUSED:
        refusal = v.get("refusal")
        reason = refusal if isinstance(refusal, str) else (refusal or {}).get("code") or "refused"
    elif status != versions.STATUS_OK:
        breaches = versions.breaches_of(v)
        reason = "floor_breach" if status == versions.STATUS_FLOOR else status
    gmv = result_store.p50(block, "gmv")
    profit = result_store.p50(block, "profit")
    cost = (block or {}).get("cost_total")
    return CompareOption(
        lever=lever,
        version=int(v.get("version") or 0),
        label=str(v.get("label") or ""),
        inputs=_json(dict(v.get("inputs") or {})),
        status=status,
        delta_gmv=_dec(gmv),
        delta_profit=_dec(profit),
        cost=_dec(cost),
        reason=reason,
        breaches=_json(breaches),
    )


async def compare(
    session: AsyncSession,
    shop_id: uuid.UUID,
    kind: str,
    *,
    item_id: str | None = None,
    points: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    as_of: date | None = None,
    env: Any = None,
) -> CompareResult:
    """Exactly four evaluated versions of one kind (the engine's candidate for it, then its
    ``versions.ALTERNATIVES`` points, or the seller's own ``points``), each with its figures or the
    reason it has none (refused, or a floor breach). Reads only; nothing is saved."""
    from juli_backend.services.shopee_recommendations import service
    from juli_backend.services.shopee_recommendations.cards import build_card
    from juli_backend.services.shopee_recommendations.loader import load_env

    moment = (now or datetime.now()).replace(tzinfo=None)
    if kind not in COMPARE_KINDS and kind not in versions.ALTERNATIVES:
        return CompareResult(kind, item_id, [], "kind_not_comparable")
    env = env or await load_env(session, shop_id, as_of=as_of, now=moment)
    if env is None:
        return CompareResult(kind, item_id, [], "no_shopee_data")
    cands, _crit = await service.build_candidates(session, shop_id, env)
    mine = [c for c in cands if c.kind == kind and (item_id is None or str(item_id) in c.items)]
    if not mine:
        return CompareResult(kind, item_id, [], REASON_NO_OPPORTUNITY)
    cand = mine[0]
    card = build_card(env, cand, now=moment)
    if card is None:
        from juli_backend.services.shopee_recommendations.cards import refusal_of

        return CompareResult(kind, item_id, [], refusal_of(env, cand))
    if points:
        vs = [versions.version_of(card, 1, versions.DEFAULT_LABEL)]
        for n, pt in enumerate(points[: N_OPTIONS - 1], start=2):
            alt = replace(cand, inputs=versions.fit_inputs(kind, {**cand.inputs, **pt}))
            label = versions.input_label(kind, cand.inputs, alt.inputs)
            built = build_card(env, alt, now=moment)
            vs.append(
                versions.version_of(built, n, label)
                if built is not None
                else versions.refused_version(n, label, alt.inputs, _refusal(env, alt))
            )
        card["versions"] = vs
    else:
        card["versions"] = versions.build_versions(env, cand, card, now=moment)
    blocks = await result_store.compute_many(
        session, shop_id, env, [result_store.Job(card)], now=moment
    )
    result_store.write_into(card, blocks[0])
    options = [_option(v, kind) for v in card["versions"]][:N_OPTIONS]
    while len(options) < N_OPTIONS:  # a point the kind has no slider for: say so
        n = len(options) + 1
        options.append(
            CompareOption(
                n,
                f"Phương án {n}",
                {},
                versions.STATUS_REFUSED,
                reason="no_alternative_point",
                lever=kind,
            )
        )
    return CompareResult(kind, item_id, options)


def _refusal(env: Any, cand: Candidate) -> str | None:
    from juli_backend.services.shopee_recommendations.cards import refusal_of

    return refusal_of(env, cand)


# ------------------------------------------------------------------------ draft card


async def draft_card(
    session: AsyncSession,
    shop_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    *,
    now: datetime | None = None,
    env: Any = None,
) -> dict[str, Any]:
    """The full card (versions and stored results) of one stored opportunity, rebuilt read-only
    from its kind, items and inputs. A refused opportunity answers with its reason; nothing is
    saved and the engine is not searched again."""
    from juli_backend.services.shopee_recommendations.cards import build_card
    from juli_backend.services.shopee_recommendations.loader import load_env

    row = await session.get(ShopeeOpportunity, opportunity_id)
    if row is None or row.shop_id != shop_id:
        return {"ok": False, "reason": REASON_NO_OPPORTUNITY}
    if row.outcome == REFUSED:
        return {"ok": False, "reason": row.reason or "refused", "outcome": row.outcome}
    moment = (now or datetime(row.run_date.year, row.run_date.month, row.run_date.day, 12)).replace(
        tzinfo=None
    )
    env = env or await load_env(session, shop_id, now=moment)
    if env is None:
        return {"ok": False, "reason": "no_shopee_data"}
    from juli_backend.services.shopee_recommendations import service

    # the candidate carries more than kind / items / inputs (``extra``: the proposal, the
    # creator, the add-on item): use the one the engine makes now when it still makes it
    cands, _crit = await service.build_candidates(session, shop_id, env)
    cand = next(
        (
            c
            for c in cands
            if c.kind == row.kind
            and item_key_of([str(i) for i in c.items]) == row.item_key
            and variant_key_of(c.campaign_key) == row.variant_key
        ),
        None,
    )
    if cand is None:  # the run's own cards now lock their products: rebuild from the row
        cand = Candidate(
            kind=row.kind,
            items=tuple(row.item_ids or ()),
            inputs=dict(row.inputs or {}),
            campaign_key=campaign_of(row.variant_key),
        )
    card = build_card(env, cand, now=moment)
    if card is None:
        return {"ok": False, "reason": _refusal(env, cand) or "engine_refused"}
    card["versions"] = versions.build_versions(env, cand, card, now=moment)
    blocks = await result_store.compute_many(
        session, shop_id, env, [result_store.Job(card)], now=moment
    )
    result_store.write_into(card, blocks[0])
    return {
        "ok": True,
        "reason": None,
        "kind": row.kind,
        "outcome": row.outcome,
        "opportunity_id": str(row.id),
        "card": card,
    }


__all__ = [
    "COMPARE_KINDS",
    "CompareOption",
    "CompareResult",
    "Draft",
    "Ledger",
    "Opportunity",
    "compare",
    "draft_card",
    "generate_for",
    "item_key_of",
    "list_opportunities",
    "run_day",
    "save_drafts",
    "variant_key_of",
]
