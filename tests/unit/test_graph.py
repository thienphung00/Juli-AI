"""Commerce graph layer — Issue #92 (P1-1).

AC1 → test_ac1_migration_tables_registered
AC2 → test_ac2_upsert_edge_is_idempotent
AC3 → test_ac3_list_edges_scoped_by_shop
AC4 → test_ac4_create_campaign_persists_node
AC5 → test_ac5_shop_a_cannot_read_shop_b_edges
"""

import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Campaign, Creator, GraphEdge, Shop, User
from backend.database.repos import GraphRepo


def _user(uid: uuid.UUID) -> User:
    return User(id=uid, phone=f"+8490{uid.int % 10_000_000:07d}")


def _shop(sid: uuid.UUID, uid: uuid.UUID, name: str) -> Shop:
    return Shop(id=sid, user_id=uid, shop_name=name)


def _creator(cid: uuid.UUID, sid: uuid.UUID) -> Creator:
    return Creator(
        id=cid,
        shop_id=sid,
        tiktok_creator_id=f"tt_{cid.hex[:8]}",
        name="Creator A",
    )


def test_ac1_migration_tables_registered():
    """AC1: campaigns and graph_edges tables exist on Base metadata."""
    table_names = {Campaign.__table__.name, GraphEdge.__table__.name}
    assert table_names.issubset(set(Campaign.metadata.tables.keys()))


@pytest.mark.asyncio
async def test_ac2_upsert_edge_is_idempotent(session: AsyncSession, user_id: uuid.UUID):
    """AC2: upsert_edge is idempotent on natural key."""
    shop_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    product_id = uuid.uuid4()
    session.add_all([_user(user_id), _shop(shop_id, user_id, "Graph Shop")])
    await session.flush()

    repo = GraphRepo(session)
    first = await repo.upsert_edge(
        shop_id,
        edge_type="potential_match",
        source_node_type="creator",
        source_node_id=creator_id,
        target_node_type="product",
        target_node_id=product_id,
        weight=Decimal("0.75"),
    )
    second = await repo.upsert_edge(
        shop_id,
        edge_type="potential_match",
        source_node_type="creator",
        source_node_id=creator_id,
        target_node_type="product",
        target_node_id=product_id,
        weight=Decimal("0.90"),
    )

    assert first.id == second.id
    assert second.weight == Decimal("0.90")
    edges = await repo.list_edges(shop_id)
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_ac3_list_edges_scoped_by_shop(
    session: AsyncSession, user_id: uuid.UUID, other_user_id: uuid.UUID
):
    """AC3: list_edges returns only edges for the given shop."""
    shop_a = uuid.uuid4()
    shop_b = uuid.uuid4()
    session.add_all(
        [
            _user(user_id),
            _user(other_user_id),
            _shop(shop_a, user_id, "Shop A"),
            _shop(shop_b, other_user_id, "Shop B"),
        ]
    )
    await session.flush()

    repo = GraphRepo(session)
    await repo.upsert_edge(
        shop_a,
        edge_type="has_sold",
        source_node_type="creator",
        source_node_id=uuid.uuid4(),
        target_node_type="product",
        target_node_id=uuid.uuid4(),
        weight=Decimal("1.0"),
    )
    await repo.upsert_edge(
        shop_b,
        edge_type="has_sold",
        source_node_type="creator",
        source_node_id=uuid.uuid4(),
        target_node_type="product",
        target_node_id=uuid.uuid4(),
        weight=Decimal("0.5"),
    )

    edges_a = await repo.list_edges(shop_a, edge_type="has_sold")
    assert len(edges_a) == 1
    assert edges_a[0].shop_id == shop_a


@pytest.mark.asyncio
async def test_ac4_create_campaign_persists_node(session: AsyncSession, user_id: uuid.UUID):
    """AC4: create_campaign persists Campaign node with creator_id + shop_id."""
    shop_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    product_id = uuid.uuid4()
    session.add_all(
        [_user(user_id), _shop(shop_id, user_id, "Campaign Shop"), _creator(creator_id, shop_id)]
    )
    await session.flush()

    repo = GraphRepo(session)
    campaign = await repo.create_campaign(
        shop_id,
        creator_id=creator_id,
        product_ids=[str(product_id)],
        status="active",
        predicted_gmv=Decimal("50000000"),
    )

    assert campaign.shop_id == shop_id
    assert campaign.creator_id == creator_id
    assert json.loads(campaign.product_ids_json) == [str(product_id)]
    assert campaign.predicted_gmv == Decimal("50000000")


@pytest.mark.asyncio
async def test_ac5_shop_a_cannot_read_shop_b_edges(
    session: AsyncSession, user_id: uuid.UUID, other_user_id: uuid.UUID
):
    """AC5: shop A cannot read shop B graph edges."""
    shop_a = uuid.uuid4()
    shop_b = uuid.uuid4()
    session.add_all(
        [
            _user(user_id),
            _user(other_user_id),
            _shop(shop_a, user_id, "Shop A"),
            _shop(shop_b, other_user_id, "Shop B"),
        ]
    )
    await session.flush()

    repo = GraphRepo(session)
    secret_edge = await repo.upsert_edge(
        shop_b,
        edge_type="trust_score",
        source_node_type="creator",
        source_node_id=uuid.uuid4(),
        target_node_type="shop",
        target_node_id=shop_b,
        weight=Decimal("0.99"),
    )

    edges_for_a = await repo.list_edges(shop_a)
    assert edges_for_a == []

    edges_for_b = await repo.list_edges(shop_b)
    assert len(edges_for_b) == 1
    assert edges_for_b[0].id == secret_edge.id
