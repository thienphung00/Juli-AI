"""One card, one number (owner, 2026-11-14): the simulation result stored on the card.

Every screen reads the same figure for a card: the engine result (``integrate.evaluate``, the one
path Tự tạo and Kế hoạch use) of each of its versions, stored on the card as ``result``. The money
layer (``predicted.money_per_month``) no longer drives anything the seller sees or any total.

**Where it lives.** A card is frozen in its ``proposed`` event (append-only, ADR-121 d.3), so the
result computed when the card is made is written into that payload (``card["versions"][n]
["result"]``, and ``card["result"]`` for version 1). A later recomputation (the data changed, the
engine changed, the ``recompute_card_results`` command) cannot touch the event: it is kept in the
card's ``action_cards.metadata_json`` under ``results`` (version number -> block), which
:func:`apply` lays over the payload whenever the store reads a card. The first time an approved /
executed card is recomputed, the result it was approved with is kept as ``result_at_approval``
(measurement compares the reading with what the client approved, never with a later figure).

**Freshness.** A block carries ``inputs_hash`` = the version's spec, the engine version and the
inputs fingerprint of the card's scope on the block's own ``as_of`` (``freshness.fingerprint``:
costs, VAT, fees, rules, exclusions, the last order days). A new day of orders leaves it fresh; a
correction or a new engine version makes it stale. ``is_fresh`` is what the plan asks before it
reuses a stored result; the refresh job (``refresh_shop``) recomputes the stale ones.

**Block** (``block_of``): ``estimable``, ``basis``, ``reason`` / ``message`` (not estimable ->
"Chưa ước tính được"), ``own`` (dates, days, Δ gmv / profit / orders P10 / P50 / P90 over the
version's own days, ``cost_total``), ``roi``, ``margin``, ``break_even_orders``, ``option`` (the
builder's wire ``OptionResult`` JSON: the card page draws Tự tạo's result card from it), ``core``
(the exact Decimals the plan rebuilds the ``OptionResult`` from), ``targets`` (one core per target
of a many-target version), ``start``, ``as_of``, ``computed_at``, ``engine_version``,
``inputs_hash``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_PLANNED,
    STATUS_SENT,
    ShopProposal,
)
from juli_backend.services.shopee_recommendations import config, freshness, versions
from juli_backend.services.shopee_recommendations.env import RecoEnv

if TYPE_CHECKING:
    from juli_backend.services.shopee_builder.context import BuilderContext
    from juli_backend.services.shopee_builder.engine.contract import OptionResult, Scenario

KEY = "result"
META_RESULTS = "results"
AT_APPROVAL = "result_at_approval"
RESULT_SCHEMA = "card-result/1"
NOT_ESTIMABLE_TEXT = "Chưa ước tính được"
NOT_COMPUTED = "not_computed"
#: Statuses whose cards keep a live result (``recompute_card_results`` and the refresh job).
NON_TERMINAL = (
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_CHANGES_REQUESTED,
    STATUS_PLANNED,
    STATUS_APPROVED,
    STATUS_EXECUTED,
)
#: Statuses whose approval-time result is kept before any recomputation.
APPROVED_LIKE = (STATUS_APPROVED, STATUS_EXECUTED)
COLUMNS = (("p10", "low"), ("p50", "likely"), ("p90", "high"))
METRICS = {"gmv": "gmv", "profit": "profit", "orders": "orders"}


def engine_version() -> str:
    return f"{config.ENGINE_VERSION}+{RESULT_SCHEMA}"


# ------------------------------------------------------------------- the OptionResult as JSON


def _s(x: Decimal | None) -> str | None:
    return None if x is None else format(x, "f")


def _d(x: Any) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def _scenario_core(s: Scenario | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "views": _s(s.views),
        "clicks": _s(s.clicks),
        "orders": _s(s.orders),
        "gmv": _s(s.gmv),
        "profit": _s(s.profit),
        "offer_cost": _s(s.offer_cost),
    }


def core_of(r: OptionResult) -> dict[str, Any]:
    """The exact figures of an ``OptionResult`` (Decimals as strings) -- what the plan needs to
    rebuild it (``option_of``) and count the card on its days, to the đồng."""
    return {
        "kind": r.kind,
        "label": r.label,
        "days": r.days,
        "horizon": r.horizon,
        "drivers": list(r.drivers),
        "estimable": r.estimable,
        "basis": r.basis,
        "before": _scenario_core(r.before),
        "low": _scenario_core(r.low),
        "likely": _scenario_core(r.likely),
        "high": _scenario_core(r.high),
        "cost_total": _s(r.cost_total),
        "break_even_orders": _s(r.break_even_orders),
        "break_even_aov": _s(r.break_even_aov),
        "notes": list(r.notes),
    }


def _scenario_of(raw: Mapping[str, Any] | None) -> Scenario | None:
    from juli_backend.services.shopee_builder.engine.contract import Scenario

    if raw is None:
        return None
    return Scenario(
        views=_d(raw.get("views")),
        clicks=_d(raw.get("clicks")),
        orders=_d(raw.get("orders")) or Decimal(0),
        gmv=_d(raw.get("gmv")) or Decimal(0),
        profit=_d(raw.get("profit")),
        offer_cost=_d(raw.get("offer_cost")) or Decimal(0),
    )


def option_of(core: Mapping[str, Any]) -> OptionResult:
    """The ``OptionResult`` a stored ``core`` was taken from (scenarios, days, cost, basis)."""
    from juli_backend.services.shopee_builder.engine.contract import OptionResult

    before = _scenario_of(core["before"])
    assert before is not None
    return OptionResult(
        kind=str(core["kind"]),
        label=str(core.get("label") or ""),
        days=int(core["days"]),
        horizon=core.get("horizon") or "duration",
        drivers=tuple(core.get("drivers") or ()),
        estimable=bool(core["estimable"]),
        basis=core.get("basis") or "not_estimable",
        before=before,
        low=_scenario_of(core.get("low")),
        likely=_scenario_of(core.get("likely")),
        high=_scenario_of(core.get("high")),
        build_up=(),
        cost_total=_d(core.get("cost_total")) or Decimal(0),
        break_even_orders=_d(core.get("break_even_orders")),
        break_even_aov=_d(core.get("break_even_aov")),
        notes=tuple(core.get("notes") or ()),
    )


# ------------------------------------------------------------------------------ the block


def _delta(r: OptionResult, name: str) -> dict[str, float | None] | None:
    """``{p10, p50, p90}`` of one metric over the result's own days (column - before)."""
    if not r.estimable or r.likely is None:
        return None
    out: dict[str, float | None] = {}
    for q, col in COLUMNS:
        s: Scenario | None = getattr(r, col)
        a = None if s is None else getattr(s, name)
        b = getattr(r.before, name)
        out[q] = None if a is None or b is None else float(a - b)
    if name == "orders":
        from juli_backend.services.shopee_builder.engine.wire import round_count

        out = {q: round_count(v) for q, v in out.items()}
    return out


