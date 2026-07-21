"""Unit tests for analytics ETL normalizers and transform (#425)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from juli_backend.integrations.tiktok.mapping import (
    analytics_snapshot_key,
    expand_analytics_live_session,
    expand_analytics_product_detail,
    expand_analytics_shop_performance,
    expand_analytics_sku_detail,
)
from juli_backend.services.etl.transform import TransformError, transform_for_channel


def test_analytics_snapshot_key_includes_grain_date_and_entity_ids():
    key = analytics_snapshot_key(
        grain="sku",
        start_date="2026-07-13",
        end_date="2026-07-14",
        sku_id="sku-1",
        product_id="prod-1",
    )
    assert key == "sku|2026-07-13|2026-07-14||prod-1|sku-1|"


def test_expand_shop_performance_maps_metrics_without_fabrication():
    rows = expand_analytics_shop_performance(
        {
            "performance": {
                "intervals": [
                    {
                        "start_date": "2026-07-13",
                        "end_date": "2026-07-14",
                        "sales": {
                            "gmv": {"overall": {"amount": "100.00", "currency": "VND"}},
                            "sku_orders_count": 2,
                        },
                        "traffic": {"avg_visitors": 10},
                    }
                ]
            }
        },
        synced_at=1_700_000_000,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["gmv"] == "100.00"
    assert row["sku_orders"] == 2
    assert row["visitors"] == 10
    assert "ctr" not in row


def test_transform_analytics_persists_optional_decimal_fields():
    _, kwargs = transform_for_channel(
        "tiktok.analytics.product.raw",
        {
            "grain": "product",
            "start_date": "2026-07-13",
            "end_date": "2026-07-14",
            "product_id": "prod-1",
            "snapshot_key": "product|2026-07-13|2026-07-14|||prod-1||",
            "gmv": "50.00",
            "gmv_currency": "VND",
            "ctr": "0.0759",
            "update_time": 1_700_000_000,
        },
    )
    assert kwargs["tiktok_product_id"] == "prod-1"
    assert kwargs["gmv"] == Decimal("50.00")
    assert kwargs["ctr"] == Decimal("0.0759")
    assert "click_through_rate" not in kwargs


def test_transform_analytics_requires_start_date():
    with pytest.raises(TransformError, match="start_date"):
        transform_for_channel("tiktok.analytics.shop.raw", {"grain": "shop"})


def test_expand_product_detail_includes_product_id_in_snapshot_key():
    detail = {
        "performance": {
            "intervals": [
                {
                    "start_date": "2026-07-13",
                    "end_date": "2026-07-14",
                    "sales": {
                        "gmv": {"amount": "10.00", "currency": "VND"},
                        "orders": 1,
                    },
                    "traffic": {"breakdowns": []},
                }
            ]
        }
    }
    rows_a = expand_analytics_product_detail(
        detail, synced_at=1_700_000_000, product_id="prod-a"
    )
    rows_b = expand_analytics_product_detail(
        detail, synced_at=1_700_000_000, product_id="prod-b"
    )
    assert len(rows_a) == 1
    assert len(rows_b) == 1
    assert rows_a[0]["product_id"] == "prod-a"
    assert rows_b[0]["product_id"] == "prod-b"
    assert rows_a[0]["snapshot_key"] != rows_b[0]["snapshot_key"]
    assert "prod-a" in rows_a[0]["snapshot_key"]
    assert "prod-b" in rows_b[0]["snapshot_key"]


def test_expand_live_session_includes_live_id_in_snapshot_key():
    row = expand_analytics_live_session(
        {
            "id": "live-123",
            "sales_performance": {
                "gmv": {"amount": "100.00", "currency": "VND"},
                "sku_orders": 2,
            },
            "interaction_performance": {"click_through_rate": "9.96%"},
        },
        start_date="2026-07-13",
        end_date="2026-07-14",
        synced_at=1_700_000_000,
    )
    assert row is not None
    assert row["grain"] == "live"
    assert row["live_id"] == "live-123"
    assert "live-123" in row["snapshot_key"]


def test_expand_sku_detail_produces_one_row_per_interval():
    rows = expand_analytics_sku_detail(
        {
            "performance": {
                "sku_id": "sku-1",
                "product_id": "prod-1",
                "intervals": [
                    {
                        "start_date": "2026-07-13",
                        "end_date": "2026-07-14",
                        "gmv": {"amount": "1.00", "currency": "VND"},
                        "sku_orders": 1,
                    }
                ],
            }
        },
        synced_at=1_700_000_000,
    )
    assert len(rows) == 1
    assert rows[0]["sku_id"] == "sku-1"
