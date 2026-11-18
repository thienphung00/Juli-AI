"""F2 on real Postgres: ``funnel.load_rows`` fills ``FunnelRows.unavailable`` from
``stock_history`` as the runtime role, under the shop's scope (the other shop's reads stay
out), using the GMT+7 day and the window bounds.

Synthetic tenants only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_analytics.windows import Window
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

WINDOW = Window(date(2026, 11, 14), date(2026, 11, 16))


def _read(conn, shop_id, item, model, at, sellable, status="active", available=None) -> None:
    conn.execute(
        text(
            "INSERT INTO public.stock_history (id, shop_id, item_id, variation_id, read_at, "
            "sellable, available, listing_status) "
            "VALUES (:id, :shop, :item, :model, :at, :sellable, :available, :status)"
        ),
        {
            "id": uuid.uuid4(),
            "shop": shop_id,
            "item": item,
            "model": model,
            "at": at,
            "sellable": sellable,
            "available": available,
            "status": status,
        },
    )


async def test_load_rows_reads_the_unavailable_days_of_the_shop_only(owner_engine, shopee_tenants):
    a, b = shopee_tenants
    with owner_engine.begin() as conn:
        # 20:00 UTC on 11-14 is 03:00 GMT+7 on 11-15: both variations at 0 -> out of stock then
        _read(conn, a.shop_id, "1001", "m1", datetime(2026, 11, 14, 20), 0)
        _read(conn, a.shop_id, "1001", "m2", datetime(2026, 11, 14, 20), 0)
        # unlisted on 11-16 (GMT+7)
        _read(conn, a.shop_id, "1002", "", datetime(2026, 11, 16, 2), 7, "unlisted")
        # in stock, and a read outside the window: neither is unavailable
        _read(conn, a.shop_id, "1003", "", datetime(2026, 11, 15, 2), 3)
        _read(conn, a.shop_id, "1004", "", datetime(2026, 10, 1, 2), 0)
        # prepared stock 0 but Kho hàng 9 (the client-shop pattern): in stock, not out of stock
        _read(conn, a.shop_id, "1005", "", datetime(2026, 11, 15, 2), 0, available=9)
        # the other shop's out-of-stock read must not leak
        _read(conn, b.shop_id, "2001", "", datetime(2026, 11, 15, 2), 0)
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            rows = await funnel.load_rows(session, a.shop_id, WINDOW)
    assert dict(rows.unavailable) == {
        "1001": frozenset({date(2026, 11, 15)}),
        "1002": frozenset({date(2026, 11, 16)}),
    }
