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


# -- the page readers (ADR-120 d.14) ----------------------------------------------------

READ_AT = datetime(2026, 11, 3, 5, 0)


@pytest.mark.parametrize(
    ("dataset", "name", "rows"),
    [
        ("item_catalog", "item_catalog.body.json", 5),
        ("ads_campaign_daily", "ads_campaign_daily.body.json", 3),
        ("voucher_settings", "voucher_settings.body.json", 2),
    ],
)
async def test_the_page_readers_posts_are_accepted(session, dataset, name, rows):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    result = await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset=dataset,
        body=_body(name),
        token_id=None,
        now=READ_AT,
    )
    assert result.rows == rows


async def test_the_ads_daily_post_lands_as_ads_overlay_rows(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="ads_campaign_daily",
        body=_body("ads_campaign_daily.body.json"),
        token_id=None,
        now=READ_AT,
    )
    stored = (
        (
            await session.execute(
                select(PlatformDailyMetric).where(PlatformDailyMetric.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    assert {m.stream for m in stored} == {"ads"}
    assert {m.order_type for m in stored} == {"placed"}
    main = next(m for m in stored if m.platform_source == "Chiến dịch mẫu 1")
    assert (main.impressions, main.clicks, main.orders, main.gmv) == (
        Decimal("1000"),
        Decimal("40"),
        Decimal("4"),
        Decimal("400000"),
    )
    assert main.extra["cost"] == 50000


@pytest.mark.parametrize(
    ("dataset", "name"),
    [
        ("item_snapshot", "item_snapshot.body.json"),
        ("shop_health_daily", "shop_health_daily.body.json"),
    ],
)
async def test_the_snapshot_and_health_readers_posts_are_accepted_by_the_gateway(
    session, dataset, name
):
    # Formerly "reserved, the gateway refuses" (migration 113 gave them tables).
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    result = await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset=dataset,
        body=_body(name),
        token_id=None,
        now=READ_AT,
    )
    assert result.rows > 0 and result.duplicate is False


async def test_item_traffic_sources_post_lands_on_streams_and_segments(session):
    """The pinned Connector body (one item, one day, confirmed) → stream / segment frame."""
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    body = _body("item_traffic_sources.body.json")
    result = await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="item_traffic_sources",
        body=body,
        token_id=None,
        now=datetime(2026, 11, 4, 3, 0),
    )
    assert result.rows == len(body.rows)
    stored = (
        (
            await session.execute(
                select(PlatformDailyMetric).where(PlatformDailyMetric.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == len(body.rows)
    segments = {m.segment for m in stored}
    assert segments <= {
        "all",
        "search",
        "recommend",
        "my_orders",
        "cart",
        "shop_page",
        "promo",
        "other",
    }
    assert {m.stream for m in stored} <= {
        "product_card",
        "seller_live",
        "seller_video",
        "affiliate",
    }
    assert all(m.order_type == "confirmed" and m.item_id == "1001" for m in stored)
    total = next(m for m in stored if m.stream == "product_card" and m.segment == "all")
    assert (total.gmv, total.orders, total.impressions, total.clicks) == (
        Decimal("1000000"),
        Decimal("20"),
        Decimal("1000"),
        Decimal("100"),
    )
    assert total.extra["unique_product_clicks"] == 90
