"""The Juli Connector's posts are accepted by the gateway (fast track P24, D31.3 / D31.4).

``apps/connector/test/contract.test.ts`` pins what the extension's mapper produces
for the recon-shaped Seller Centre fixtures in
``apps/connector/test/fixtures/contract/*.body.json``. This posts the SAME files
through the gateway, so a field the extension sends and the gateway refuses (or
a KPI it stops mapping) fails here rather than in a seller's browser.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.services import ingest as svc
from tests.support.builders import make_tenant
from tests.support.consent import grant_service_consent

CONTRACT = Path(__file__).resolve().parents[2] / "apps/connector/test/fixtures/contract"
NOW = datetime(2026, 10, 12, 3, 0)


def _body(name: str) -> svc.IngestBody:
    return svc.IngestBody.model_validate(json.loads((CONTRACT / name).read_text("utf-8")))


@pytest.mark.parametrize(
    ("dataset", "name", "rows"),
    [
        ("traffic_overview", "traffic_overview.body.json", 5),
        ("shop_traffic", "shop_traffic.body.json", 3),
    ],
)
async def test_the_extensions_posts_are_accepted_and_normalized(session, dataset, name, rows):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)  # ADR-116 §4: the gateway requires it
    result = await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset=dataset,
        body=_body(name),
        token_id=None,
        now=NOW,
    )
    assert result.rows == rows
    stored = (
        (
            await session.execute(
                select(PlatformDailyMetric).where(PlatformDailyMetric.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == rows
    assert all(m.source == "extension" and m.confidence == "high" for m in stored)


async def test_overview_lands_on_the_juli_streams_with_kpis(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)  # ADR-116 §4: the gateway requires it
    await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="traffic_overview",
        body=_body("traffic_overview.body.json"),
        token_id=None,
        now=NOW,
    )
    by_stream = {
        m.stream: m
        for m in (
            await session.execute(
                select(PlatformDailyMetric).where(PlatformDailyMetric.shop_id == shop.id)
            )
        ).scalars()
    }
    assert set(by_stream) == {"product_card", "seller_live", "seller_video", "affiliate", "ads"}
    card = by_stream["product_card"]
    assert (card.impressions, card.clicks, card.ctr, card.gmv) == (
        Decimal("3000"),
        Decimal("100"),
        Decimal("0.05"),
        Decimal("1000000"),
    )
    assert card.extra["sales_ratio"] == 0.2
    assert by_stream["ads"].extra["ads_expense"] == 50000
