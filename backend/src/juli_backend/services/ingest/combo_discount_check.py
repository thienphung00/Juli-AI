"""batch-1124-b CONN (owner Q4): a check, never a change, of the combo discount the Connector posts.

Connector 0.3.36 posts each combo (Combo Khuyến Mãi) line's ``bundle_discount`` as
``(page list price - its share of the combo price) x qty``, with the line's ``extra``
``{bundle_deal_id, list_price}``. When the shop's combo settings (``platform_promotions``,
``promo_type = bundle``, ``extra.discount_type = pct``) give that combo's percent tiers, the tier
the combo's quantity reaches gives an expected discount ``Σ list x qty x percent``. A combo whose
posted discount differs from it by more than rounding is LOGGED (``order_line_combo_discount_
mismatch``: ids and amounts only); the stored lines are never changed.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.services.ingest.schemas import SHOPEE_PROMO_TYPES, ShopeeOrderLineRow

logger = logging.getLogger(__name__)

#: VND per combo line the posted discount may differ from the tier's (the line split rounds).
TOLERANCE_PER_LINE = Decimal(1)
_CENT = Decimal("0.01")
_BUNDLE = SHOPEE_PROMO_TYPES["Combo Khuyến Mãi"]


@dataclass(frozen=True)
class ComboMismatch:
    order_ref: str
    combo_id: int
    expected: Decimal
    posted: Decimal


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    return Decimal(str(value))


def combo_discount_mismatches(
    rows: Iterable[ShopeeOrderLineRow], percent_tiers: Mapping[int, list[tuple[int, Decimal]]]
) -> list[ComboMismatch]:
    """The combos (per order) whose posted ``bundle_discount`` is not ``Σ list x qty x percent`` of
    the percent tier their quantity reaches. A combo without a list price, without percent tiers
    or below its first tier is not checked."""
    groups: dict[tuple[str, int], list[ShopeeOrderLineRow]] = defaultdict(list)
    for row in rows:
        combo = _number(row.extra.get("bundle_deal_id"))
        if row.promo_kind != "bundle" or combo is None:
            continue
        if _number(row.extra.get("list_price")) is None:
            continue
        groups[(row.order_ref, int(combo))].append(row)
    out: list[ComboMismatch] = []
    for (order_ref, combo_id), lines in groups.items():
        tiers = percent_tiers.get(combo_id)
        if not tiers:
            continue
        qty = sum(int(line.qty) for line in lines)
        reached = [percent for need, percent in sorted(tiers) if need <= qty]
        if not reached:
            continue
        listed = sum(
            (_number(line.extra.get("list_price")) or Decimal(0)) * line.qty for line in lines
        )
        expected = (listed * reached[-1] / 100).quantize(_CENT)
        posted = sum((line.bundle_discount for line in lines), Decimal(0)).quantize(_CENT)
        if abs(expected - posted) > TOLERANCE_PER_LINE * len(lines):
            out.append(ComboMismatch(order_ref, combo_id, expected, posted))
    return out


async def _percent_tiers(
    session: AsyncSession, shop_id: Any, platform: str, combo_ids: set[int]
) -> dict[int, list[tuple[int, Decimal]]]:
    """The newest percent tiers ``[(qty, percent)]`` the shop's combo settings hold per combo id."""
    found = await session.execute(
        select(PlatformPromotion.extra, PlatformPromotion.period_end)
        .where(
            PlatformPromotion.shop_id == shop_id,
            PlatformPromotion.platform == platform,
            PlatformPromotion.promo_type == _BUNDLE,
        )
        .order_by(PlatformPromotion.period_end)
    )
    out: dict[int, list[tuple[int, Decimal]]] = {}
    for extra, _ in found:
        combo = _number((extra or {}).get("combo_id"))
        if combo is None or int(combo) not in combo_ids or extra.get("discount_type") != "pct":
            continue
        tiers = [
            (int(t["qty"]), value)
            for t in extra.get("tiers") or []
            if isinstance(t, dict)
            and isinstance(t.get("qty"), int)
            and (value := _number(t.get("value"))) is not None
        ]
        if tiers:
            out[int(combo)] = tiers  # ordered by period_end: the newest snapshot wins
    return out


async def log_combo_discount_mismatches(
    session: AsyncSession, shop_id: Any, platform: str, rows: list[ShopeeOrderLineRow]
) -> int:
    """Log each combo whose posted discount misses its percent tier; returns how many."""
    combo_ids = {
        int(combo)
        for row in rows
        if row.promo_kind == "bundle"
        and (combo := _number(row.extra.get("bundle_deal_id"))) is not None
        and _number(row.extra.get("list_price")) is not None
    }
    if not combo_ids:
        return 0
    tiers = await _percent_tiers(session, shop_id, platform, combo_ids)
    mismatches = combo_discount_mismatches(rows, tiers)
    for miss in mismatches:
        logger.warning(
            "order_line_combo_discount_mismatch",
            extra={
                "shop_id": str(shop_id),
                "order_ref": miss.order_ref,
                "combo_id": miss.combo_id,
                "expected": str(miss.expected),
                "posted": str(miss.posted),
            },
        )
    return len(mismatches)
