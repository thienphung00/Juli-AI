"""Pooled cells: who takes part in a figure pooled across shops (D14, D15, D17; ADR-116 §3).

Every figure pooled across shops -- the Ops card-group EB prior
(``action_cards.card_groups.apply_pooled_eb``) and the D30.3 fleet calibration factor
(``lever_flows.measurement.fleet_calibration_stats``) -- follows the same three rules:

- **D11 / D17 (owner, 2026-10-27).** Only shops holding an open ``pooled_training`` grant
  contribute (the draws are filtered in SQL: migration 107), and only they receive the
  pooled figure: a shop without the grant neither borrows nor lends. ``pooled_training``
  is granted only to Juli's own shops: the TikTok Shop Developer ToS §2.7(g) and the
  Partner Center ToS §3.8(e) forbid aggregating seller API data for Juli's own purposes,
  and the Shopee ToS §6.2(c) needs Shopee's written consent for derived seller-performance
  aggregates. D14 / D15 below are defence in depth.
- **D14.** A pooled cell is used only when at least :data:`MIN_CONTRIBUTING_SHOPS`
  consenting shops contribute to it AND no single shop holds more than
  :data:`MAX_SHOP_SHARE` of the cell's weight. Otherwise the next wider cell is tried; if
  that is short too there is no pooled figure (own data / the uncalibrated default). The
  weight is the unit each estimator already counts: day-14 results (``readings``) for the
  fleet factor, measured group comparisons (draws) for the Ops prior.
- **D15.** Each computation names its contributing set: the contributing shops' ids,
  the SHA-256 of the sorted list and the shop count of each cell used
  (:class:`ContributingSet`). The id is the shop's UUID (``shops.id``): an opaque
  internal key that carries no name, joins straight to ``data_use_consents`` to prove
  every contributor held a grant at the time, and stays stable across secret rotation
  (a keyed HMAC would need a new purpose key and break that join). Shop names are never
  written. A computation whose result is persisted (the nightly card plan) writes one
  ``pooled_contributor_sets`` row (migration 107, ``ops_only``); a query-time one (the
  Ops groups page) logs ``pooled_contributor_set`` with the same fields.

The thresholds live here and nowhere else.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: D14: fewest consenting shops a pooled cell needs.
MIN_CONTRIBUTING_SHOPS = 5
#: D14: the largest share of a cell's weight one shop may hold (strictly more -> unused).
MAX_SHOP_SHARE = 0.5

#: ``pooled_contributor_sets.figure`` values (and the log line's ``figure``).
FIGURE_FLEET_CALIBRATION = "fleet_calibration"
FIGURE_OPS_GROUP_PRIOR = "ops_group_prior"
FIGURES: tuple[str, ...] = (FIGURE_FLEET_CALIBRATION, FIGURE_OPS_GROUP_PRIOR)


@dataclass(frozen=True)
class CellCheck:
    """One candidate cell measured against D14."""

    key: str
    shops: int
    max_share: float
    shop_ids: tuple[str, ...]

    @property
    def active(self) -> bool:
        return self.shops >= MIN_CONTRIBUTING_SHOPS and self.max_share <= MAX_SHOP_SHARE


def check_cell(key: str, weights: Mapping[str, float]) -> CellCheck:
    """D14 for one cell: ``weights`` is shop id -> that shop's weight in the cell."""
    positive = {shop: float(w) for shop, w in weights.items() if w and w > 0}
    total = sum(positive.values())
    share = max(positive.values()) / total if total > 0 else 1.0
    return CellCheck(key, len(positive), share, tuple(sorted(positive)))


def first_active(ladder: Iterable[tuple[str, Mapping[str, float]]]) -> CellCheck | None:
    """The narrowest cell of ``ladder`` (narrow -> wide) that passes D14, else ``None``."""
    for key, weights in ladder:
        cell = check_cell(key, weights)
        if cell.active:
            return cell
    return None


@dataclass(frozen=True)
class ContributingSet:
    """D15: the shops behind one pooled computation, and the cells it used."""

    figure: str
    shop_ids: tuple[str, ...]
    sha256: str
    cells: dict[str, int] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.shop_ids

    def to_json(self) -> dict[str, Any]:
        return {
            "figure": self.figure,
            "shop_ids": list(self.shop_ids),
            "sha256": self.sha256,
            "cells": dict(self.cells),
        }


def contributors_sha256(shop_ids: Iterable[str]) -> str:
    """SHA-256 (hex) of the sorted ids joined by ``\\n`` -- the same set, the same hash."""
    return hashlib.sha256("\n".join(sorted(set(shop_ids))).encode("utf-8")).hexdigest()


def contributing_set(figure: str, used: Sequence[CellCheck]) -> ContributingSet:
    """The union of the shops of every cell ``used``, with each cell's shop count."""
    ids = sorted({shop for cell in used for shop in cell.shop_ids})
    cells = {cell.key: cell.shops for cell in sorted(used, key=lambda c: c.key)}
    return ContributingSet(figure, tuple(ids), contributors_sha256(ids), cells)


def log_contributing_set(
    contributors: ContributingSet, *, applied_shop_id: uuid.UUID | str, persisted: bool
) -> None:
    """The structured audit line (ids, hash and counts only -- never a shop name)."""
    logger.info(
        "pooled_contributor_set figure=%s applied_shop_id=%s shops=%d sha256=%s persisted=%s",
        contributors.figure,
        applied_shop_id,
        len(contributors.shop_ids),
        contributors.sha256,
        persisted,
        extra={
            "applied_shop_id": str(applied_shop_id),
            "persisted": persisted,
            **contributors.to_json(),
        },
    )


async def record_contributing_set(
    session: AsyncSession,
    contributors: ContributingSet,
    *,
    applied_shop_id: uuid.UUID,
    computed_at: datetime | None = None,
) -> None:
    """Append the ``pooled_contributor_sets`` row (D15) and log it.

    ``ops_only`` table (migration 107): on Postgres the caller must be inside an
    ``ops_role`` block (``juli_ops`` has SELECT, INSERT; ``juli_app`` nothing).
    """
    from juli_backend.models.consent import PooledContributorSet

    session.add(
        PooledContributorSet(
            figure=contributors.figure,
            applied_shop_id=applied_shop_id,
            contributor_shop_ids=list(contributors.shop_ids),
            contributors_sha256=contributors.sha256,
            cells=dict(contributors.cells),
            computed_at=computed_at or datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await session.flush()
    log_contributing_set(contributors, applied_shop_id=applied_shop_id, persisted=True)


__all__ = [
    "FIGURES",
    "FIGURE_FLEET_CALIBRATION",
    "FIGURE_OPS_GROUP_PRIOR",
    "MAX_SHOP_SHARE",
    "MIN_CONTRIBUTING_SHOPS",
    "CellCheck",
    "ContributingSet",
    "check_cell",
    "contributing_set",
    "contributors_sha256",
    "first_active",
    "log_contributing_set",
    "record_contributing_set",
]