def inputs_hash(
    spec_json: Mapping[str, Any] | None, env: RecoEnv, items: Sequence[str], as_of: date
) -> str:
    """The version's spec, the engine version and the scope's inputs fingerprint on ``as_of``."""
    blob = json.dumps(
        {
            "spec": spec_json,
            "engine": engine_version(),
            "inputs": freshness.fingerprint(env, list(items), as_of),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def block_of(
    result: OptionResult | None,
    *,
    reason: str | None,
    start: date | None,
    targets: Mapping[str, OptionResult | None] | None,
    as_of: date,
    now: datetime,
    hash_: str,
) -> dict[str, Any]:
    """The stored ``result`` of one version (see the module docstring)."""
    estimable = result is not None and result.estimable and result.likely is not None
    if result is not None and not estimable and reason is None:
        reason = "not_estimable"
    days = None if result is None else result.days
    dates = None
    if result is not None and start is not None:
        end = date.fromordinal(start.toordinal() + result.days - 1)
        dates = {"from": start.isoformat(), "to": end.isoformat(), "days": result.days}
    cost = None if result is None else float(result.cost_total)
    wire = None if result is None else result.json()
    be = None if result is None else result.break_even_orders
    return {
        "estimable": estimable,
        "not_estimable": not estimable,
        "basis": None if result is None else result.basis,
        "reason": None if estimable else (reason or "not_estimable"),
        "message": None if estimable else NOT_ESTIMABLE_TEXT,
        "own": {
            "dates": dates,
            "dated": start is not None,
            "days": days,
            "delta": None
            if not estimable or result is None
            else {k: _delta(result, f) for k, f in METRICS.items()},
            "cost_total": cost,
        },
        "cost_total": cost,
        "roi": None if wire is None else wire.get("roi"),
        "margin": None if wire is None else wire.get("margin"),
        "break_even_orders": None if be is None else float(math.ceil(float(be) - 1e-6)),
        "option": wire,
        "core": None if result is None else core_of(result),
        "targets": {t: (None if r is None else core_of(r)) for t, r in (targets or {}).items()},
        "start": None if start is None else start.isoformat(),
        "as_of": as_of.isoformat(),
        "computed_at": now.isoformat(),
        "engine_version": engine_version(),
        "inputs_hash": hash_,
    }


def missing_block() -> dict[str, Any]:
    """A card whose result was never computed (before the recompute command ran)."""
    return {
        "estimable": False,
        "not_estimable": True,
        "basis": None,
        "reason": NOT_COMPUTED,
        "message": NOT_ESTIMABLE_TEXT,
        "own": {"dates": None, "dated": False, "days": None, "delta": None, "cost_total": None},
        "cost_total": None,
        "roi": None,
        "margin": None,
        "break_even_orders": None,
        "option": None,
        "core": None,
        "targets": {},
    }


# --------------------------------------------------------------------------- reading


def apply(card: dict[str, Any], meta: Mapping[str, Any] | None) -> dict[str, Any]:
    """The card with its newest results laid over the frozen payload (in place, returned)."""
    stored = (meta or {}).get(META_RESULTS) or {}
    if meta and meta.get(AT_APPROVAL):
        card[AT_APPROVAL] = meta[AT_APPROVAL]
    if not stored:
        return card
    vlist = card.get("versions")
    if vlist:
        for v in vlist:
            got = stored.get(str(v.get("version")))
            if got is not None:
                v[KEY] = got
    if stored.get("1") is not None:
        card[KEY] = stored["1"]
    return card


def version_result(card: Mapping[str, Any], version: int | None = None) -> dict[str, Any] | None:
    """The stored result of ``version`` (default 1); ``None`` when none was computed."""
    n = version or 1
    for v in card.get("versions") or []:
        if int(v.get("version") or 0) == n and v.get(KEY):
            return dict(v[KEY])
    if n == 1 and card.get(KEY):
        return dict(card[KEY])
    return None


def p50(block: Mapping[str, Any] | None, metric: str) -> float | None:
    own = (block or {}).get("own") or {}
    return (((own.get("delta") or {}).get(metric)) or {}).get("p50")


def per_day(block: Mapping[str, Any] | None, metric: str) -> float | None:
    v = p50(block, metric)
    days = ((block or {}).get("own") or {}).get("days")
    return None if v is None or not days else v / int(days)


def summary(block: Mapping[str, Any] | None) -> dict[str, Any]:
    """``predicted_summary`` of the card list / page: the result's own-days band, or nulls with
    ``not_estimable`` and the reason."""
    b = block or missing_block()
    own = b.get("own") or {}
    d = own.get("delta") or {}

    def band(m: str) -> dict[str, float | None]:
        got = d.get(m) or {}
        return {q: got.get(q) for q in ("p10", "p50", "p90")}

    return {
        "dgmv": band("gmv"),
        "dprofit": band("profit"),
        "dorders": band("orders"),
        # deprecated names (the band is for the card's own days, not a month)
        "dgmv_month": band("gmv"),
        "dprofit_month": band("profit"),
        "label": "Dự kiến",
        "effect_days": own.get("days"),
        "dates": own.get("dates"),
        "estimable": bool(b.get("estimable")),
        "not_estimable": not b.get("estimable"),
        "reason": b.get("reason"),
        "message": b.get("message"),
        "basis": b.get("basis"),
        "roi": b.get("roi"),
        "margin": b.get("margin"),
        "break_even_orders": b.get("break_even_orders"),
    }


def is_fresh(block: Mapping[str, Any] | None, env: RecoEnv, card: Mapping[str, Any]) -> bool:
    """The stored block still answers on ``env``: same engine, same inputs on its own day."""
    if not block or block.get("engine_version") != engine_version() or not block.get("as_of"):
        return False
    try:
        as_of = date.fromisoformat(str(block["as_of"]))
    except ValueError:
        return False
    if as_of > env.as_of:
        return False
    spec_json = block.get("_spec")
    return block.get("inputs_hash") == inputs_hash(spec_json, env, scope_items(card), as_of)


def scope_items(card: Mapping[str, Any]) -> list[str]:
    return sorted({str(i) for i in (card.get("scope") or {}).get("product_ids") or []})


# ------------------------------------------------------------------------------ measuring


def measured_block(card: Mapping[str, Any]) -> dict[str, Any] | None:
    """The result a measurement is judged against: the one the card was approved with when kept,
    else the chosen (or first) version's stored result."""
    if card.get(AT_APPROVAL):
        return dict(card[AT_APPROVAL])
    return version_result(card, int(card.get("version") or 1)) or version_result(card, 1)


def _metric_of(col: Mapping[str, Any] | None, metric: str) -> Decimal | None:
    if col is None:
        return None
    views, clicks = _d(col.get("views")), _d(col.get("clicks"))
    orders, gmv = _d(col.get("orders")), _d(col.get("gmv"))
    if metric == "gmv":
        return gmv
    if metric == "orders":
        return orders
    if metric == "views":
        return views
    if metric == "ctr":
        return None if not views or clicks is None else clicks / views
    if metric == "ctor":
        return None if not clicks or orders is None else orders / clicks
    if metric == "aov":
        return None if not orders or gmv is None else gmv / orders
    return None


def metric_band(block: Mapping[str, Any] | None, metric: str) -> dict[str, float] | None:
    """The result's relative change of ``metric`` (a fraction, like a measured ``impact_pct``):
    ``{p10, p50, p90}`` from the low / likely / high columns over the before column; ``None``
    when the result does not know that metric (not estimable, ads metrics)."""
    core = (block or {}).get("core")
    if not core or not (block or {}).get("estimable"):
        return None
    base = _metric_of(core.get("before"), metric)
    if base is None or base == 0:
        return None
    rel: list[float] = []
    for col in ("low", "likely", "high"):
        v = _metric_of(core.get(col), metric)
        if v is None:
            return None
        rel.append(float(v / base - 1))
    lo, hi = min(rel), max(rel)
    return {"p10": lo, "p50": rel[1], "p90": hi}


def profit_band(block: Mapping[str, Any] | None, days: int | None) -> dict[str, float | None]:
    """The result's Δ lợi nhuận band over ``days`` (its own days spread evenly)."""
    own = (block or {}).get("own") or {}
    d = (own.get("delta") or {}).get("profit") or {}
    own_days = own.get("days")
    k = None if not days or not own_days else int(days) / int(own_days)

    def at(q: str) -> float | None:
        v = d.get(q)
        return None if v is None or k is None else float(v) * k

    return {"p10": at("p10"), "p50": at("p50"), "p90": at("p90")}


# ------------------------------------------------------------------------------- computing


@dataclass
class Job:
    """One card to compute: its payload and the versions wanted (default: every live one)."""

    card: dict[str, Any]
    wanted: Sequence[int] | None = None
    specs: dict[int, Any] = field(default_factory=dict)
    no_spec: set[int] = field(default_factory=set)
    #: versions whose spec was rebuilt from the card's candidate (no "Chọn" spec): their dates are
    #: the day they were computed, and a plan starts them on its own first day
    rebuilt: set[int] = field(default_factory=set)


def _version_numbers(card: Mapping[str, Any], wanted: Sequence[int] | None) -> list[int]:
    out = []
    for v in versions.versions_of(card):
        n = int(v["version"])
        if wanted is not None and n not in wanted:
            continue
        if v.get("status") == versions.STATUS_REFUSED:
            continue
        out.append(n)
    return out


def spec_of_version(
    card: Mapping[str, Any], n: int, today: date, variations: Mapping[str, Any] | None
) -> Any | None:
    """The builder spec of version ``n``: the one "Chọn" stored, else rebuilt from the card's
    candidate (``plan_aggregate.spec_of_candidate``); ``None`` = no spec (no result)."""
    from juli_backend.services.shopee_recommendations import plan_aggregate as pa
    from juli_backend.services.shopee_recommendations.mega import candidate_of_card

    if card.get("family") == "mega_sale":
        return None
    vlist = versions.versions_of(card)
    if not 1 <= n <= len(vlist):
        return None
    row = vlist[n - 1]
    try:
        cand = candidate_of_card(versions.overlay(card, row))
    except (KeyError, TypeError):
        return None
    return pa.spec_of_candidate(cand, today, row.get("spec"), variations)


def _set_specs(jobs: Sequence[Job], today: date, variations: Mapping[str, Any] | None) -> None:
    for j in jobs:
        vlist = versions.versions_of(j.card)
        for n in _version_numbers(j.card, j.wanted):
            spec = spec_of_version(j.card, n, today, variations)
            if spec is None:
                j.no_spec.add(n)
                continue
            j.specs[n] = spec
            if not vlist[n - 1].get("spec"):
                j.rebuilt.add(n)


def _items_of(jobs: Sequence[Job]) -> list[str]:
    out: list[str] = []
    for j in jobs:
        out += scope_items(j.card)
        for v in versions.versions_of(j.card):
            out += [str(i) for i in v.get("items") or []]
    return list(dict.fromkeys(out))


async def context_for(
    session: AsyncSession, shop_id: uuid.UUID, env: RecoEnv, jobs: Sequence[Job], *, now: datetime
) -> BuilderContext:
    """One builder context for every version of ``jobs`` (the specs are set on the jobs): the
    same context ``builder.build_context`` gives Tự tạo -- variations, reference orders, keyword
    volumes, the 90-day price response -- on a copy of ``env`` (the caller's env is not touched)."""
    from juli_backend.services.shopee_builder import service as builder

    work = copy.copy(env)
    variations = await builder.variation_rows_for(session, shop_id, work, _items_of(jobs))
    _set_specs(jobs, now.date(), variations)
    specs = [s for j in jobs for s in j.specs.values()]
    return await builder.build_context(session, shop_id, specs, as_of=work.as_of, now=now, env=work)


def evaluate_spec(
    ctx: BuilderContext,
    spec: Any,
    shop_id: uuid.UUID | str,
    card: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """The block of one version spec on ``ctx`` (exactly Tự tạo's ``integrate.evaluate``)."""
    from juli_backend.services.shopee_builder import specs as sp
    from juli_backend.services.shopee_builder.context import SpecRefused
    from juli_backend.services.shopee_builder.engine_families import integrate
    from juli_backend.services.shopee_recommendations.plan_aggregate import spec_start

    src = ctx.source_env or ctx.env
    spec_json = sp.as_json(spec)
    h = inputs_hash(spec_json, src, scope_items(card), src.as_of)
    start = spec_start(spec)
    try:
        done, targets = integrate.evaluate(ctx, spec, str(shop_id))
    except (SpecRefused, ValueError, KeyError, ArithmeticError) as exc:
        out = block_of(
            None,
            reason=f"refused:{type(exc).__name__}",
            start=start,
            targets=None,
            as_of=src.as_of,
            now=now,
            hash_=h,
        )
    else:
        reason = None
        if done.result is None:
            reason = done.refusal.code if done.refusal is not None else "refused"
        out = block_of(
            done.result,
            reason=reason,
            start=start,
            targets={t: e.result for t, e in targets},
            as_of=src.as_of,
            now=now,
            hash_=h,
        )
    out["_spec"] = spec_json
    return out


def no_spec_block(card: Mapping[str, Any], env: RecoEnv, now: datetime) -> dict[str, Any]:
    out = block_of(
        None,
        reason="no_spec",
        start=None,
        targets=None,
        as_of=env.as_of,
        now=now,
        hash_=inputs_hash(None, env, scope_items(card), env.as_of),
    )
    out["_spec"] = None
    return out


async def compute_many(
    session: AsyncSession,
    shop_id: uuid.UUID,
    env: RecoEnv,
    jobs: Sequence[Job],
    *,
    now: datetime,
    ctx: BuilderContext | None = None,
) -> list[dict[int, dict[str, Any]]]:
    """Per job: version number -> its block. ``ctx`` (the builder's own context, "Chọn") is used
    as it is; else one context is built for all jobs."""
    if not jobs:
        return []
    if ctx is None:
        ctx = await context_for(session, shop_id, env, jobs, now=now)
    else:
        _set_specs(jobs, now.date(), ctx.variations)
    src = ctx.source_env or ctx.env
    out: list[dict[int, dict[str, Any]]] = []
    for j in jobs:
        got: dict[int, dict[str, Any]] = {}
        for n in sorted({*j.specs, *j.no_spec}):
            if n in j.specs:
                got[n] = evaluate_spec(ctx, j.specs[n], shop_id, j.card, now=now)
                got[n]["spec_source"] = "rebuilt" if n in j.rebuilt else "stored"
            else:
                got[n] = no_spec_block(j.card, src, now)
        out.append(got)
    return out


def write_into(card: dict[str, Any], blocks: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    """Put the blocks on a card about to be saved (frozen with it): each version and the top."""
    vlist = card.get("versions")
    if vlist:
        for v in vlist:
            got = blocks.get(int(v.get("version") or 0))
            if got is not None:
                v[KEY] = dict(got)
                if isinstance(v.get("metrics"), dict):  # the side-by-side reads the result too
                    v["metrics"].update(metrics_of_block(got))
    if blocks.get(1) is not None:
        card[KEY] = dict(blocks[1])
    return card


def metrics_of_block(block: Mapping[str, Any]) -> dict[str, Any]:
    """A version's ``metrics`` figures from its result (own days; ``cost`` = Chi phí)."""
    own = block.get("own") or {}
    d = own.get("delta") or {}
    prof, gmv, orders = d.get("profit") or {}, d.get("gmv") or {}, d.get("orders") or {}
    return {
        "dprofit_p10": prof.get("p10"),
        "dprofit_p50": prof.get("p50"),
        "dprofit_p90": prof.get("p90"),
        "dgmv_p50": gmv.get("p50"),
        "dorders_p50": orders.get("p50"),
        "cost": block.get("cost_total"),
        "days": own.get("days"),
        "estimable": bool(block.get("estimable")),
    }


def rank_profit(block: Mapping[str, Any] | None) -> float | None:
    """The ranking's Δ lợi nhuận P50 (``rank_inputs.dprofit_p50``): the result's own-days P50."""
    return p50(block, "profit")


def rank_from_results(card: dict[str, Any]) -> None:
    """``rank_inputs.dprofit_p50`` of the card and each version = its stored result's P50 (the
    money layer's figure is kept as ``dprofit_p50_money`` for the record, never ranked on)."""

    def one(row: dict[str, Any], block: Mapping[str, Any] | None) -> None:
        ri = row.get("rank_inputs")
        if not isinstance(ri, dict) or block is None:
            return
        if "dprofit_p50_money" not in ri:
            ri["dprofit_p50_money"] = ri.get("dprofit_p50")
        ri["dprofit_p50"] = rank_profit(block)
        ri["dprofit_p50_basis"] = "result"

    for v in card.get("versions") or []:
        one(v, v.get(KEY))
    one(card, card.get(KEY))


# ---------------------------------------------------------------------------- persisting


async def _row(session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID) -> ActionCard | None:
    return await session.scalar(
        select(ActionCard).where(ActionCard.id == card_id, ActionCard.shop_id == shop_id)
    )


async def save(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    card: Mapping[str, Any],
    blocks: Mapping[int, Mapping[str, Any]],
    *,
    status: str | None,
    chosen_version: int | None = None,
) -> bool:
    """Store recomputed blocks in the card's metadata (the event stays as it was frozen). An
    approved / executed card first keeps the result it was approved with (once)."""
    row = await _row(session, shop_id, card_id)
    if row is None:
        return False
    meta = json.loads(row.metadata_json or "{}")
    if status in APPROVED_LIKE and not meta.get(AT_APPROVAL):
        n = chosen_version or meta.get("chosen_version") or 1
        before = version_result(card, int(n))
        if before is None:
            before = dict(blocks.get(int(n)) or {}) or None
        if before is not None:
            meta[AT_APPROVAL] = {**before, "version": int(n)}
    results = dict(meta.get(META_RESULTS) or {})
    for n, b in blocks.items():
        results[str(n)] = dict(b)
    meta[META_RESULTS] = results
    row.metadata_json = json.dumps(meta, default=str)
    return True


async def freeze_at_approval(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    card: Mapping[str, Any],
    version: int,
) -> None:
    """At approval: keep the chosen version's result as ``result_at_approval`` (first time only)."""
    row = await _row(session, shop_id, card_id)
    block = version_result(card, version)
    if row is None or block is None:
        return
    meta = json.loads(row.metadata_json or "{}")
    if meta.get(AT_APPROVAL):
        return
    meta[AT_APPROVAL] = {**block, "version": int(version)}
    row.metadata_json = json.dumps(meta, default=str)


@dataclass
class Counts:
    cards: int = 0
    updated: int = 0
    fresh: int = 0
    not_estimable: int = 0
    failed: int = 0

    def json(self) -> dict[str, int]:
        return {
            "cards": self.cards,
            "updated": self.updated,
            "fresh": self.fresh,
            "not_estimable": self.not_estimable,
            "failed": self.failed,
        }


async def refresh_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    env: RecoEnv,
    *,
    now: datetime,
    force: bool = False,
    dry_run: bool = False,
    card_ids: Sequence[uuid.UUID] | None = None,
) -> Counts:
    """Recompute and store the result of every non-terminal card (approved, executed and
    measuring ones too) whose stored result is missing or stale on ``env`` -- every one with
    ``force``. Idempotent: a second run finds every result fresh and writes nothing."""
    from juli_backend.services.shopee_recommendations import store

    counts = Counts()
    stmt = (
        select(ShopProposal)
        .join(ActionCard, ActionCard.id == ShopProposal.id)
        .where(
            ShopProposal.shop_id == shop_id,
            ActionCard.status == store.CARD_STATUS,
            ShopProposal.status.in_(list(NON_TERMINAL)),
        )
        .order_by(ShopProposal.created_at)
    )
    if card_ids is not None:
        stmt = stmt.where(ShopProposal.id.in_(list(card_ids)))
    proposals = list((await session.scalars(stmt)).all())
    todo: list[tuple[ShopProposal, dict[str, Any]]] = []
    for p in proposals:
        card = await store.card_payload(session, shop_id, p.id)
        if card is None:
            continue
        counts.cards += 1
        live = _version_numbers(card, None)
        if not force and all(is_fresh(version_result(card, n), env, card) for n in live):
            counts.fresh += 1
            continue
        todo.append((p, card))
    for p, card in todo:
        try:
            [blocks] = await compute_many(session, shop_id, env, [Job(card)], now=now)
        except (ValueError, KeyError, TypeError, ArithmeticError, LookupError):
            counts.failed += 1  # one card's failure stops no other card
            continue
        meta = await store.card_meta(session, shop_id, p.id)
        chosen = int(meta.get("chosen_version") or 1)
        head = blocks.get(chosen) or blocks.get(1)
        if head is None or not head.get("estimable"):
            counts.not_estimable += 1
        if dry_run:
            counts.updated += 1
            continue
        if await save(session, shop_id, p.id, card, blocks, status=p.status, chosen_version=chosen):
            counts.updated += 1
    if not dry_run:
        await session.flush()
    return counts


__all__ = [
    "AT_APPROVAL",
    "KEY",
    "NON_TERMINAL",
    "Counts",
    "Job",
    "apply",
    "block_of",
    "compute_many",
    "core_of",
    "freeze_at_approval",
    "is_fresh",
    "measured_block",
    "metric_band",
    "profit_band",
    "option_of",
    "p50",
    "per_day",
    "rank_from_results",
    "rank_profit",
    "refresh_shop",
    "save",
    "summary",
    "version_result",
    "write_into",
]
