"""Orders-derived KPIs for the sandbox shop's ADR-108 report (fast track P64, D73.3).

A shop read through its own ``sandbox_write`` credential whose A-34 product-days
are all zero gets GMV / SKU orders / AOV and the hero ranking from its real paid
synced orders, marked ``metrics_source = "orders"``; funnel traffic stays empty.
A real shop is built from A-34 exactly as before (no ``metrics_source`` key).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import Order, OrderItem, Product, Shop, User
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport
from juli_backend.repositories import ShopDiagnosisReportsRepo, TikTokCredentialRepo
from juli_backend.services.shop_diagnosis_daily import build_and_store_shop_diagnosis
from juli_backend.services.shop_diagnosis_daily.orders_source import (
    OrderLine,
    analytics_all_zero,
    daily_rows_from_orders,
)
from tests.support.shop_diagnosis import END, FakeTikTokReadResources

#: 2026-10-07 10:00 UTC is 17:00 in UTC+7, so "yesterday" there is END (10-06).
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_lazy_refresh(monkeypatch):
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


class _ZeroAnalytics:
    """A-34 the way TikTok answers for a sandbox shop: every product-day at zero."""

    def __init__(self, inner, calls: list) -> None:
        self._inner = inner
        self._calls = calls

    def list_product_performance_all(self, *, start_date_ge: str, end_date_lt: str):
        self._calls.append(("a34", start_date_ge))
        return [{"id": "p-listed", "total_performance": {"gmv": {"amount": "0"}, "sku_orders": 0}}]

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _sandbox_resources() -> FakeTikTokReadResources:
    resources = FakeTikTokReadResources()
    resources.analytics = _ZeroAnalytics(resources.analytics, resources.calls)
    return resources


async def _shop(session, *, label: str, capability: TikTokCapability) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8492{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name=f"{label} shop",
        tiktok_shop_id=f"tt-{label}-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    session.add_all([user, shop])
    await session.flush()
    await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token=f"access-{label}",
        refresh_token=f"refresh-{label}",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        merchant_authorization_id=f"merchant-{label}",
        capability=capability.value,
        shop_cipher=f"cipher-{label}",
    )
    await session.commit()
    return shop


def _at(day: date, hour: int = 12) -> datetime:
    """Naive UTC for ``hour`` o'clock local (UTC+7) on ``day``."""
    return datetime(day.year, day.month, day.day, hour) - timedelta(hours=7)


async def _order(session, shop: Shop, order_id: str, day: date, status: str, lines) -> None:
    created = _at(day)
    order = Order(
        shop_id=shop.id,
        tiktok_order_id=order_id,
        status=status,
        total_amount=Decimal(sum(q * p for _, q, p in lines)),
        currency="VND",
        tiktok_created_at=created,
        update_time=created,
    )
    session.add(order)
    await session.flush()
    for n, (product_id, quantity, price) in enumerate(lines):
        session.add(
            OrderItem(
                shop_id=shop.id,
                order_id=order.id,
                tiktok_order_id=order_id,
                tiktok_product_id=product_id,
                tiktok_sku_id=f"{product_id}-sku{n}",
                quantity=quantity,
                unit_price=Decimal(price),
                line_total=Decimal(quantity * price),
                update_time=created,
            )
        )
    await session.commit()


async def _seed_orders(session, shop: Shop) -> None:
    session.add(
        Product(
            shop_id=shop.id,
            tiktok_product_id="p-sbx-1",
            title="Áo thun cotton sandbox",
            name="Áo thun cotton sandbox",
            status="ACTIVATE",
            update_time=_at(END),
        )
    )
    await session.commit()
    last = END - timedelta(days=3)
    prior = END - timedelta(days=40)
    # Paid: 2 orders in the last 30 days, 1 in the prior 30.
    await _order(session, shop, "o-1", last, "confirmed", [("p-sbx-1", 2, 100_000)])
    await _order(session, shop, "o-2", last, "DELIVERED", [("p-sbx-1", 1, 100_000)])
    await _order(session, shop, "o-3", prior, "completed", [("p-sbx-1", 1, 100_000)])
    # Never counted: unpaid, cancelled, returned, outside the 60 days.
    await _order(session, shop, "o-4", last, "pending", [("p-sbx-1", 9, 100_000)])
    await _order(session, shop, "o-5", last, "cancelled", [("p-sbx-1", 9, 100_000)])
    await _order(session, shop, "o-6", last, "returned", [("p-sbx-1", 9, 100_000)])
    await _order(session, shop, "o-7", END - timedelta(days=70), "delivered", [("p-sbx-1", 9, 1)])


async def _build(factory, shop_id, resources, tmp_path: Path, **kwargs):
    return await build_and_store_shop_diagnosis(
        session_factory=factory,
        shop_id=shop_id,
        app_key="app-key",
        app_secret="app-secret",
        create_resources=lambda _config: resources,
        now=NOW,
        tmp_root=tmp_path,
        sleep_s=0,
        backoff_sleep=lambda _s: None,
        **kwargs,
    )


