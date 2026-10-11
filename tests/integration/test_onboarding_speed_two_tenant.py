"""Two-tenant proof for the P17 quick scan and onboarding state as `juli_app` (AC-17.7).

- migration 084's columns exist and its check constraint refuses an unknown
  quick-scan status;
- the quick scan for shop A, run as the runtime role, writes A's placeholder
  product, quick cards and quick-scan state under A's scope and nothing for B;
- `GET /v1/shops/me/onboarding`'s read (`onboarding_status`) under B's scope
  never sees A's state.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.onboarding import onboarding_status
from juli_backend.services.onboarding import quick_scan as qs
from tests.integration.test_shop_ingestion_two_tenant import committing_juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

NOW = datetime(2026, 10, 7, 7, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def tenants(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    with owner_engine.begin() as conn:
        for tenant, label in ((tenant_a, "a"), (tenant_b, "b")):
            conn.execute(
                text(
                    "UPDATE public.tiktok_credentials "
                    "SET capability = 'seller_connect', merchant_authorization_id = :merchant, "
                    "    shop_cipher = :cipher "
                    "WHERE id = :id"
                ),
                {
                    "merchant": f"merchant-p17-{label}-{tenant.shop_id.hex[:6]}",
                    "cipher": f"cipher-{label}",
                    "id": str(tenant.fresh_credential_id),
                },
            )
    return tenant_a, tenant_b


def _count(owner_engine, sql: str, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), {"shop": str(shop_id)}).scalar_one()


def _row(pid: str, impressions: int, clicks: int, orders: int) -> dict:
    return {
        "id": pid,
        "total_performance": {
            "gmv": {"amount": str(orders * 200_000)},
            "sku_orders": orders,
            "items_sold": orders,
            "product_impressions": impressions,
            "product_clicks": clicks,
        },
    }


class _Resources:
    def __init__(self) -> None:
        rows = [_row(f"p17-ok{i}", 30_000, 1500, 75) for i in range(5)]
        rows.append(_row("p17-weak", 30_000, 600, 30))

        class Analytics:
            def list_product_performance(self, **_kwargs):
                return {"products": rows, "next_page_token": ""}

        class Products:
            def get_diagnoses(self, ids):
                return {
                    "products": [
                        {
                            "id": "p17-weak",
                            "diagnoses": [
                                {
                                    "field": "MAIN_IMAGE",
                                    "diagnosis_results": [
                                        {"code": "MAIN_IMG_NUMBER_LESS_THAN_FIVE"}
                                    ],
                                }
                            ],
                        }
                    ]
                }

            def get_details(self, pid):
                return {"id": pid, "title": "Áo thun p17", "status": "ACTIVATE"}

        self.analytics = Analytics()
        self.products = Products()


def test_migration_084_columns_and_check_constraint(owner_engine, tenants):
    tenant_a, _ = tenants
    with owner_engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'shop_ingestion_state'"
                )
            )
        }
    assert {
        "quick_scan_status",
        "quick_scan_started_at",
        "quick_scan_done_at",
        "quick_scan_cards",
        "history_extended_on",
    } <= columns
    with pytest.raises(Exception, match="ck_shop_ingestion_state_quick_scan_status"):
        with owner_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO public.shop_ingestion_state (shop_id, status, quick_scan_status) "
                    "VALUES (:shop, 'not_started', 'bogus') "
                    "ON CONFLICT (shop_id) DO UPDATE SET quick_scan_status = 'bogus'"
                ),
                {"shop": str(tenant_a.shop_id)},
            )


@pytest.mark.asyncio
async def test_the_quick_scan_as_juli_app_writes_only_its_shop(owner_engine, tenants, monkeypatch):
    tenant_a, tenant_b = tenants
    monkeypatch.setenv(qs.TOP_PRODUCTS_ENV, "10")

    result = await qs.run_quick_scan(
        session_factory=committing_juli_app_session,
        shop_id=tenant_a.shop_id,
        app_key="app",
        app_secret="secret",
        create_resources=lambda _cfg: _Resources(),
        now=NOW,
    )
    assert result.status == "done" and result.cards == 1 and result.surfaced == 1

    products = (
        "SELECT COUNT(*) FROM public.products "
        "WHERE shop_id = :shop AND tiktok_product_id = 'p17-weak'"
    )
    assert _count(owner_engine, products, tenant_a.shop_id) == 1
    assert _count(owner_engine, products, tenant_b.shop_id) == 0
    cards = (
        "SELECT COUNT(*) FROM public.action_cards WHERE shop_id = :shop "
        "AND workflow_key = 'optimize_product_2' AND surfaced_at IS NOT NULL"
    )
    assert _count(owner_engine, cards, tenant_a.shop_id) == 1
    assert _count(owner_engine, cards, tenant_b.shop_id) == 0
    state = (
        "SELECT COUNT(*) FROM public.shop_ingestion_state WHERE shop_id = :shop "
        "AND quick_scan_status = 'done' AND quick_scan_cards = 1"
    )
    assert _count(owner_engine, state, tenant_a.shop_id) == 1
    assert _count(owner_engine, state, tenant_b.shop_id) == 0
    with owner_engine.connect() as conn:
        payload = conn.execute(
            text(
                "SELECT recommendation_payload FROM public.action_cards "
                "WHERE shop_id = :shop AND workflow_key = 'optimize_product_2'"
            ),
            {"shop": str(tenant_a.shop_id)},
        ).scalar_one()
    assert json.loads(payload)["diagnosis"]["quick_scan"]["confidence"] == "Tham khảo"


@pytest.mark.asyncio
async def test_onboarding_status_never_reads_another_shops_state(tenants):
    tenant_a, tenant_b = tenants
    async with committing_juli_app_session() as session:
        async with with_shop_scope(session, tenant_b.shop_id):
            body = await onboarding_status(session, tenant_b.shop_id)
            leaked = await onboarding_status(session, tenant_a.shop_id)
    assert body["steps"][0]["status"] == "pending"
    # Under B's scope, A's state row is invisible: A reads as "nothing started".
    assert leaked["steps"][0]["status"] == "pending"
    async with committing_juli_app_session() as session:
        async with with_shop_scope(session, tenant_a.shop_id):
            own = await onboarding_status(session, tenant_a.shop_id)
    assert own["steps"][0]["status"] == "done"
