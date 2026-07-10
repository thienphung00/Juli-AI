"""Unit and integration tests for Phase 1.5 feature builders — Issue #137."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from juli_backend.ai.dataset import assemble_backtest_dataset
from juli_backend.ai.features import (
    AD_FEATURE_COLUMNS,
    ANOMALY_FEATURE_COLUMNS,
    SELLER_STAGE_FEATURE_COLUMNS,
    FeatureValidationError,
    build_ad_features,
    build_anomaly_features,
    build_seller_stage_features,
)


@pytest.fixture
def tiny_dataset_dir(tmp_path: Path) -> Path:
    output_dir = tmp_path / "backtest"
    assemble_backtest_dataset(
        output_dir,
        seed=137,
        n_shops=1,
        orders_per_shop=12,
        return_rate=0.5,
        ads_days=5,
    )
    return output_dir


@pytest.fixture
def tiny_manifest(tiny_dataset_dir: Path) -> dict:
    import json

    manifest = json.loads((tiny_dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    return manifest


def test_anomaly_feature_columns_match_feature_store_schema(tiny_manifest: dict):
    """Golden mini-parquet → anomaly feature matrix column names match schema exactly."""
    matrix = build_anomaly_features(tiny_manifest)

    assert matrix.feature_columns == ANOMALY_FEATURE_COLUMNS
    assert list(matrix.frame.columns[-len(ANOMALY_FEATURE_COLUMNS) :]) == list(
        ANOMALY_FEATURE_COLUMNS
    )


def test_anomaly_builder_rejects_affiliate_creator_columns(
    tiny_dataset_dir: Path,
    tiny_manifest: dict,
):
    """Anomaly builder raises when affiliate/creator columns are present in input."""
    orders_path = tiny_dataset_dir / "orders.parquet"
    orders = pd.read_parquet(orders_path)
    orders["creator_id"] = "creator-forbidden"
    orders.to_parquet(orders_path, index=False)

    with pytest.raises(FeatureValidationError, match="forbidden affiliate/creator"):
        build_anomaly_features(tiny_manifest)


def test_buyer_aggregate_counts_match_hand_computed_fixture(tmp_path: Path):
    """Buyer aggregate counts match hand-computed expected values on fixture."""
    dataset_dir = tmp_path / "golden"
    dataset_dir.mkdir()
    reference = datetime(2026, 6, 1, tzinfo=UTC)
    recent = (reference - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    old = (reference - timedelta(days=40)).isoformat().replace("+00:00", "Z")

    shop_id = "shop-golden"
    buyer_id = "buyer_golden"

    orders = pd.DataFrame(
        [
            {
                "order_id": "o1",
                "tiktok_order_id": "t1",
                "shop_id": shop_id,
                "buyer_id": buyer_id,
                "status": "delivered",
                "order_value": "100000.00",
                "currency": "VND",
                "payment_time": recent,
                "ship_time": recent,
                "delivery_time": recent,
                "created_at": recent,
                "cancel_reason": None,
                "is_seller_fault": False,
            },
            {
                "order_id": "o2",
                "tiktok_order_id": "t2",
                "shop_id": shop_id,
                "buyer_id": buyer_id,
                "status": "cancelled",
                "order_value": "50000.00",
                "currency": "VND",
                "payment_time": None,
                "ship_time": None,
                "delivery_time": None,
                "created_at": recent,
                "cancel_reason": "seller delay",
                "is_seller_fault": True,
            },
        ]
    )
    order_items = pd.DataFrame(
        [
            {
                "id": "oi1",
                "order_id": "o1",
                "tiktok_order_id": "t1",
                "product_id": "p1",
                "sku_id": "sku-a",
                "quantity": 1,
                "unit_price": "100000.00",
                "line_total": "100000.00",
            }
        ]
    )
    returns = pd.DataFrame(
        [
            {
                "return_id": "r1",
                "tiktok_return_id": "tr1",
                "order_id": "o1",
                "tiktok_order_id": "t1",
                "shop_id": shop_id,
                "buyer_id": buyer_id,
                "product_id": "p1",
                "sku_id": "sku-a",
                "return_type": "item_swap",
                "return_condition": "wrong_item",
                "return_reason": "wrong item",
                "refund_amount": "100000.00",
                "status": "approved",
                "created_at": recent,
            },
            {
                "return_id": "r2",
                "tiktok_return_id": "tr2",
                "order_id": "o1",
                "tiktok_order_id": "t1",
                "shop_id": shop_id,
                "buyer_id": buyer_id,
                "product_id": "p1",
                "sku_id": "sku-b",
                "return_type": "item_swap",
                "return_condition": "wrong_item",
                "return_reason": "wrong item again",
                "refund_amount": "100000.00",
                "status": "approved",
                "created_at": recent,
            },
            {
                "return_id": "r3",
                "tiktok_return_id": "tr3",
                "order_id": "o1",
                "tiktok_order_id": "t1",
                "shop_id": shop_id,
                "buyer_id": buyer_id,
                "product_id": "p1",
                "sku_id": "sku-a",
                "return_type": "empty_return",
                "return_condition": "empty_parcel",
                "return_reason": "empty",
                "refund_amount": "100000.00",
                "status": "approved",
                "created_at": recent,
            },
            {
                "return_id": "r-old",
                "tiktok_return_id": "tr-old",
                "order_id": "o1",
                "tiktok_order_id": "t1",
                "shop_id": shop_id,
                "buyer_id": buyer_id,
                "product_id": "p1",
                "sku_id": "sku-a",
                "return_type": "item_swap",
                "return_condition": "wrong_item",
                "return_reason": "stale",
                "refund_amount": "100000.00",
                "status": "approved",
                "created_at": old,
            },
        ]
    )

    orders.to_parquet(dataset_dir / "orders.parquet", index=False)
    order_items.to_parquet(dataset_dir / "order_items.parquet", index=False)
    returns.to_parquet(dataset_dir / "returns.parquet", index=False)

    manifest = {
        "dataset_dir": str(dataset_dir.resolve()),
        "date_range": {"start": recent[:10], "end": reference.date().isoformat()},
    }

    matrix = build_anomaly_features(manifest)
    row = matrix.frame.loc[
        (matrix.frame["buyer_id"] == buyer_id) & (matrix.frame["shop_id"] == shop_id)
    ].iloc[0]

    assert row["buyer_return_count_30d"] == 3
    assert row["buyer_item_swap_count_30d"] == 2
    assert row["buyer_empty_return_count_30d"] == 1
    assert row["buyer_repeat_anomaly_flag"] == 1
    assert row["return_rate_30d"] == pytest.approx(3 / 1)
    assert row["seller_fault_cancel_rate_30d"] == pytest.approx(0.5)


def test_all_three_builders_run_on_tiny_dataset_fixture(tiny_manifest: dict):
    """Integration test: all three builders run on #136 tiny fixture without error."""
    seller_matrix = build_seller_stage_features(tiny_manifest)
    anomaly_matrix = build_anomaly_features(tiny_manifest)
    ad_matrix = build_ad_features(tiny_manifest)

    assert seller_matrix.feature_columns == SELLER_STAGE_FEATURE_COLUMNS
    assert not seller_matrix.frame.empty

    assert anomaly_matrix.feature_columns == ANOMALY_FEATURE_COLUMNS
    assert not anomaly_matrix.frame.empty

    assert ad_matrix.feature_columns == AD_FEATURE_COLUMNS
    assert not ad_matrix.frame.empty

    for column in AD_FEATURE_COLUMNS:
        assert column in ad_matrix.frame.columns