async def _report(session, shop_id) -> dict:
    row = await ShopDiagnosisReportsRepo(session).latest(shop_id, "60d")
    assert row is not None
    return row.report


@pytest.mark.asyncio
async def test_a_zero_analytics_sandbox_report_is_built_from_its_paid_orders(
    session, factory, tmp_path
):
    shop = await _shop(session, label="sbx", capability=TikTokCapability.SANDBOX_WRITE)
    await _seed_orders(session, shop)
    # The sandbox's analytics day lags; the report still ends yesterday (UTC+7).
    session.add(ShopIngestionState(shop_id=shop.id, analytics_through_date=END - timedelta(days=9)))
    await session.commit()

    result = await _build(factory, shop.id, _sandbox_resources(), tmp_path)

    assert result.built and result.end_date == END
    report = await _report(session, shop.id)
    assert report["metrics_source"] == "orders"
    total = report["total"]
    # Daily averages over each 30-day window: 300k ₫ / 2 orders last, 100k ₫ / 1 prior.
    assert total["last"]["gmv"] * 30 == pytest.approx(300_000)
    assert total["prior"]["gmv"] * 30 == pytest.approx(100_000)
    assert total["orders_last"] == 2 and total["orders_prior"] == 1
    # The funnel is never derived: no traffic, so no CTR / CTOR.
    assert total["last"]["impressions"] == 0 and total["last"]["clicks"] == 0
    for row in report["channels"]:
        assert row["comparison"]["last"]["gmv"] == 0
    assert report["selection"]["heroes"] == ["p-sbx-1"]
    assert report["titles"]["p-sbx-1"] == "Áo thun cotton sandbox"


@pytest.mark.asyncio
async def test_a_real_shop_is_built_from_analytics_unchanged(session, factory, tmp_path):
    shop = await _shop(session, label="real", capability=TikTokCapability.SELLER_CONNECT)
    await _seed_orders(session, shop)

    result = await _build(factory, shop.id, FakeTikTokReadResources(), tmp_path)

    assert result.built
    report = await _report(session, shop.id)
    assert "metrics_source" not in report
    # The synthetic A-34 GMV, nowhere near the 300k ₫ of synced orders.
    assert report["total"]["last"]["gmv"] * 30 > 1_000_000
    assert report["total"]["last"]["impressions"] > 0


@pytest.mark.asyncio
async def test_a_sandbox_without_paid_orders_keeps_the_analytics_report(session, factory, tmp_path):
    shop = await _shop(session, label="sbx-empty", capability=TikTokCapability.SANDBOX_WRITE)

    await _build(factory, shop.id, _sandbox_resources(), tmp_path)

    report = await _report(session, shop.id)
    assert report["metrics_source"] == "analytics"
    assert report["total"]["last"]["gmv"] == 0


@pytest.mark.asyncio
async def test_a_sandbox_report_from_before_the_source_flag_is_rebuilt_once(
    session, factory, tmp_path
):
    shop = await _shop(session, label="sbx-old", capability=TikTokCapability.SANDBOX_WRITE)
    await _seed_orders(session, shop)
    async with factory() as other:
        await ShopDiagnosisReportsRepo(other).save(
            shop.id, end_date=END, ranking="60d", report={"total": {}}, built_at=_at(END)
        )
        await other.commit()

    first = await _build(factory, shop.id, _sandbox_resources(), tmp_path)
    second = await _build(factory, shop.id, _sandbox_resources(), tmp_path)

    assert first.built, "the zero-only report stored before the flag is not already_built"
    assert not second.built and second.skipped_reason == "already_built"
    rows = (
        (
            await session.execute(
                select(ShopDiagnosisReport).where(ShopDiagnosisReport.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    assert {r.report.get("metrics_source") for r in rows} == {"orders"}


def test_analytics_all_zero_reads_every_traffic_and_sales_count():
    zero = {"id": "p", "total_performance": {"gmv": {"amount": "0"}, "sku_orders": 0}}
    clicked = {"id": "p", "total_performance": {"product_clicks": 3}}
    assert analytics_all_zero({END: [zero], END - timedelta(days=1): []})
    assert not analytics_all_zero({END: [zero, clicked]})


def test_daily_rows_count_an_order_once_per_product_and_sum_its_lines():
    lines = [
        OrderLine(END, "o-1", "p-a", 2, 200_000.0),
        OrderLine(END, "o-1", "p-a", 1, 50_000.0),
        OrderLine(END, "o-2", "p-a", 1, 100_000.0),
        OrderLine(END, "o-2", "p-b", 3, 30_000.0),
    ]
    rows = {r["id"]: r["total_performance"] for r in daily_rows_from_orders(lines)[END]}
    assert rows["p-a"] == {
        "gmv": {"amount": "350000.00"},
        "sku_orders": 2,
        "orders": 2,
        "items_sold": 4,
    }
    assert rows["p-b"]["sku_orders"] == 1 and rows["p-b"]["items_sold"] == 3
    assert "product_impressions" not in rows["p-a"]
