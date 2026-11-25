"""`CardEnginePort` over Juli's recommendation engine (read-only; no card is persisted).

batch-1124-c-data (OPP): one card path. `engine_card` reads the stored opportunity of the kind (and
product) from the daily run, or runs `opportunities.generate_for` for that product (the daily
run's own pipeline, saving only opportunity rows) and reads the row it made; it never runs one
generator by itself. `draft_card` then rebuilds the stored opportunity's card read-only (versions
and results, `versions` + `result_store.compute_many`), and a refused or absent opportunity answers
with its reason.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from juli_backend.services.analytics_agent.data_service import SessionFactory


class ServiceCardEngine:
    def __init__(
        self,
        factory: SessionFactory,
        shop_id: uuid.UUID,
        write_factory: SessionFactory | None = None,
    ) -> None:
        """``factory`` is the read session factory; ``write_factory`` is the primary one, used
        only to store the on-demand opportunity rows (defaults to ``factory``)."""
        self._f, self.shop = factory, shop_id
        self._wf = write_factory or factory

    def allowed_kinds(self, metric: str) -> tuple[str, ...]:
        from juli_backend.services.shopee_recommendations.kinds import allowed_for_metric

        return allowed_for_metric(metric)

    def needs_item(self, kind: str) -> bool:
        """Does the kind's opportunities come per product? The shop-wide kinds do not."""
        from juli_backend.services.shopee_recommendations.generators import GENERATORS
        from juli_backend.services.shopee_recommendations.opportunities import SHOP_KIND_REFUSALS

        if kind in SHOP_KIND_REFUSALS:
            return False
        return GENERATORS[kind][1] if kind in GENERATORS else True

    async def engine_card(self, kind: str, item: str | None, as_of: date) -> dict[str, Any]:
        from juli_backend.services.shopee_recommendations import opportunities as opp

        now = datetime(as_of.year, as_of.month, as_of.day, 12)
        async with self._f() as s:
            try:
                rows = await opp.list_opportunities(
                    s, self.shop, kind=kind, item_id=item, run_date=opp.run_day(now)
                )
                rows = [r for r in rows if item is not None or r.scope == "shop"]
            finally:
                await s.rollback()
        if not rows:  # on demand: the daily pipeline for this product, rows stored on the primary
            rows = [
                r
                for r in await opp.generate_for_stored(
                    self._wf, self.shop, [item] if item else [], now=now
                )
                if r.kind == kind
            ]
        if not rows:
            return {"ok": False, "reason": opp.REASON_NO_OPPORTUNITY}
        row = rows[0]
        if row.outcome == opp.REFUSED:
            return {"ok": False, "reason": row.reason or "engine_refused"}
        async with self._f() as s:
            try:
                out = await opp.draft_card(s, self.shop, row.id, now=now)
            finally:
                await s.rollback()
        if not out.get("ok"):
            return {"ok": False, "reason": out.get("reason") or "engine_refused"}
        return {
            "ok": True,
            "kind": kind,
            "item": item,
            "source": "opportunity",
            "outcome": row.outcome,
            "opportunity_id": str(row.id),
            "card": _brief(out["card"]),
        }

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
