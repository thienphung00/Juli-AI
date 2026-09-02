"""Shop-scoped commerce graph: Campaign nodes and typed relationship edges."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, or_, select

from juli_backend.models.models import Campaign, GraphEdge
from juli_backend.repositories._base import SessionRepo


class GraphRepo(SessionRepo):
    async def upsert_edge(
        self,
        shop_id: uuid.UUID,
        *,
        edge_type: str,
        source_node_type: str,
        source_node_id: uuid.UUID,
        target_node_type: str,
        target_node_id: uuid.UUID,
        weight: Decimal | None = None,
        metadata_json: str | None = None,
        computed_at: datetime | None = None,
    ) -> GraphEdge:
        """Create the edge or refresh its measurements.

        On an existing edge only the values actually supplied are overwritten,
        so a caller recomputing ``weight`` does not wipe ``metadata_json``.
        """
        stmt = select(GraphEdge).where(
            GraphEdge.shop_id == shop_id,
            GraphEdge.edge_type == edge_type,
            GraphEdge.source_node_type == source_node_type,
            GraphEdge.source_node_id == source_node_id,
            GraphEdge.target_node_type == target_node_type,
            GraphEdge.target_node_id == target_node_id,
        )
        existing = await self._one_or_none(stmt)
        if existing is not None:
            if weight is not None:
                existing.weight = weight
            if metadata_json is not None:
                existing.metadata_json = metadata_json
            if computed_at is not None:
                existing.computed_at = computed_at
            await self._session.flush()
            return existing

        return await self._add(
            GraphEdge(
                id=uuid.uuid4(),
                shop_id=shop_id,
                edge_type=edge_type,
                source_node_type=source_node_type,
                source_node_id=source_node_id,
                target_node_type=target_node_type,
                target_node_id=target_node_id,
                weight=weight,
                metadata_json=metadata_json,
                computed_at=computed_at,
            )
        )

    async def list_edges(
        self,
        shop_id: uuid.UUID,
        *,
        edge_type: str | None = None,
        node_type: str | None = None,
        node_id: uuid.UUID | None = None,
    ) -> list[GraphEdge]:
        """Edges for a shop, newest first; ``node_type``+``node_id`` match either end."""
        stmt = select(GraphEdge).where(GraphEdge.shop_id == shop_id)
        if edge_type is not None:
            stmt = stmt.where(GraphEdge.edge_type == edge_type)
        if node_type is not None and node_id is not None:
            stmt = stmt.where(
                or_(
                    and_(
                        GraphEdge.source_node_type == node_type,
                        GraphEdge.source_node_id == node_id,
                    ),
                    and_(
                        GraphEdge.target_node_type == node_type,
                        GraphEdge.target_node_id == node_id,
                    ),
                )
            )
        return await self._all(stmt.order_by(GraphEdge.created_at.desc()))

    async def find_campaign_by_idempotency(
        self, shop_id: uuid.UUID, idempotency_key: str
    ) -> Campaign | None:
        return await self._one_or_none(
            select(Campaign).where(
                Campaign.shop_id == shop_id, Campaign.idempotency_key == idempotency_key
            )
        )

    async def get_campaign(self, shop_id: uuid.UUID, campaign_id: uuid.UUID) -> Campaign | None:
        return await self._one_or_none(
            select(Campaign).where(Campaign.shop_id == shop_id, Campaign.id == campaign_id)
        )

    async def create_campaign(
        self,
        shop_id: uuid.UUID,
        *,
        creator_id: uuid.UUID,
        product_ids: list[str],
        status: str = "draft",
        predicted_gmv: Decimal | None = None,
        realized_gmv: Decimal | None = None,
        predicted_conversion: Decimal | None = None,
        realized_conversion: Decimal | None = None,
        idempotency_key: str | None = None,
    ) -> Campaign:
        return await self._add(
            Campaign(
                id=uuid.uuid4(),
                shop_id=shop_id,
                creator_id=creator_id,
                status=status,
                product_ids_json=json.dumps(product_ids),
                predicted_gmv=predicted_gmv,
                realized_gmv=realized_gmv,
                predicted_conversion=predicted_conversion,
                realized_conversion=realized_conversion,
                idempotency_key=idempotency_key,
            )
        )


__all__ = ["GraphRepo"]
