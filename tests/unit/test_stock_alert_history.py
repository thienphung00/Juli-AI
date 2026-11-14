"""Part S: the stock history written on ``item_snapshot`` ingest (SQLite, the Connector body)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from juli_backend.models.stock_alert import ShopeeStockHistory
from juli_backend.services import ingest as svc
from tests.support.builders import make_tenant
from tests.support.consent import grant_service_consent

CONTRACT = Path(__file__).resolve().parents[2] / "apps/connector/test/fixtures/contract"
READ_AT = datetime(2026, 11, 3, 5, 0)


def _body() -> svc.IngestBody:
    raw = json.loads((CONTRACT / "item_snapshot.body.json").read_text("utf-8"))
    return svc.IngestBody.model_validate(raw)


async def _ingest(session, shop):
    return await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="item_snapshot",
        body=_body(),
        token_id=None,
        now=READ_AT,
    )


async def test_each_variation_read_is_stored_once(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    await _ingest(session, shop)
    rows = (
        (
            await session.execute(
                select(ShopeeStockHistory).where(ShopeeStockHistory.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    by_key = {(r.item_id, r.model_id): r for r in rows}
    assert set(by_key) == {
        ("1001", ""),
        ("1001", "5001"),
        ("1001", "5002"),
        ("1002", ""),
        ("1003", ""),
    }
    m = by_key[("1001", "5001")]
    assert (m.sellable, m.available, m.listing_status) == (8, 10, "active")
    assert by_key[("1002", "")].listing_status == "unlisted"
    assert m.read_at == datetime(2026, 11, 3, 3, 0)

    # the same read posted again adds nothing
    await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="item_snapshot",
        body=_body().model_copy(update={"source_version": "0.3.19"}),
        token_id=None,
        now=READ_AT,
    )
    again = (
        (
            await session.execute(
                select(ShopeeStockHistory).where(ShopeeStockHistory.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(again) == 5
