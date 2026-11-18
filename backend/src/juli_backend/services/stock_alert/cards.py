"""What a stopped variation ("Ngừng theo dõi") does to the recommendation cards (Part S).

"Stopped" = a member switched it off (``settings.untracked_keys``); a variation that is off only by
default is not stopped and changes nothing here.

- Generation: a product whose every known variation is stopped gets no new card
  (``RecoEnv.stock_stopped``, read by ``generators.generate``); the builder warns when such a
  product is picked (``stock_warnings``).
- Open cards whose targets are ONLY stopped variations (the variations a card names in
  ``inputs.variations``; a whole-product card targets all of the product's variations, so it
  qualifies only when all of them are stopped): ``draft`` / ``sent`` / ``changes_requested`` /
  ``planned`` / ``approved`` (not started) are withdrawn (reason ``other``, by ``stock_alert``);
  ``executed`` (running / measuring) keeps running and its measurement, tagged
  ``stock_untracked`` ("Đã ngừng theo dõi"). A planned card in a confirmed plan cannot be
  withdrawn: it is tagged instead.
- On again: alerts and generation resume; a withdrawn card stays withdrawn; the tag is removed.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_PLANNED,
    STATUS_SENT,
)
from juli_backend.models.stock_alert import ShopeeSkuTracking, ShopeeStockHistory
from juli_backend.services.shopee_analytics.catalog import Catalog
from juli_backend.services.stock_alert.settings import sku_key, untracked_keys

logger = logging.getLogger(__name__)

TAG_KEY = "stock_untracked"
TAG_LABEL = "Đã ngừng theo dõi"
WITHDRAW_NOTE = "Đã ngừng theo dõi SKU"
WITHDRAW_BY = "stock_alert"
WITHDRAWABLE = (
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_CHANGES_REQUESTED,
    STATUS_PLANNED,
    STATUS_APPROVED,
)
OPEN = (*WITHDRAWABLE, STATUS_EXECUTED)


async def variation_keys(
    session: AsyncSession, shop_id: uuid.UUID, catalog: Catalog | None = None
) -> dict[str, set[str]]:
    """item id -> every variation key Juli knows (stock history, switches, catalogue)."""
    out: dict[str, set[str]] = {}
    hist = (
        await session.execute(
            select(ShopeeStockHistory.item_id, ShopeeStockHistory.variation_id)
            .where(ShopeeStockHistory.shop_id == shop_id)
            .distinct()
        )
    ).all()
    with_models = {h.item_id for h in hist if h.variation_id}
    for h in hist:
        if h.variation_id or h.item_id not in with_models:
            out.setdefault(h.item_id, set()).add(sku_key(h.item_id, h.variation_id))
    for t in (
        await session.execute(
            select(ShopeeSkuTracking.item_id, ShopeeSkuTracking.model_id).where(
                ShopeeSkuTracking.shop_id == shop_id
            )
        )
    ).all():
        out.setdefault(t.item_id, set()).add(sku_key(t.item_id, t.model_id))
    if catalog is not None:
        for item, keys in out.items():
            info = catalog.items.get(item)
            for v in info.variations if info else ():
                if v.variation_id:
                    keys.add(sku_key(item, v.variation_id))
    return out


def stopped_items(stopped: set[str], keys: Mapping[str, set[str]]) -> frozenset[str]:
    """Products whose every known variation is stopped (pure)."""
    return frozenset(item for item, ks in keys.items() if ks and ks <= stopped)


async def load_stopped(
    session: AsyncSession, shop_id: uuid.UUID, catalog: Catalog | None = None
) -> tuple[frozenset[str], set[str]]:
    """``(products fully stopped, stopped variation keys)``; both empty when nothing is stopped."""
    stopped = await untracked_keys(session, shop_id)
    if not stopped:
        return frozenset(), set()
    return stopped_items(stopped, await variation_keys(session, shop_id, catalog)), stopped


def _sku_to_key(catalog: Catalog | None, item: str, sku: str) -> str | None:
    info = catalog.items.get(item) if catalog else None
    for v in info.variations if info else ():
        if v.seller_sku == sku and v.variation_id:
            return sku_key(item, v.variation_id)
    return None


def targets_of(
    card: Mapping[str, Any], keys: Mapping[str, set[str]], catalog: Catalog | None
) -> set[str] | None:
    """The variation keys a card targets; None when Juli cannot tell (then nothing happens)."""
    items = [str(i) for i in (card.get("scope") or {}).get("product_ids") or []]
    if not items:
        return None
    named = [
        str(v["sku"])
        for v in (card.get("inputs") or {}).get("variations") or []
        if isinstance(v, Mapping) and v.get("sku")
    ]
    if named and len(items) == 1:
        found = {_sku_to_key(catalog, items[0], s) for s in named}
        return None if None in found else {k for k in found if k}
    out: set[str] = set()
    for item in items:
        ks = keys.get(item)
        if not ks:
            return None
        out |= ks
    return out


async def apply(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    catalog: Catalog | None = None,
) -> dict[str, int]:
    """Withdraw / tag / untag the open cards per the stopped variations (no commit)."""
    from juli_backend.services.shop_proposals.cycle import ProposalError
    from juli_backend.services.shopee_recommendations import service, store

    stopped = await untracked_keys(session, shop_id)
    keys = await variation_keys(session, shop_id, catalog)
    counts = {"withdrawn": 0, "tagged": 0, "untagged": 0}
    for p, card in await store.list_cards(session, shop_id, statuses=list(OPEN)):
        targets = targets_of(card, keys, catalog)
        only_stopped = bool(targets) and targets is not None and targets <= stopped
        meta = await store.card_meta(session, shop_id, p.id)
        if only_stopped and p.status in WITHDRAWABLE:
            try:
                await service.withdraw(
                    session,
                    shop_id,
                    p.id,
                    now=now,
                    reason_code="other",
                    note=WITHDRAW_NOTE,
                    by=WITHDRAW_BY,
                )
                counts["withdrawn"] += 1
                continue
            except ProposalError:
                pass  # a confirmed plan holds it: tag it like a running card
        if only_stopped and not meta.get(TAG_KEY):
            await store.set_meta(
                session, shop_id, p.id, {TAG_KEY: {"label": TAG_LABEL, "at": now.isoformat()}}
            )
            counts["tagged"] += 1
        elif not only_stopped and meta.get(TAG_KEY):
            await store.set_meta(session, shop_id, p.id, {TAG_KEY: None})
            counts["untagged"] += 1
    if any(counts.values()):
        logger.info("stock_alert_cards_applied", extra={"shop_id": str(shop_id), **counts})
    return counts


def stock_warnings(stopped: frozenset[str], items: list[str]) -> list[dict[str, Any]]:
    """The builder's warning when a picked product is stopped (pure)."""
    hit = [i for i in items if i in stopped]
    return (
        [{"type": "stock_untracked", "items": hit, "message": f"{TAG_LABEL} SKU này."}]
        if hit
        else []
    )


__all__ = [
    "TAG_KEY",
    "TAG_LABEL",
    "apply",
    "load_stopped",
    "stock_warnings",
    "stopped_items",
    "targets_of",
    "variation_keys",
]
