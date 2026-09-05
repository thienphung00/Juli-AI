"""Persist one entity with unique defaults; override only what the test is about.

Every builder takes the session, adds the row and flushes, so ids and server
defaults are populated when it returns. Unique columns (``User.phone``,
``Shop.tiktok_shop_id``) draw from a process-wide counter, so two builders in
one test never collide and no test needs to invent a phone number.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    Order,
    OrderItem,
    Product,
    Shop,
    TikTokCredential,
    User,
    WorkflowRun,
    WorkflowRunEvent,
)

_sequence = itertools.count(1)


def next_unique(prefix: str) -> str:
    """``"<prefix>-<n>"`` with a process-unique ``n``."""
    return f"{prefix}-{next(_sequence)}"


def utc_now_naive() -> datetime:
    """What repositories write into ``TIMESTAMP WITHOUT TIME ZONE`` columns (#1138)."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _persist(session: AsyncSession, entity: Any) -> Any:
    session.add(entity)
    await session.flush()
    return entity


async def make_user(session: AsyncSession, **overrides: Any) -> User:
    values: dict[str, Any] = {"id": uuid.uuid4(), "phone": f"+8490{next(_sequence):07d}"}
    values.update(overrides)
    return await _persist(session, User(**values))


async def make_shop(session: AsyncSession, user: User, **overrides: Any) -> Shop:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": user.id,
        "shop_name": next_unique("Shop"),
        "tiktok_shop_id": next_unique("tiktok-shop"),
    }
    values.update(overrides)
    return await _persist(session, Shop(**values))


async def make_tenant(session: AsyncSession, **shop_overrides: Any) -> tuple[User, Shop]:
    """A user and one shop they own -- the unit of tenant isolation."""
    user = await make_user(session)
    shop = await make_shop(session, user, **shop_overrides)
    return user, shop


async def make_product(session: AsyncSession, shop: Shop, **overrides: Any) -> Product:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "shop_id": shop.id,
        "tiktok_product_id": next_unique("prod"),
        "name": "Widget",
        "status": "ACTIVE",
        "revenue": Decimal("0"),
        "units_sold": 0,
        "update_time": utc_now_naive(),
    }
    values.update(overrides)
    return await _persist(session, Product(**values))


async def make_order(session: AsyncSession, shop: Shop, **overrides: Any) -> Order:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "shop_id": shop.id,
        "tiktok_order_id": next_unique("order"),
        "status": "AWAITING_SHIPMENT",
        "total_amount": Decimal("100.00"),
        "currency": "VND",
        "update_time": utc_now_naive(),
    }
    values.update(overrides)
    return await _persist(session, Order(**values))


async def make_order_item(
    session: AsyncSession,
    shop: Shop,
    *,
    tiktok_product_id: str,
    quantity: int = 1,
    line_total: Decimal = Decimal("100.00"),
    **overrides: Any,
) -> OrderItem:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "shop_id": shop.id,
        "order_id": uuid.uuid4(),
        "tiktok_order_id": next_unique("order"),
        "tiktok_product_id": tiktok_product_id,
        "tiktok_sku_id": next_unique("sku"),
        "quantity": quantity,
        "unit_price": line_total / quantity,
        "line_total": line_total,
        "update_time": utc_now_naive(),
    }
    values.update(overrides)
    return await _persist(session, OrderItem(**values))


async def make_credential(session: AsyncSession, shop: Shop, **overrides: Any) -> TikTokCredential:
    """A raw credential row. Tokens are stored as given -- use ``TikTokCredentialRepo.create``
    when the test needs them encrypted the way production writes them."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "shop_id": shop.id,
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "token_expires_at": utc_now_naive() + timedelta(hours=1),
    }
    values.update(overrides)
    return await _persist(session, TikTokCredential(**values))


async def make_workflow_run(
    session: AsyncSession, shop: Shop, *, product: Product | None = None, **overrides: Any
) -> WorkflowRun:
    """A run bound to ``product`` (created when omitted), ``running`` by default."""
    if product is None:
        product = await make_product(session, shop)
    values: dict[str, Any] = {
        "shop_id": shop.id,
        "product_id": product.id,
        "state": {},
        "status": "running",
        "prompt_version": "optimize_product.v1",
        "prompt_sha256": "a" * 64,
    }
    values.update(overrides)
    return await _persist(session, WorkflowRun(**values))


async def make_run_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    sequence_number: int,
    *,
    event_type: str = "workflow.status",
    payload: dict[str, Any] | None = None,
) -> WorkflowRunEvent:
    return await _persist(
        session,
        WorkflowRunEvent(
            workflow_run_id=run_id,
            sequence_number=sequence_number,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            payload=payload
            if payload is not None
            else {"phase_narration": f"seq-{sequence_number}"},
            v=1,
        ),
    )


__all__ = [
    "make_credential",
    "make_order",
    "make_order_item",
    "make_product",
    "make_run_event",
    "make_shop",
    "make_tenant",
    "make_user",
    "make_workflow_run",
    "next_unique",
    "utc_now_naive",
]
