"""Which recommendations an input change re-runs, and the hook that re-runs them.

A change to a SKU's cost, packaging, discount cap, stock, restock date, group or status
affects the OPEN proposals (``shop_proposals``) and active cards (``action_cards``) of its
item. A change to a monthly target (margin, marketing cap, ...) is shop-wide: it moves the
operating floor and the spend cap every price / voucher / ads proposal is judged against,
so those kinds count too. Everything else stays as it is.

There is no generator that re-runs proposals yet (step 8). ``mark_stale`` is the seam it
will consume: it calls the hooks registered with ``register_recompute_hook`` inside the
caller's transaction. With none registered it does nothing and the apply response still
tells the seller how many proposals will be recomputed and for which items.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_SENT,
    ShopProposal,
)

OPEN_PROPOSAL_STATUSES: tuple[str, ...] = (
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_CHANGES_REQUESTED,
    STATUS_APPROVED,
)
#: Proposal kinds judged against the operating floor / spend cap (shop-wide targets).
TARGET_SENSITIVE_KINDS: tuple[str, ...] = ("price", "voucher", "flash_sale", "ads", "bundle")
ACTIVE_CARD_STATUS = "active"
PRODUCT_SUBJECT = "product"
STALE_REASON = "seller_inputs_changed"


@dataclass(frozen=True)
class AffectedRecommendations:
    proposals: int
    action_cards: int
    item_ids: tuple[str, ...]
    shop_wide: bool

    @property
    def total(self) -> int:
        return self.proposals + self.action_cards


async def affected_recommendations(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    item_ids: Iterable[str],
    shop_wide: bool = False,
) -> AffectedRecommendations:
    """Count the open recommendations whose item is in ``item_ids`` (plus, shop-wide, the
    target-sensitive kinds)."""
    items = tuple(sorted(set(item_ids)))
    if not items and not shop_wide:
        return AffectedRecommendations(0, 0, (), False)
    conditions = []
    if items:
        conditions.append(ShopProposal.item_id.in_(items))
    if shop_wide:
        conditions.append(ShopProposal.kind.in_(TARGET_SENSITIVE_KINDS))
    proposals = (
        await session.execute(
            select(func.count())
            .select_from(ShopProposal)
            .where(
                ShopProposal.shop_id == shop_id,
                ShopProposal.status.in_(OPEN_PROPOSAL_STATUSES),
                or_(*conditions),
            )
        )
    ).scalar_one()
    cards = 0
    if items:
        cards = (
            await session.execute(
                select(func.count())
                .select_from(ActionCard)
                .where(
                    ActionCard.shop_id == shop_id,
                    and_(
                        ActionCard.status == ACTIVE_CARD_STATUS,
                        ActionCard.subject_type == PRODUCT_SUBJECT,
                        ActionCard.subject_id.in_(items),
                    ),
                )
            )
        ).scalar_one()
    return AffectedRecommendations(int(proposals), int(cards), items, shop_wide)


@dataclass(frozen=True)
class StaleRequest:
    """What the recommendation generator is asked to recompute."""

    item_ids: tuple[str, ...]
    shop_wide: bool
    reason: str
    changed_at: datetime
    import_file_hash: str | None = None


RecomputeHook = Callable[[AsyncSession, uuid.UUID, StaleRequest], Awaitable[None]]
_HOOKS: list[RecomputeHook] = []


def register_recompute_hook(hook: RecomputeHook) -> None:
    """The step-8 generator registers here; registering twice is a no-op."""
    if hook not in _HOOKS:
        _HOOKS.append(hook)


def unregister_recompute_hook(hook: RecomputeHook) -> None:
    if hook in _HOOKS:
        _HOOKS.remove(hook)


async def mark_stale(session: AsyncSession, shop_id: uuid.UUID, request: StaleRequest) -> int:
    """Run the registered hooks in the caller's transaction; returns how many ran."""
    for hook in tuple(_HOOKS):
        await hook(session, shop_id, request)
    return len(_HOOKS)
