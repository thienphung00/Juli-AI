"""Ops reads of the Shopee funnel's accuracy checks (P98 / ADR-122 d.11.3 and d.11.4). Read only.

- :func:`funnel_check` -- ``funnel_check.check_days`` over the last N days; the mismatches as rows.
- :func:`prediction_coverage` -- per family (``change_kind``) how many scored results fell inside
  the predicted low-high range. What exists today: ``shopee_reco_calibrations`` keeps, per
  (shop, change_kind, metric), ``coverage_n`` (usable scored results) and ``coverage_hits`` (of
  those, inside the range). The per-prediction low / high are frozen on ``card_events`` and are
  not re-read here: only what the calibration job stored is reported, nothing is recomputed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_recommendations import ShopeeRecoCalibration
from juli_backend.services.shopee_analytics import funnel_check

#: ADR-122 d.11.4: the share of results that should land inside low-high
COVERAGE_TARGET = 0.8


def _num(value: Any) -> str | None:
    return None if value is None else str(value)


def mismatch_json(m: funnel_check.Mismatch) -> dict[str, Any]:
    gap = m.gap_pct
    scope = "product" if m.item_id is not None else "shop"
    return {
        "kind": m.kind,
        "day": m.day.isoformat(),
        "scope": scope,
        "item_id": m.item_id,
        "source": m.source,
        "metric": m.metric,
        "expected": _num(m.expected),
        "actual": _num(m.stored),
        "gap_pct": None if gap is None else round(float(gap), 2),
    }


async def funnel_check_report(
    session: AsyncSession, shop_id: uuid.UUID, *, days: int, as_of: date
) -> dict[str, Any]:
    window = [as_of - timedelta(days=i) for i in range(days)]
    found = await funnel_check.check_days(session, shop_id, window)
    rows = [mismatch_json(m) for m in found]
    rows.sort(key=lambda r: (r["day"], r["kind"], r["metric"]), reverse=False)
    return {
        "days": days,
        "from": min(window).isoformat(),
        "to": max(window).isoformat(),
        "tolerance_pct": float(funnel_check.TOLERANCE * 100),
        "mismatches": rows,
    }


def _share(hits: int, n: int) -> float | None:
    return None if n == 0 else round(hits / n, 3)


async def prediction_coverage(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    t = ShopeeRecoCalibration
    rows = list(
        (
            await session.execute(
                select(t).where(t.shop_id == shop_id).order_by(t.change_kind, t.metric)
            )
        ).scalars()
    )
    by_family: dict[str, list[ShopeeRecoCalibration]] = defaultdict(list)
    for r in rows:
        by_family[r.change_kind].append(r)
    families = []
    for family, items in sorted(by_family.items()):
        n = sum(r.coverage_n for r in items)
        hits = sum(r.coverage_hits for r in items)
        families.append(
            {
                "family": family,
                "scored": n,
                "inside": hits,
                "coverage": _share(hits, n),
                "metrics": [
                    {
                        "metric": r.metric,
                        "scored": r.coverage_n,
                        "inside": r.coverage_hits,
                        "coverage": _share(r.coverage_hits, r.coverage_n),
                        "range_scale": float(r.range_scale),
                    }
                    for r in items
                ],
            }
        )
    return {
        "target": COVERAGE_TARGET,
        "source": "shopee_reco_calibrations",
        "families": families,
    }
