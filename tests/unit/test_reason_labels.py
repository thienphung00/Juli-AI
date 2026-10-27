"""Cancel / return reasons keep a platform reason only; anything else is "other" (decision A).

Owner decision A (2026-10-27; D16, audit gap 5): a reason field can carry free text a
buyer typed, so ``services/privacy/reason_labels.safe_reason`` keeps a machine reason
code (identifier-shaped) or a catalogued platform label and stores every other value
as ``"other"``. Each case -- free text, a known label, a code -- is proven at each
place the rule applies: the function, the bronze allowlist (orders, returns,
cancellations), the silver transform and the operator clean-up of stored rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from juli_backend.models.models import Order
from juli_backend.services.etl.transform import (
    bronze_order_to_upsert_kwargs,
    bronze_return_to_upsert_kwargs,
)
from juli_backend.services.privacy.payload_allowlist import (
    ORDERS_RAW,
    RETURNS_RAW,
    TIKTOK,
    allowlist_payload,
)
from juli_backend.services.privacy.payload_cleanup import clean_shop
from juli_backend.services.privacy.reason_labels import LABELS, OTHER, REASON_CODE, safe_reason
from tests.support.builders import make_order, make_tenant

FREE_TEXT = "Shop giao sai màu, gọi lại cho tôi 0900000000 nhé"
CODE = "ecom_order_delivered_refund_and_return_reason_wrong_item"
RECEIVED = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("cancel_reason", FREE_TEXT, OTHER),
        ("cancel_reason", "Out of stock", "Out of stock"),
        (
            "cancel_reason",
            "seller_cancel_paid_reason_address_not_deliver",
            ("seller_cancel_paid_reason_address_not_deliver"),
        ),
        ("return_reason", CODE, CODE),
        ("return_reason", "wrong item", OTHER),
        ("return_reason_text", "Wrong item", "Wrong item"),
        ("return_reason_text", f"{FREE_TEXT}!", OTHER),
        ("cancel_reason_text", "Changed my mind", "Changed my mind"),
        ("cancel_reason_text", "OUT_OF_STOCK", OTHER),
        ("cancel_reason", None, None),
        ("cancel_reason", "", ""),
        ("cancel_reason", {"text": "x"}, OTHER),
        ("cancel_reason", OTHER, OTHER),
    ],
)
def test_safe_reason(field, value, expected):
    assert safe_reason(TIKTOK, field, value) == expected


def test_a_label_of_another_field_or_platform_is_not_borrowed():
    assert safe_reason(TIKTOK, "cancel_reason_text", "Wrong item") == OTHER
    assert safe_reason("shopee", "cancel_reason", "Out of stock") == OTHER


def test_the_catalog_holds_no_code_and_every_entry_is_wired():
    assert LABELS, "the catalog must exist even when a field's set is small"
    for (platform, field), labels in LABELS.items():
        for label in labels:
            assert not REASON_CODE.match(label), label
            assert safe_reason(platform, field, label) == label


def test_the_order_allowlist_maps_the_cancel_reason():
    for value, expected in (
        (FREE_TEXT, OTHER),
        ("Out of stock", "Out of stock"),
        ("out_of_stock", "out_of_stock"),
    ):
        kept = allowlist_payload(TIKTOK, ORDERS_RAW, {"order_id": "1", "cancel_reason": value})
        assert kept == {"order_id": "1", "cancel_reason": expected}


def test_the_return_allowlist_maps_every_reason_field():
    kept = allowlist_payload(
        TIKTOK,
        RETURNS_RAW,
        {
            "return_id": "r1",
            "return_reason": CODE,
            "return_reason_text": FREE_TEXT,
            "cancel_reason": "change_my_mind",
            "cancel_reason_text": "Changed my mind",
        },
    )
    assert kept == {
        "return_id": "r1",
        "return_reason": CODE,
        "return_reason_text": OTHER,
        "cancel_reason": "change_my_mind",
        "cancel_reason_text": "Changed my mind",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [(FREE_TEXT, OTHER), ("Pricing error", "Pricing error"), ("out_of_stock", "out_of_stock")],
)
def test_silver_orders_cancel_reason(value, expected):
    kwargs = bronze_order_to_upsert_kwargs(
        {"order_id": "1", "status": "CANCELLED", "update_time": 1761530000, "cancel_reason": value},
        received_at=RECEIVED,
    )
    assert kwargs["cancel_reason"] == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"return_reason": FREE_TEXT}, OTHER),
        ({"return_reason": "Wrong item"}, "Wrong item"),
        ({"return_reason": CODE}, CODE),
        ({"cancel_reason": "Changed my mind"}, "Changed my mind"),
    ],
)
def test_silver_returns_return_reason(body, expected):
    kwargs = bronze_return_to_upsert_kwargs(
        {"return_id": "r1", "order_id": "o1", "update_time": 1761530000, **body},
        received_at=RECEIVED,
    )
    assert kwargs["return_reason"] == expected


@pytest.mark.asyncio
async def test_the_clean_up_maps_stored_silver_reasons(session):
    _, shop = await make_tenant(session)
    await make_order(session, shop, cancel_reason=FREE_TEXT)
    await make_order(session, shop, cancel_reason="Out of stock")
    await make_order(session, shop, cancel_reason="seller_cancel_paid_reason_address_not_deliver")

    first = await clean_shop(session, shop.id)
    assert first["public.orders"].changed == 1
    reasons = sorted(
        (await session.execute(select(Order.cancel_reason).where(Order.shop_id == shop.id)))
        .scalars()
        .all()
    )
    assert reasons == ["Out of stock", OTHER, "seller_cancel_paid_reason_address_not_deliver"]

    second = await clean_shop(session, shop.id)
    assert second["public.orders"].changed == 0
