"""batch-1124-b CONN (owner Q4): the combo discount the Connector posts (list price minus the line's
share of the combo price, per line) is checked against the shop's percent combo tiers and a
mismatch is only logged. Synthetic ids and amounts only."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.services.ingest.combo_discount_check import combo_discount_mismatches
from juli_backend.services.ingest.schemas import ShopeeOrderLineRow
from juli_backend.services.ingest.writers import write_order_lines
from tests.support.builders import make_tenant
from tests.unit.test_ingest_composed_precedence import T2, _payload

REF = "c" * 32
TIERS = {88: [(2, Decimal(5)), (3, Decimal(10))]}


def _line(line_no: int, list_price: int, deal: Decimal, qty: int = 1, **over: Any):
    discount = (Decimal(list_price) - deal) * qty
    return ShopeeOrderLineRow.model_validate(
        {
            "order_ref": REF,
            "line_no": line_no,
            "ordered_at": "2026-11-24T09:00:00",
            "status": "in_transit",
            "variation_sku": f"SKU-{line_no}",
            "qty": qty,
            "original_price": deal,
            "deal_price": deal,
            "bundle_discount": discount,
            "promo_kind": "bundle",
            "extra": {"bundle_deal_id": 88, "list_price": list_price},
            **over,
        }
    )


def test_a_discount_that_matches_the_reached_tier_is_not_a_mismatch():
    # list 100.000 x 2 at the 2-item tier (5 %): 10.000 = 5.000 + 5.000
    rows = [_line(0, 100_000, Decimal(95_000)), _line(1, 100_000, Decimal(95_000))]
    assert combo_discount_mismatches(rows, TIERS) == []


def test_a_discount_off_the_tier_beyond_rounding_is_a_mismatch():
    rows = [_line(0, 100_000, Decimal(90_000)), _line(1, 100_000, Decimal(95_000))]
    (miss,) = combo_discount_mismatches(rows, TIERS)
    assert (miss.combo_id, miss.expected, miss.posted) == (
        88,
        Decimal("10000.00"),
        Decimal("15000.00"),
    )


def test_the_tier_follows_the_combo_quantity_and_rounding_is_tolerated():
    # 3 items reach the 10 % tier: 30.000 expected, posted 30.001 (1 VND split rounding)
    rows = [
        _line(0, 100_000, Decimal(90_000)),
        _line(1, 100_000, Decimal("89999.50"), qty=2),
    ]
    assert combo_discount_mismatches(rows, TIERS) == []


def test_not_checked_without_percent_tiers_a_list_price_or_below_the_first_tier():
    two = [_line(0, 100_000, Decimal(50_000)), _line(1, 100_000, Decimal(50_000))]
    assert combo_discount_mismatches(two, {}) == []
    assert combo_discount_mismatches([_line(0, 100_000, Decimal(50_000))], TIERS) == []
    no_list = [_line(0, 100_000, Decimal(50_000), extra={"bundle_deal_id": 88})] * 2
    assert combo_discount_mismatches(no_list, TIERS) == []


async def test_the_writer_logs_a_mismatch_and_keeps_the_posted_lines(session, caplog):
    _, shop = await make_tenant(session)
    session.add(
        PlatformPromotion(
            id=uuid.uuid4(),
            shop_id=shop.id,
            platform="shopee",
            promo_type="bundle",
            program_name="Combo mẫu",
            starts_at=datetime(2026, 11, 1),
            period_start=date(2026, 11, 24),
            period_end=date(2026, 11, 24),
            order_type="none",
            extra={
                "combo_id": 88,
                "discount_type": "pct",
                "tiers": [{"qty": 2, "value": 5}, {"qty": 3, "value": 10}],
            },
            source="extension",
            source_rank=3,
            source_version="0.3.36",
            captured_at=datetime(2026, 11, 24),
            updated_at=datetime(2026, 11, 24),
        )
    )
    await session.flush()
    rows = [_line(0, 100_000, Decimal(90_000)), _line(1, 100_000, Decimal(95_000))]
    provenance = {
        "shop_id": shop.id,
        "platform": "shopee",
        "source": "extension",
        "source_rank": 3,
        "source_version": "0.3.36",
        "raw_payload_id": await _payload(session, shop.id, "extension", T2),
        "updated_at": T2,
    }
    with caplog.at_level(logging.WARNING):
        await write_order_lines(session, rows, None, provenance)
    (record,) = [
        r for r in caplog.records if r.getMessage() == "order_line_combo_discount_mismatch"
    ]
    assert (record.combo_id, record.expected, record.posted) == (88, "10000.00", "15000.00")
    stored = await session.execute(
        ShopeeOrderLine.__table__.select().order_by(ShopeeOrderLine.line_no)
    )
    assert [r.bundle_discount for r in stored] == [Decimal(10_000), Decimal(5_000)]
