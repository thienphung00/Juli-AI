"""Group A buyer-behavior anomaly feature builder."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.ai.features.exceptions import FeatureValidationError
from backend.ai.features.loader import (
    assert_anomaly_input_columns,
    load_order_items,
    load_orders,
    load_returns,
    resolve_dataset_dir,
)
from backend.ai.features.schema import ANOMALY_FEATURE_COLUMNS
from backend.ai.features.time_windows import in_last_n_days, resolve_reference_date
from backend.ai.features.types import FeatureMatrix


def _compute_shop_return_rate_30d(
    orders: pd.DataFrame,
    returns: pd.DataFrame,
    reference: pd.Timestamp,
) -> pd.DataFrame:
    delivered_mask = (orders["status"] == "delivered") & in_last_n_days(
        orders["delivery_time"], reference.to_pydatetime()
    )
    delivered_counts = (
        orders.loc[delivered_mask]
        .groupby("shop_id", as_index=False)
        .size()
        .rename(columns={"size": "delivered_orders_30d"})
    )

    return_mask = in_last_n_days(returns["created_at"], reference.to_pydatetime()) & (
        returns["status"] != "rejected"
    )
    return_counts = (
        returns.loc[return_mask]
        .groupby("shop_id", as_index=False)
        .size()
        .rename(columns={"size": "return_events_30d"})
    )

    merged = delivered_counts.merge(return_counts, on="shop_id", how="outer").fillna(0)
    merged["return_rate_30d"] = merged.apply(
        lambda row: (
            None
            if row["delivered_orders_30d"] == 0
            else row["return_events_30d"] / row["delivered_orders_30d"]
        ),
        axis=1,
    )
    return merged[["shop_id", "return_rate_30d"]]


def _compute_seller_fault_cancel_rate_30d(
    orders: pd.DataFrame,
    reference: pd.Timestamp,
) -> pd.DataFrame:
    window_mask = in_last_n_days(orders["created_at"], reference.to_pydatetime())
    window_orders = orders.loc[window_mask]
    if window_orders.empty:
        return pd.DataFrame(columns=["shop_id", "seller_fault_cancel_rate_30d"])

    grouped = window_orders.groupby("shop_id")
    rows: list[dict[str, Any]] = []
    for shop_id, shop_orders in grouped:
        total = len(shop_orders)
        if total == 0:
            rate = None
        elif shop_orders["is_seller_fault"].isna().all():
            rate = None
        else:
            seller_fault = shop_orders[
                (shop_orders["status"] == "cancelled") & (shop_orders["is_seller_fault"] == True)  # noqa: E712
            ]
            rate = len(seller_fault) / total
        rows.append({"shop_id": shop_id, "seller_fault_cancel_rate_30d": rate})
    return pd.DataFrame(rows)


def _compute_buyer_features(
    returns: pd.DataFrame,
    reference: pd.Timestamp,
) -> pd.DataFrame:
    window_mask = in_last_n_days(returns["created_at"], reference.to_pydatetime())
    window_returns = returns.loc[window_mask].copy()
    if window_returns.empty:
        return pd.DataFrame(
            columns=[
                "buyer_id",
                "shop_id",
                "buyer_return_count_30d",
                "buyer_item_swap_count_30d",
                "buyer_empty_return_count_30d",
                "buyer_repeat_anomaly_flag",
            ]
        )

    grouped = window_returns.groupby(["buyer_id", "shop_id"], as_index=False)
    rows: list[dict[str, Any]] = []
    for (buyer_id, shop_id), buyer_returns in grouped:
        return_count = len(buyer_returns)
        item_swap_count = int((buyer_returns["return_type"] == "item_swap").sum())
        empty_return_count = int((buyer_returns["return_type"] == "empty_return").sum())
        repeat_flag = 1 if (item_swap_count + empty_return_count) >= 2 else 0
        rows.append(
            {
                "buyer_id": buyer_id,
                "shop_id": shop_id,
                "buyer_return_count_30d": return_count,
                "buyer_item_swap_count_30d": item_swap_count,
                "buyer_empty_return_count_30d": empty_return_count,
                "buyer_repeat_anomaly_flag": repeat_flag,
            }
        )
    return pd.DataFrame(rows)


def build_anomaly_features(manifest: dict[str, Any]) -> FeatureMatrix:
    """Build Group A anomaly features from Order/OrderItem/Return parquet only."""
    root = resolve_dataset_dir(manifest)
    orders = load_orders(root)
    order_items = load_order_items(root)
    returns = load_returns(root)

    assert_anomaly_input_columns(orders, order_items, returns)

    reference_dt = resolve_reference_date(manifest, orders)
    reference = pd.Timestamp(reference_dt)
    feature_date = reference.date().isoformat()

    buyer_frame = _compute_buyer_features(returns, reference)
    shop_return_rate = _compute_shop_return_rate_30d(orders, returns, reference)
    shop_cancel_rate = _compute_seller_fault_cancel_rate_30d(orders, reference)

    if buyer_frame.empty:
        frame = pd.DataFrame(columns=["buyer_id", "shop_id", "feature_date", *ANOMALY_FEATURE_COLUMNS])
    else:
        frame = buyer_frame.merge(shop_return_rate, on="shop_id", how="left").merge(
            shop_cancel_rate, on="shop_id", how="left"
        )
        frame["feature_date"] = feature_date

    missing = [column for column in ANOMALY_FEATURE_COLUMNS if column not in frame.columns]
    if missing:
        raise FeatureValidationError(f"anomaly feature build missing columns: {missing}")

    ordered = frame[["buyer_id", "shop_id", "feature_date", *ANOMALY_FEATURE_COLUMNS]]
    return FeatureMatrix(
        grain="buyer×shop×date",
        feature_columns=ANOMALY_FEATURE_COLUMNS,
        frame=ordered,
        metadata={
            "reference_date": feature_date,
            "source_entities": ["Order", "OrderItem", "Return"],
        },
    )
