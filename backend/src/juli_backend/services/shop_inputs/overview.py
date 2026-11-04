"""What the Thông số shop screen shows before any upload: catalogue size, the SKUs on the
1/3 cost fallback, the targets set so far, and which SKUs have a version history."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import ShopRuleVersion
from juli_backend.services.shop_inputs import kol_samples
from juli_backend.services.shop_inputs.catalogue import (
    load_catalogue,
    load_current,
    split_scope,
)
from juli_backend.services.shop_inputs.fallback import (
    OWNER_DEFAULT_GROSS_MARGIN_PCT,
    cost_fallbacks,
)
from juli_backend.services.shop_inputs.importer import SUGGESTED_REASONS
from juli_backend.services.shop_rules.rules import SKU_INPUT_RULE_KEYS

MAX_FALLBACK_ROWS = 500


def _number(value: Any) -> Any:
    return float(value) if value is not None else None


async def build_overview(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    catalogue = await load_catalogue(session, shop_id)
    current = await load_current(session, shop_id)
    fallbacks = await cost_fallbacks(session, shop_id)
    with_cost = sum(
        1
        for s in catalogue
        if "sku_cost" in current.per_sku.get(s.scope, {}) or s.item_id in current.product_cost
    )
    sent = await kol_samples.load_samples(session, shop_id)
    by_scope = {c.scope: c for c in catalogue}
    samples = []
    for (key, sku_scope), shipments in sorted(sent.items()):
        sku = by_scope.get(sku_scope)
        unit = kol_samples.unit_cost_from_inputs(current, sku, sku_scope, split_scope(sku_scope)[0])
        cost = kol_samples.sample_cost(shipments, unit)
        samples.append(
            {
                "scope_ref": kol_samples.scope_ref(key, sku_scope),
                "kol_key": key,
                "handle": shipments[0].handle,
                "item_id": split_scope(sku_scope)[0],
                "sku": (sku.sku if sku and sku.sku else sku_scope),
                "shipments": [sh.json() for sh in shipments],
                "sample_cost": _number(cost),
                "cost_label": unit.label if unit else "chưa có giá vốn",
            }
        )
    return {
        "samples": {
            "pairs": len(samples),
            "shipments": sum(len(x["shipments"]) for x in samples),
            "items": samples[:MAX_FALLBACK_ROWS],
        },
        "catalogue": {
            "sku_rows": len(catalogue),
            "items": len({s.item_id for s in catalogue}),
            "with_cost": with_cost,
        },
        "cost_fallback": {
            "count": len(fallbacks),
            "assumed_share": "1/3",
            "margin_pct": _number(
                fallbacks[0].margin_pct if fallbacks else OWNER_DEFAULT_GROSS_MARGIN_PCT
            ),
            "source": fallbacks[0].source if fallbacks else "assumed_one_third",
            "skus": [
                {
                    "item_id": f.item_id,
                    "variation_id": f.variation_id,
                    "sku": f.sku,
                    "name": f.name,
                    "list_price": _number(f.list_price),
                    "assumed_cost": _number(f.assumed_cost),
                }
                for f in fallbacks[:MAX_FALLBACK_ROWS]
            ],
        },
        "months": [
            {"month": month, "values": values} for month, values in sorted(current.monthly.items())
        ],
        "reasons": list(SUGGESTED_REASONS),
    }


async def versions_index(session: AsyncSession, shop_id: uuid.UUID) -> list[dict[str, Any]]:
    """SKUs with any version history, for the per-SKU pills."""
    scopes = (
        (
            await session.execute(
                select(ShopRuleVersion.scope_ref)
                .where(
                    ShopRuleVersion.shop_id == shop_id,
                    ShopRuleVersion.rule_key.in_(SKU_INPUT_RULE_KEYS),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    by_scope = {s.scope: s for s in await load_catalogue(session, shop_id)}
    out = []
    for scope in sorted(scopes):
        sku = by_scope.get(scope)
        item_id, variation_id = split_scope(scope)
        out.append(
            {
                "scope_ref": scope,
                "item_id": item_id,
                "variation_id": variation_id,
                "sku": (sku.sku if sku and sku.sku else item_id),
                "name": sku.name if sku else "",
            }
        )
    return out
