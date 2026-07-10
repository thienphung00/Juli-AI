"""Campaign outcome ingest — P1-3 / Issue #94."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import GraphRepo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutcomeIngestResult:
    campaign_id: uuid.UUID
    idempotency_key: str
    is_duplicate: bool
    edge_count: int
    calibration_weight: Decimal | None


def compute_calibration_weight(
    *,
    predicted_gmv: Decimal | None,
    realized_gmv: Decimal,
) -> Decimal:
    """Map realized vs predicted GMV to a graph edge weight in [0, 1]."""
    if predicted_gmv is None or predicted_gmv <= 0:
        return Decimal("0.5")
    ratio = realized_gmv / predicted_gmv
    capped = min(max(ratio, Decimal("0")), Decimal("1"))
    return capped.quantize(Decimal("0.000001"))


async def ingest_campaign_outcome(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    idempotency_key: str,
    creator_id: uuid.UUID,
    product_ids: list[uuid.UUID],
    realized_gmv: Decimal,
    realized_conversion: Decimal | None = None,
    predicted_gmv: Decimal | None = None,
    predicted_conversion: Decimal | None = None,
    campaign_id: uuid.UUID | None = None,
) -> OutcomeIngestResult:
    """Persist campaign realized outcomes and predicted_vs_actual edges (idempotent)."""
    repo = GraphRepo(session)
    existing = await repo.find_campaign_by_idempotency(shop_id, idempotency_key)
    if existing is not None:
        return OutcomeIngestResult(
            campaign_id=existing.id,
            idempotency_key=idempotency_key,
            is_duplicate=True,
            edge_count=0,
            calibration_weight=None,
        )

    if campaign_id is not None:
        campaign = await repo.get_campaign(shop_id, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found for shop")
        campaign.realized_gmv = realized_gmv
        campaign.realized_conversion = realized_conversion
        if predicted_gmv is not None:
            campaign.predicted_gmv = predicted_gmv
        if predicted_conversion is not None:
            campaign.predicted_conversion = predicted_conversion
        campaign.status = "completed"
        campaign.completed_at = datetime.now(UTC)
        campaign.idempotency_key = idempotency_key
        await session.flush()
    else:
        campaign = await repo.create_campaign(
            shop_id,
            creator_id=creator_id,
            product_ids=[str(pid) for pid in product_ids],
            status="completed",
            predicted_gmv=predicted_gmv,
            realized_gmv=realized_gmv,
            predicted_conversion=predicted_conversion,
            realized_conversion=realized_conversion,
            idempotency_key=idempotency_key,
        )
        campaign.completed_at = datetime.now(UTC)
        await session.flush()

    weight = compute_calibration_weight(
        predicted_gmv=campaign.predicted_gmv,
        realized_gmv=realized_gmv,
    )
    metadata = json.dumps(
        {
            "predicted_gmv": str(campaign.predicted_gmv) if campaign.predicted_gmv else None,
            "realized_gmv": str(realized_gmv),
            "predicted_conversion": (
                str(campaign.predicted_conversion) if campaign.predicted_conversion else None
            ),
            "realized_conversion": (
                str(realized_conversion) if realized_conversion is not None else None
            ),
        }
    )
    computed_at = datetime.now(UTC)
    edge_count = 0
    for product_id in product_ids:
        await repo.upsert_edge(
            shop_id,
            edge_type="predicted_vs_actual",
            source_node_type="creator",
            source_node_id=creator_id,
            target_node_type="product",
            target_node_id=product_id,
            weight=weight,
            metadata_json=metadata,
            computed_at=computed_at,
        )
        edge_count += 1

    logger.info(
        "outcome_ingested",
        extra={
            "shop_id": str(shop_id),
            "campaign_id": str(campaign.id),
            "edge_count": edge_count,
            "is_duplicate": False,
        },
    )
    return OutcomeIngestResult(
        campaign_id=campaign.id,
        idempotency_key=idempotency_key,
        is_duplicate=False,
        edge_count=edge_count,
        calibration_weight=weight,
    )
