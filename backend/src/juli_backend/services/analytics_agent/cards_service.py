"""`CardEnginePort` over Juli's recommendation engine (read-only; nothing is persisted).

G3: the engine's own candidate for (kind, item), or the kind's generator fitted to the floors; then
`versions.build_versions` and `result_store.compute_many` (the same path as a backend card), never
persisted: the session is read-only and rolled back.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from juli_backend.services.analytics_agent.data_service import SessionFactory


class ServiceCardEngine:
    def __init__(self, factory: SessionFactory, shop_id: uuid.UUID) -> None:
        self._f, self.shop = factory, shop_id
        self._cache: dict[date, tuple[Any, list[Any]]] = {}

    def allowed_kinds(self, metric: str) -> tuple[str, ...]:
        from juli_backend.services.shopee_recommendations.kinds import allowed_for_metric

        return allowed_for_metric(metric)

    def needs_item(self, kind: str) -> bool:
        """Does the kind's generator need a product? An unknown kind cannot be filled at all."""
        from juli_backend.services.shopee_recommendations.generators import GENERATORS

        return GENERATORS[kind][1] if kind in GENERATORS else True

    async def _env(self, as_of: date) -> tuple[Any, list[Any]]:
        if as_of in self._cache:
            return self._cache[as_of]
        from juli_backend.services.shopee_recommendations.loader import load_env
        from juli_backend.services.shopee_recommendations.service import build_candidates

        async with self._f() as s:
            try:
                env = await load_env(
                    s, self.shop, as_of=as_of, now=datetime(as_of.year, as_of.month, as_of.day, 12)
                )
                cands, _crit = await build_candidates(s, self.shop, env) if env else ([], {})
            finally:
                await s.rollback()
        self._cache[as_of] = (env, cands)
        return env, cands

    async def engine_card(self, kind: str, item: str | None, as_of: date) -> dict[str, Any]:
        from juli_backend.services.shopee_recommendations import result_store, versions
        from juli_backend.services.shopee_recommendations.cards import build_card

        env, cands = await self._env(as_of)
        if env is None:
            return {"ok": False, "reason": "no_shopee_data"}
        mine = [c for c in cands if c.kind == kind and (item is None or item in _items(c))]
        source = "engine_run"
        if not mine:
            from juli_backend.services.shopee_recommendations.generators import GENERATORS
            from juli_backend.services.shopee_recommendations.service import (
                apply_acceptance_defaults,
            )

            if kind not in GENERATORS:
                return {"ok": False, "reason": "no_generator_for_kind"}
            gen, needs_item = GENERATORS[kind]
            if needs_item and not item:
                return {"ok": False, "reason": "kind_needs_a_product"}
            try:
                mine = gen(env, None, item or "")
            except Exception as exc:  # a generator that needs a critical item
                return {"ok": False, "reason": f"generator_error:{type(exc).__name__}"}
            if not mine:
                return {"ok": False, "reason": "generator_returned_none"}
            for c in mine:
                apply_acceptance_defaults(env, c)
            source = "generator"
        now = datetime(as_of.year, as_of.month, as_of.day, 12)
        card = build_card(env, mine[0], now=now)
        if card is None:
            return {"ok": False, "reason": "engine_refused"}
        card["versions"] = versions.build_versions(env, mine[0], card, now=now)
        async with self._f() as s:
            try:
                blocks = await result_store.compute_many(
                    s, self.shop, env, [result_store.Job(card)], now=now
                )
                result_store.write_into(card, blocks[0])
            finally:
                await s.rollback()
        return {"ok": True, "kind": kind, "item": item, "source": source, "card": _brief(card)}

    async def build_custom(self, spec: dict[str, Any], as_of: date) -> dict[str, Any]:
        """A card from a typed Tự tạo spec (the builder's own validation and translation, then the
        same evaluation as `engine_card`). Reads only; nothing is saved."""
        from pydantic import TypeAdapter, ValidationError

        from juli_backend.services.shopee_builder import service as bsvc
        from juli_backend.services.shopee_builder import specs as sp
        from juli_backend.services.shopee_builder.context import SpecRefused
        from juli_backend.services.shopee_builder.translate import to_variant
        from juli_backend.services.shopee_recommendations import manual, result_store, versions

        try:
            parsed: Any = TypeAdapter(sp.VersionSpec).validate_python(spec)
        except ValidationError:
            return {"ok": False, "reason": "invalid_spec"}
        now = datetime(as_of.year, as_of.month, as_of.day, 12)
        async with self._f() as s:
            try:
                ctx = await bsvc.build_context(s, self.shop, [parsed], as_of=as_of, now=now)
                try:
                    tr = to_variant(parsed, ctx)
                except SpecRefused as exc:
                    return {"ok": False, "reason": exc.code}
                card, why = manual.build_variant(ctx.env, tr.variant, now=now)
                if card is None:
                    return {"ok": False, "reason": (why or {}).get("code", "refused")}
                cand = manual.candidate_of(tr.variant)
                card["versions"] = versions.build_versions(ctx.env, cand, card, now=now)
                blocks = await result_store.compute_many(
                    s, self.shop, ctx.env, [result_store.Job(card)], now=now
                )
                result_store.write_into(card, blocks[0])
            finally:
                await s.rollback()
        return {"ok": True, "kind": tr.card_kind, "card": _brief(card)}


def _items(c: Any) -> set[str]:
    out: set[str] = set()
    for k in ("item", "item_id", "items", "targets"):
        v = getattr(c, k, None)
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, (list, tuple, set)):
            out |= {x if isinstance(x, str) else str(getattr(x, "item_id", x)) for x in v}
    inp = getattr(c, "inputs", None) or {}
    for k in ("item_id", "item_ids", "items"):
        v = inp.get(k) if isinstance(inp, dict) else None
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, list):
            out |= {str(x) for x in v}
    return out


def _brief(card: dict[str, Any]) -> dict[str, Any]:
    keep = {
        k: card.get(k)
        for k in (
            "title",
            "family",
            "kind",
            "subject",
            "target",
            "metric",
            "inputs",
            "certain",
            "predicted",
            "plan",
            "floors",
            "warnings",
        )
    }
    keep["versions"] = [
        {k: v.get(k) for k in ("label", "inputs", "result", "recommended", "default")}
        for v in card.get("versions") or []
    ]
    return json.loads(json.dumps(keep, default=str, ensure_ascii=False))
