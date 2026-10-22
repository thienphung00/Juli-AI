"""P64 (D73.3) on real Postgres under RLS, as ``juli_app``: the sandbox's orders-derived KPIs.

The unit twins are ``tests/unit/test_shop_diagnosis_orders_source.py`` and
``tests/unit/test_quick_scan_orders.py`` (SQLite, no RLS). Here:

1. ``load_paid_order_lines`` reads ``silver.orders`` joined to ``order_items`` under the
   shop's scope: paid lines only, another shop's orders invisible;
2. the daily diagnosis build stores ``metrics_source = "orders"`` with the paid GMV;
3. the quick scan writes the orders-based title card with its stored proposal.

Every test asserts it really runs on Postgres as ``juli_app``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.services.onboarding import quick_scan as qs
from juli_backend.services.shop_diagnosis_daily import build_and_store_shop_diagnosis
from juli_backend.services.shop_diagnosis_daily.orders_source import (
    load_paid_order_lines,
    product_titles,
)
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

#: 2026-10-07 10:00 UTC = 17:00 UTC+7: yesterday there is 10-06.
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
END = date(2026, 10, 6)
CREATED = datetime(2026, 10, 3, 5, 0)  # 12:00 UTC+7 on 10-03


def _seed_shop(engine, *, capability: TikTokCapability) -> uuid.UUID:
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO public.users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1556{user_id.hex[:7]}"},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id) "
                "VALUES (:id, :u, 'Orders shop', :t)"
            ),
            {"id": shop_id, "u": user_id, "t": f"77{shop_id.int % 10**17:017d}"},
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials "
                "(id, shop_id, merchant_authorization_id, capability, shop_cipher, access_token, "
                " refresh_token, token_expires_at, scopes, status, refresh_count) "
                "VALUES (:id, :s, :m, :c, :m, 'access', 'r', :exp, "
                " 'seller.order.info', 'active', 0)"
            ),
            {
                "id": uuid.uuid4(),
                "s": shop_id,
                "m": f"m-{shop_id.hex[:8]}",
                "c": capability.value,
                "exp": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, title, "
                "status, update_time) VALUES (:id, :s, 'p-best', 'Áo thun nữ', 'Áo thun nữ', "
                "'ACTIVATE', now())"
            ),
            {"id": uuid.uuid4(), "s": shop_id},
        )
        for order_id, status, qty in (("o-1", "confirmed", 3), ("o-2", "cancelled", 40)):
            row_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO silver.orders (id, shop_id, tiktok_order_id, status, "
                    "total_amount, currency, tiktok_created_at, update_time) "
                    "VALUES (:id, :s, :o, :st, :amt, 'VND', :c, :c)"
                ),
                {
                    "id": row_id,
                    "s": shop_id,
                    "o": order_id,
                    "st": status,
                    "amt": Decimal(qty * 150_000),
                    "c": CREATED,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.order_items (id, shop_id, order_id, tiktok_order_id, "
                    "tiktok_product_id, tiktok_sku_id, quantity, unit_price, line_total, "
                    "update_time) VALUES (:id, :s, :oid, :o, 'p-best', 'sku-1', :q, 150000, "
                    ":lt, :c)"
                ),
                {
                    "id": uuid.uuid4(),
                    "s": shop_id,
                    "oid": row_id,
                    "o": order_id,
                    "q": qty,
                    "lt": Decimal(qty * 150_000),
                    "c": CREATED,
                },
            )
    return shop_id


@pytest.fixture
def shops():
    with owner_sync_engine() as engine:
        return {
            "sandbox": _seed_shop(engine, capability=TikTokCapability.SANDBOX_WRITE),
            "other": _seed_shop(engine, capability=TikTokCapability.SELLER_CONNECT),
        }


async def _as_juli_app(session) -> None:
    assert (await session.execute(text("SELECT current_user"))).scalar_one() == "juli_app"


async def test_1_paid_lines_only_and_only_the_scoped_shop(shops):
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        await _as_juli_app(session)
        async with with_shop_scope(session, shops["sandbox"]):
            lines = await load_paid_order_lines(
                session, shops["sandbox"], END - timedelta(days=59), END
            )
            titles = await product_titles(session, shops["sandbox"], ["p-best"])
    assert [(x.order_id, x.product_id, x.quantity, x.revenue, x.day) for x in lines] == [
        ("o-1", "p-best", 3, 450_000.0, date(2026, 10, 3))
    ]
    assert titles == {"p-best": "Áo thun nữ"}


async def test_2_the_diagnosis_build_stores_orders_metrics(shops, tmp_path):
    from tests.unit.test_shop_diagnosis_orders_source import _sandbox_resources

    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            await _as_juli_app(session)
        result = await build_and_store_shop_diagnosis(
            session_factory=factory,
            shop_id=shops["sandbox"],
            app_key="k",
            app_secret="s",
            create_resources=lambda _c: _sandbox_resources(),
            now=NOW,
            tmp_root=tmp_path,
            sleep_s=0,
            backoff_sleep=lambda _s: None,
        )
    assert result.built and result.end_date == END
    with owner_sync_engine() as engine, engine.begin() as conn:
        report = conn.execute(
            text(
                "SELECT report FROM public.shop_diagnosis_reports "
                "WHERE shop_id = :s AND ranking = '60d'"
            ),
            {"s": shops["sandbox"]},
        ).scalar_one()
    report = report if isinstance(report, dict) else json.loads(report)
    assert report["metrics_source"] == "orders"
    assert report["total"]["last"]["gmv"] * 30 == pytest.approx(450_000)
    assert report["total"]["orders_last"] == 1


async def test_3_the_quick_scan_writes_the_orders_title_card(shops, monkeypatch):
    from tests.unit.test_quick_scan_orders import FakeSandboxResources, _listing

    monkeypatch.delenv(qs.ENABLED_ENV, raising=False)
    resources = FakeSandboxResources({"p-best": _listing("p-best", "Áo thun nữ")})
    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            await _as_juli_app(session)
        result = await qs.run_quick_scan(
            session_factory=factory,
            shop_id=shops["sandbox"],
            app_key="k",
            app_secret="s",
            create_resources=lambda _c: resources,
            now=NOW,
        )
    assert result.cards == 1, result
    with owner_sync_engine() as engine, engine.begin() as conn:
        payload = conn.execute(
            text(
                "SELECT recommendation_payload FROM public.action_cards "
                "WHERE shop_id = :s AND workflow_key = 'optimize_product_2'"
            ),
            {"s": shops["sandbox"]},
        ).scalar_one()
    diagnosis = json.loads(payload)["diagnosis"]
    assert diagnosis["quick_scan"]["source"] == "orders"
    assert diagnosis["listing_proposal"]["after"] == "Áo thun nữ - JuliWear - Trắng, Đen"
