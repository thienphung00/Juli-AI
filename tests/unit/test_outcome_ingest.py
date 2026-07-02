"""Outcome feedback loop — Issue #94 (P1-3).

AC2 → test_ac2_duplicate_idempotency_key_skips_edge_rewrite
AC3 → test_ac3_calibration_weight_reflects_gmv_delta
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.catalog.domain.feedback import (
    compute_calibration_weight,
    ingest_campaign_outcome,
)
from backend.database.models import Creator, Shop, User
from backend.database.repos import GraphRepo


def _user(uid: uuid.UUID) -> User:
    return User(id=uid, phone=f"+8491{uid.int % 10_000_000:07d}")


def _shop(sid: uuid.UUID, uid: uuid.UUID) -> Shop:
    return Shop(id=sid, user_id=uid, shop_name="Outcome Shop")


def _creator(cid: uuid.UUID, sid: uuid.UUID) -> Creator:
    return Creator(
        id=cid,
        shop_id=sid,
        tiktok_creator_id=f"tt_{cid.hex[:8]}",
        name="Creator Outcome",
    )


def test_ac3_calibration_weight_reflects_gmv_delta():
    """AC3: weight caps at 1 when realized meets or exceeds predicted."""
    assert compute_calibration_weight(
        predicted_gmv=Decimal("1000000"),
        realized_gmv=Decimal("2000000"),
    ) == Decimal("1")
    assert compute_calibration_weight(
        predicted_gmv=Decimal("1000000"),
        realized_gmv=Decimal("500000"),
    ) == Decimal("0.5")


@pytest.mark.asyncio
async def test_ac2_duplicate_idempotency_key_skips_edge_rewrite(
    session: AsyncSession, user_id: uuid.UUID
):
    """AC2: duplicate ingest with same idempotency key does not add edges."""
    shop_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    product_id = uuid.uuid4()
    session.add_all([_user(user_id), _shop(shop_id, user_id), _creator(creator_id, shop_id)])
    await session.flush()

    key = "campaign-outcome-94"
    first = await ingest_campaign_outcome(
        session,
        shop_id,
        idempotency_key=key,
        creator_id=creator_id,
        product_ids=[product_id],
        predicted_gmv=Decimal("10000000"),
        realized_gmv=Decimal("12000000"),
    )
    second = await ingest_campaign_outcome(
        session,
        shop_id,
        idempotency_key=key,
        creator_id=creator_id,
        product_ids=[product_id],
        predicted_gmv=Decimal("10000000"),
        realized_gmv=Decimal("99999999"),
    )

    assert first.is_duplicate is False
    assert first.edge_count == 1
    assert second.is_duplicate is True
    assert second.edge_count == 0
    assert second.campaign_id == first.campaign_id

    repo = GraphRepo(session)
    edges = await repo.list_edges(shop_id, edge_type="predicted_vs_actual")
    assert len(edges) == 1
    assert edges[0].weight == Decimal("1")
