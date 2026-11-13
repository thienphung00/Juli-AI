"""P97 T1: the Connector's stop event, and the shop-totals post it sends (SQLite).

- ``POST /v1/ingest/connector-events``: a stop that halted every reader lands in the Ops audit log
  (``system_connector_stop``), metadata only, behind the ingest token and a small hourly cap
- the Connector 0.3.11 ``shop_overview`` post (placed + confirmed day rows) validates and feeds the
  shop totals Tổng quan reads, so a shop with only the Connector has no ``shop_totals_partial``

Synthetic values only.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog
from juli_backend.services import ingest as svc
from juli_backend.services.ingest import gateway
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.shopee_analytics.loaders import load_shop_totals
from juli_backend.services.shopee_analytics.windows import Window
from tests.support.api import client_for
from tests.unit.test_ingest_gateway import _paired_client, _shopee_tenant

NOW = datetime(2026, 11, 9, 3, 0)  # naive UTC = 10:00 GMT+7


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


EVENT = {
    "platform": "shopee",
    "reader": "orders",
    "page": "/portal/sale/order",
    "status": "rate_limit",
    "code": "http_429",
    "occurred_at": "2026-11-09T03:00:00Z",
    "source_version": "0.3.11",
}


async def _token_headers(ext, code):
    paired = await ext.post("/v1/ingest/pair", json={"code": code, "platform": "shopee"})
    assert paired.status_code == 200, paired.text
    return {"Authorization": f"Bearer {paired.json()['token']}"}


async def test_a_stop_is_recorded_in_the_ops_audit_log_as_metadata(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        assert (await ext.post("/v1/ingest/connector-events", json=EVENT)).status_code == 401
        auth = await _token_headers(ext, code)
        done = await ext.post("/v1/ingest/connector-events", json=EVENT, headers=auth)
    assert done.status_code == 202, done.text
    rows = (
        (
            await session.execute(
                select(OpsAuditLog).where(
                    OpsAuditLog.shop_id == shop.id, OpsAuditLog.action == "system_connector_stop"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].actor_email == "system"
    assert rows[0].after == {
        "platform": "shopee",
        "reader": "orders",
        "page": "/portal/sale/order",
        "status": "rate_limit",
        "code": "http_429",
        "occurred_at": "2026-11-09T03:00:00+00:00",
        "source_version": "0.3.11",
    }


async def test_an_event_is_validated_and_scoped_to_the_token(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)
        extra = await ext.post(
            "/v1/ingest/connector-events", json={**EVENT, "body": {"buyer": "x"}}, headers=auth
        )
        bad_status = await ext.post(
            "/v1/ingest/connector-events", json={**EVENT, "status": "fine"}, headers=auth
        )
        bad_reader = await ext.post(
            "/v1/ingest/connector-events", json={**EVENT, "reader": "Orders; DROP"}, headers=auth
        )
        other_platform = await ext.post(
            "/v1/ingest/connector-events", json={**EVENT, "platform": "tiktok"}, headers=auth
        )
    assert extra.status_code == 422
    assert bad_status.status_code == 422
    assert bad_reader.status_code == 422
    assert other_platform.status_code == 403


async def test_a_stuck_client_cannot_flood_the_audit_log(session):
    user, shop = await _shopee_tenant(session)
    app, code = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        auth = await _token_headers(ext, code)
        codes = [
            (await ext.post("/v1/ingest/connector-events", json=EVENT, headers=auth)).status_code
            for _ in range(12)
        ]
    assert codes[:10] == [202] * 10
    assert codes[10:] == [429, 429]


async def test_connector_shop_overview_fills_the_shop_totals(session):
    """The 0.3.11 post: day rows per order type; Tổng quan reads confirmed GMV and orders."""
    _, shop = await _shopee_tenant(session)
    days = [date(2026, 11, 6) + timedelta(days=i) for i in range(3)]

    def body(order_type: str, scale: int) -> svc.IngestBody:
        return svc.IngestBody.model_validate(
            {
                "source": "extension",
                "source_version": "0.3.11",
                "captured_at": datetime(2026, 11, 9, 3, 0, tzinfo=UTC).isoformat(),
                "period": {
                    "start": days[0].isoformat(),
                    "end": days[-1].isoformat(),
                    "granularity": "day",
                },
                "order_type": order_type,
                "rows": [
                    {
                        "date": day.isoformat(),
                        "sales": 1_000_000 * scale * (i + 1),
                        "orders": 4 * scale * (i + 1),
                        "sales_per_order": 250_000,
                        "sales_excl_shopee_subsidy": 990_000 * scale * (i + 1),
                        "product_clicks": 90,
                        "visitors": 120,
                        "extra": {"shop_pv": 300},
                        **(
                            {
                                "cancelled_orders": 1,
                                "cancelled_sales": 50_000,
                                "returned_orders": 0,
                                "returned_sales": 0,
                            }
                            if order_type == "confirmed"
                            else {}
                        ),
                    }
                    for i, day in enumerate(days)
                ],
            }
        )

    for order_type, scale in (("confirmed", 1), ("placed", 2)):
        result = await gateway.ingest(
            session,
            shop_id=shop.id,
            platform="shopee",
            dataset="shop_overview",
            body=body(order_type, scale),
            token_id=None,
            now=NOW,
        )
        assert result.rows == 3
    await session.commit()

    totals = await load_shop_totals(session, shop.id, Window(days[0], days[-1]))
    assert totals.basis == "daily"
    assert totals.complete
    # confirmed, not placed: 1+2+3 million, 4+8+12 orders
    assert str(totals.gmv).startswith("6000000")
    assert totals.orders == 24


async def test_connector_order_lines_and_income_rows_are_accepted(session):
    """Rows shaped like the 0.3.11 mappers' output (order_ref already hashed in the browser)."""
    _, shop = await _shopee_tenant(session)
    ref = "ab" * 16
    captured = datetime(2026, 11, 9, 3, 0, tzinfo=UTC).isoformat()
    lines = svc.IngestBody.model_validate(
        {
            "source": "extension",
            "source_version": "0.3.11",
            "captured_at": captured,
            "period": {"start": "2026-11-07", "end": "2026-11-08", "granularity": "period"},
            "rows": [
                {
                    "order_ref": ref,
                    "line_no": 0,
                    "ordered_at": "2026-11-07T10:00:00",
                    "status": "delivered",
                    "qty": 2,
                    "original_price": 150000,
                    "deal_price": 120000,
                    "seller_subsidy": 60000,
                    "sku": "SKU-A",
                    "variation_sku": "SKU-A-1",
                    "variation_name": "Hong",
                    "shop_voucher_share": 15000,
                    "buyer_shipping_fee": 12000,
                    "completed_at": "2026-11-08T10:00:00",
                    "paid_at": "2026-11-07T10:01:00",
                }
            ],
        }
    )
    income = svc.IngestBody.model_validate(
        {
            "source": "extension",
            "source_version": "0.3.11",
            "captured_at": captured,
            "period": {"start": "2026-11-09", "end": "2026-11-09", "granularity": "period"},
            "rows": [
                {
                    "order_ref": ref,
                    "product_price": 150000,
                    "fee_fixed": 9000,
                    "fee_service": 7500,
                    "fee_payment": 3000,
                    "fee_piship": 1000,
                    "seller_voucher_borne": 2000,
                    "payout": 118500,
                }
            ],
        }
    )
    for dataset, body in (("order_lines", lines), ("order_income", income)):
        result = await gateway.ingest(
            session,
            shop_id=shop.id,
            platform="shopee",
            dataset=dataset,
            body=body,
            token_id=None,
            now=NOW,
        )
        assert result.rows == 1, dataset
