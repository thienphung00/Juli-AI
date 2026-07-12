"""Vendor field mapping for TikTok Shop API responses."""

from decimal import Decimal

from juli_backend.integrations.tiktok.mapping import (
    expand_order_line_items,
    normalize_creator,
    normalize_livestream,
    normalize_order,
    normalize_product,
    normalize_return,
    normalize_statement,
)
from juli_backend.services.etl.transform import transform_for_channel


class TestNormalizeOrder:
    def test_maps_id_user_id_and_nested_payment(self):
        raw = {
            "id": "577000000000001",
            "user_id": "buyer-masked-1",
            "status": "AWAITING_SHIPMENT",
            "update_time": 1_700_000_100,
            "payment": {"total_amount": "199.50", "currency": "VND"},
        }

        mapped = normalize_order(raw)

        assert mapped["order_id"] == "577000000000001"
        assert mapped["buyer_id"] == "buyer-masked-1"
        assert mapped["total_amount"] == "199.50"
        assert mapped["currency"] == "VND"

    def test_preserves_legacy_handoff_shape(self):
        raw = {
            "order_id": "o1",
            "buyer_id": "b1",
            "status": "CANCELLED",
            "total_amount": "50.00",
            "update_time": 1_700_000_000,
        }

        mapped = normalize_order(raw)

        assert mapped["order_id"] == "o1"
        assert mapped["buyer_id"] == "b1"
        assert mapped["total_amount"] == "50.00"

    def test_derives_is_seller_fault_from_cancellation_initiator(self):
        raw = {
            "id": "o-cancel",
            "status": "CANCELLED",
            "cancellation_initiator": "SELLER",
            "update_time": 1_700_000_000,
            "payment": {"total_amount": "10.00"},
        }

        mapped = normalize_order(raw)

        assert mapped["is_seller_fault"] is True

    def test_expand_order_line_items_from_official_shape(self):
        order = {
            "id": "ord-1",
            "update_time": 1_700_000_000,
            "line_items": [
                {
                    "sku_id": "sku-a",
                    "product_id": "prod-a",
                    "sale_price": "50.00",
                    "quantity": 2,
                }
            ],
        }

        items = expand_order_line_items(normalize_order(order))

        assert len(items) == 1
        assert items[0]["tiktok_order_id"] == "ord-1"
        assert items[0]["sku_id"] == "sku-a"
        assert items[0]["line_total"] == "100.00"


class TestNormalizeProduct:
    def test_maps_id_and_audit_status(self):
        mapped = normalize_product({
            "id": "prod-1",
            "title": "Widget",
            "audit": {"status": "ON_SALE"},
        })

        assert mapped["product_id"] == "prod-1"
        assert mapped["name"] == "Widget"
        assert mapped["status"] == "ON_SALE"


class TestNormalizeReturn:
    def test_maps_return_id_nested_refund_and_line_items(self):
        mapped = normalize_return({
            "return_id": "ret-1",
            "order_id": "ord-9",
            "user_id": "buyer-1",
            "refund": {"refund_total": "75.50"},
            "return_line_items": [{"sku_id": "sku-x", "product_id": "prod-x"}],
            "return_status": "APPROVED",
            "update_time": 1_700_000_100,
        })

        assert mapped["tiktok_order_id"] == "ord-9"
        assert mapped["buyer_id"] == "buyer-1"
        assert mapped["refund_amount"] == "75.50"
        assert mapped["sku_id"] == "sku-x"
        assert mapped["return_type"] == "other"

    def test_flattens_nested_refund_amount_object_from_contract_sample(self):
        mapped = normalize_return({
            "return_id": "4035463945335048707",
            "order_id": "579238058323577347",
            "refund_amount": {
                "currency": "VND",
                "refund_total": "864000",
            },
            "return_line_items": [{"sku_id": "1730420785344318071"}],
            "return_status": "RETURN_OR_REFUND_REQUEST_COMPLETE",
            "update_time": 1724833101,
        })

        assert mapped["refund_amount"] == "864000"


class TestNormalizeCreatorAndStatement:
    def test_normalize_creator_maps_user_id_and_nickname(self):
        mapped = normalize_creator({"creator_user_id": "c9", "nickname": "Star"})
        assert mapped["creator_id"] == "c9"
        assert mapped["name"] == "Star"

    def test_normalize_livestream_maps_room_and_metrics(self):
        mapped = normalize_livestream({
            "room_id": "ls9",
            "total_viewers": 500,
            "orders_placed": 12,
            "total_sale_gmv": "300.00",
            "end_time": 1_700_000_000,
        })
        assert mapped["livestream_id"] == "ls9"
        assert mapped["viewer_count"] == 500
        assert mapped["order_count"] == 12

    def test_normalize_statement_maps_statement_fields(self):
        mapped = normalize_statement({
            "statement_id": "st-1",
            "settlement_amount": "88.00",
            "statement_time": 1_700_000_000,
            "payment_status": "PAID",
        })
        assert mapped["settlement_id"] == "st-1"
        assert mapped["amount"] == "88.00"
        assert mapped["status"] == "PAID"


class TestTransformOrder:
    def test_transform_accepts_official_api_shape(self):
        payload = {
            "id": "577000000000002",
            "user_id": "buyer-2",
            "order_status": "UNPAID",
            "update_time": 1_700_000_200,
            "payment": {"total_amount": "88.00", "currency": "VND"},
        }

        kind, row = transform_for_channel("tiktok.orders.raw", payload)

        assert kind == "order"
        assert row["tiktok_order_id"] == "577000000000002"
        assert row["buyer_id"] == "buyer-2"
        assert row["total_amount"] == Decimal("88.00")
