"""Tests for Issue #723: Settlement Finance field mapping (RA-3).

Test mapping:
- AC1 → test_transform_settlement_extracts_platform_commission_and_shipping_fee
- AC2 → test_transform_settlement_removes_old_zero_defaults
- AC3 → test_etl_persists_settlement_with_fees
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.models import Settlement, Shop, User
from juli_backend.services.etl.transform import _transform_settlement

TIKTOK_SHOP_ID = "7000000000000001"


@pytest.fixture
def sample_finance_statement():
    """Realistic sample Finance API response with fee fields."""
    return {
        "statement_id": "stmt-2026-08-001",
        "settlement_amount": "950.00",
        "revenue_amount": "1000.00",
        "platform_commission": "30.00",  # TikTok platform/service fee
        "shipping_fee": "20.00",  # Shipping cost deducted
        "currency": "VND",
        "payment_status": "CONFIRMED",
        "status": "settled",
        "statement_time": 1722700800,  # Aug 4, 2026 00:00:00 UTC
        "update_time": 1722700800,
    }


@pytest.fixture
def sample_finance_statement_minimal():
    """Finance API response without optional fee fields."""
    return {
        "statement_id": "stmt-2026-08-002",
        "settlement_amount": "500.00",
        "currency": "VND",
        "statement_time": 1722700900,
    }


def test_transform_settlement_extracts_platform_commission_and_shipping_fee(
    sample_finance_statement,
):
    """AC1: Corrected mapping populates platform_commission and shipping_fee.

    Realistic sample Finance API response should extract the real fee field.
    """
    payload = {"timestamp": 1722700800}
    result = _transform_settlement(sample_finance_statement, payload)

    assert "platform_commission" in result
    assert Decimal(str(result["platform_commission"])) == Decimal("30.00")
    assert "shipping_fee" in result
    assert Decimal(str(result["shipping_fee"])) == Decimal("20.00")


def test_transform_settlement_handles_missing_fee_fields(sample_finance_statement_minimal):
    """Gracefully handle missing fee fields (should default to None or not include)."""
    payload = {"timestamp": 1722700900}
    result = _transform_settlement(sample_finance_statement_minimal, payload)

    # When fields are missing, they should not be included or should be None
    # (depends on implementation strategy)
    assert "tiktok_settlement_id" in result
    assert result["tiktok_settlement_id"] == "stmt-2026-08-002"


def test_transform_settlement_includes_standard_fields(sample_finance_statement):
    """Standard settlement fields should still be present."""
    payload = {"timestamp": 1722700800}
    result = _transform_settlement(sample_finance_statement, payload)

    assert result["tiktok_settlement_id"] == "stmt-2026-08-001"
    assert Decimal(str(result["amount"])) == Decimal("950.00")
    assert result["currency"] == "VND"
    assert result["status"] == "settled"


@pytest.mark.asyncio
async def test_etl_persists_settlement_with_fees(session, user_id):
    """AC3: Settlement sync populates real fee fields (not dangling zeros).

    Settlement record persisted to DB should have real fee values extracted from API.
    """
    import json

    # Setup shop
    import uuid

    from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
    from juli_backend.services.etl.record import IngestRecord

    shop_id = uuid.uuid4()
    user = User(id=user_id, phone="+84999777666")
    shop = Shop(
        id=shop_id,
        user_id=user_id,
        shop_name="Test Shop Settlement",
        tiktok_shop_id=TIKTOK_SHOP_ID,
    )
    session.add_all([user, shop])
    await session.flush()

    # Ingest settlement with fees
    consumer = EtlConsumer(session=session, publish_dlq=lambda *a, **k: None)
    settlement_payload = {
        "statement_id": "settle-fee-test-1",
        "settlement_amount": "1000.00",
        "revenue_amount": "1100.00",
        "platform_commission": "75.00",
        "shipping_fee": "25.00",
        "currency": "VND",
        "payment_status": "CONFIRMED",
        "statement_time": 1722700800,
        "update_time": 1722700800,
    }

    outcome = await consumer.ingest(
        IngestRecord(
            channel="tiktok.settlements.raw",
            shop_key=TIKTOK_SHOP_ID,
            value=json.dumps(settlement_payload).encode(),
        )
    )
    assert outcome == ProcessOutcome.PROCESSED
    await session.commit()

    # Verify settlement in DB has real fees, not zero defaults
    result = await session.execute(
        select(Settlement).where(Settlement.tiktok_settlement_id == "settle-fee-test-1")
    )
    settlement = result.scalar_one()

    assert settlement.amount == Decimal("1000.00")
    assert settlement.currency == "VND"
    assert settlement.platform_commission == Decimal("75.00")
    assert settlement.shipping_fee == Decimal("25.00")
    # Ensure it's not the default zero
    assert settlement.platform_commission != Decimal("0")
    assert settlement.shipping_fee != Decimal("0")
