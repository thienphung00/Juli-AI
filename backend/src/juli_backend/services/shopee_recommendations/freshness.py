"""Is a stored card still what the engine would compute now?

Every card (and every version) carries a ``freshness`` block written when it was computed:
``computed_at``, ``engine_version`` (:data:`config.ENGINE_VERSION`), ``inputs_fingerprint`` and the
``as_of`` day. The fingerprint covers what the card's numbers depend on and the seller (or a data
load) can change: costs and packaging, VAT flags and rates, exclusions, fee formulas, targets and
caps, and the order / income lines of the card's scope on the last days before ``as_of`` (the days
a late load or a correction still moves). A new day of orders does not change it: cards expire on
their own.

``stale_reason`` compares a card with the current engine version (cheap, needs no data) and, when
an environment is given, with the current fingerprint. The refresh job (``refresh``) marks and
recomputes the stale ones.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.env import RecoEnv

#: Days before ``as_of`` whose order lines are part of the fingerprint.
DATA_DAYS = 7
REASON_ENGINE = "engine_version_changed"
REASON_INPUTS = "inputs_changed"
REASON_MISSING = "never_stamped"


def _canon(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _canon(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Mapping):
        return sorted(([str(k), _canon(v)] for k, v in obj.items()), key=lambda kv: kv[0])
    if isinstance(obj, set | frozenset):
        return sorted(str(x) for x in obj)
    if isinstance(obj, list | tuple):
        return [_canon(x) for x in obj]
    if isinstance(obj, Decimal):
        return format(obj.normalize(), "f")
    if isinstance(obj, date | datetime):
        return obj.isoformat()
    return obj if isinstance(obj, str | int | float | bool) or obj is None else str(obj)


def fingerprint(env: RecoEnv, items: Sequence[str] | None, as_of: date) -> str:
    """Hash of the inputs the card's scope reads (see the module docstring)."""
    wanted = list(items) if items else env.item_ids()
    skus = sorted({sk for i in wanted for sk in env.skus_of(i)})
    rules = env.ctx.rules.for_month(f"{as_of.year:04d}-{as_of.month:02d}")
    since = as_of - timedelta(days=DATA_DAYS - 1)
    scope = set(wanted)
    lines = [
        ln for ln, _ in env.view.pairs if ln.product_id in scope and since <= ln.order_date <= as_of
    ]
    parts = {
        "costs": [[sk, _canon(env.costs.get(sk))] for sk in skus],
        "fees": [[i, _canon(env.schedule(i).formula_on(as_of))] for i in sorted(wanted)],
        "rules": _canon(rules),
        "excluded": sorted(i for i in wanted if i in env.excluded),
        "data": [
            len(lines),
            str(sum((ln.order_value for ln in lines), Decimal(0))),
            str(
                sum(
                    (
                        (ln.actual_fees or Decimal(0))
                        + (ln.income.fees_total + ln.income.commission if ln.income else Decimal(0))
                        for ln in lines
                    ),
                    Decimal(0),
                )
            ),
        ],
    }
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def stamp(env: RecoEnv, items: Iterable[str], now: datetime) -> dict[str, Any]:
    """The ``freshness`` block of a card computed now on ``env``."""
    return {
        "computed_at": now.isoformat(),
        "engine_version": config.ENGINE_VERSION,
        "inputs_fingerprint": fingerprint(env, list(items), env.as_of),
        "as_of": env.as_of.isoformat(),
    }


def stale_reason(card: Mapping[str, Any], env: RecoEnv | None = None) -> str | None:
    """Why the stored card (or version) is out of date, or None when it is current."""
    block = card.get("freshness")
    if not block:
        return REASON_MISSING
    if block.get("engine_version") != config.ENGINE_VERSION:
        return REASON_ENGINE
    if env is not None:
        try:
            as_of = date.fromisoformat(block["as_of"])
        except (KeyError, ValueError):
            return REASON_MISSING
        items = (card.get("scope") or {}).get("product_ids") or []
        if fingerprint(env, items, as_of) != block.get("inputs_fingerprint"):
            return REASON_INPUTS
    return None


def card_stale_reason(card: Mapping[str, Any], env: RecoEnv | None = None) -> str | None:
    """The card is stale when it, or any of its versions, is."""
    reason = stale_reason(card, env)
    if reason:
        return reason
    items = (card.get("scope") or {}).get("product_ids") or []
    for v in card.get("versions") or []:
        if v.get("status") == "refused":
            continue
        block = {**v, "scope": {"product_ids": items}}
        reason = stale_reason(block, env)
        if reason:
            return reason
    return None


__all__ = ["card_stale_reason", "fingerprint", "stale_reason", "stamp"]
