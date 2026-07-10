"""Shop-level seller stage feature builder."""

from __future__ import annotations

from typing import Any

import pandas as pd

from juli_backend.ai.features.loader import load_ads, load_orders, load_returns, resolve_dataset_dir
from juli_backend.ai.features.schema import SELLER_STAGE_FEATURE_COLUMNS
from juli_backend.ai.features.time_windows import in_last_n_days, parse_timestamp, resolve_reference_date
from juli_backend.ai.features.types import FeatureMatrix


def _compute_return_rate_30d(
    orders: pd.DataFrame,
    returns: pd.DataFrame,
    reference: pd.Timestamp,
) -> pd.Series:
    delivered_mask = (orders["status"] == "delivered") & in_last_n_days(
        orders["delivery_time"], reference.to_pydatetime()
    )
    delivered = orders.loc[delivered_mask].groupby("shop_id").size()

    return_mask = in_last_n_days(returns["created_at"], reference.to_pydatetime()) & (
        returns["status"] != "rejected"
    )
    return_counts = returns.loc[return_mask].groupby("shop_id").size()

    rates: dict[str, float | None] = {}
    for shop_id in set(delivered.index).union(set(return_counts.index)):
        delivered_count = int(delivered.get(shop_id, 0))
        if delivered_count == 0:
            rates[shop_id] = None
        else:
            rates[shop_id] = float(return_counts.get(shop_id, 0)) / delivered_count
    return pd.Series(rates, name="return_rate_30d")


def build_seller_stage_features(manifest: dict[str, Any]) -> FeatureMatrix:
    """Build shop-level seller stage classifier features."""
    root = resolve_dataset_dir(manifest)
    orders = load_orders(root)
    returns = load_returns(root)
    ads = load_ads(root)

    reference_dt = resolve_reference_date(manifest, orders)
    reference = pd.Timestamp(reference_dt)
    feature_date = reference.date().isoformat()

    shop_ids = sorted(set(orders["shop_id"].unique()).union(set(ads["shop_id"].unique())))
    rows: list[dict[str, Any]] = []

    return_rates = _compute_return_rate_30d(orders, returns, reference)
    order_window = orders.loc[in_last_n_days(orders["created_at"], reference.to_pydatetime())]
    ads_window = ads.loc[in_last_n_days(ads["date"], reference.to_pydatetime())]

    for shop_id in shop_ids:
        shop_orders = orders.loc[orders["shop_id"] == shop_id]
        created_times = shop_orders["created_at"].map(parse_timestamp).dropna()
        shop_age_days = (
            (reference.to_pydatetime() - created_times.min()).days if not created_times.empty else 0
        )

        order_count_30d = int((order_window["shop_id"] == shop_id).sum())

        delivered_window = order_window[
            (order_window["shop_id"] == shop_id) & (order_window["status"] == "delivered")
        ]
        gmv_30d_vnd = float(
            delivered_window["order_value"].astype(float).sum()
            if not delivered_window.empty
            else 0.0
        )

        shop_ads = ads_window.loc[ads_window["shop_id"] == shop_id]
        ad_spend_30d_vnd = float(
            shop_ads["spend_vnd"].astype(float).sum() if not shop_ads.empty else 0.0
        )

        rows.append(
            {
                "shop_id": shop_id,
                "feature_date": feature_date,
                "shop_age_days": shop_age_days,
                "order_count_30d": order_count_30d,
                "return_rate_30d": return_rates.get(shop_id),
                "ad_spend_30d_vnd": ad_spend_30d_vnd,
                "gmv_30d_vnd": gmv_30d_vnd,
            }
        )

    frame = pd.DataFrame(rows)
    return FeatureMatrix(
        grain="shop×date",
        feature_columns=SELLER_STAGE_FEATURE_COLUMNS,
        frame=frame,
        metadata={"reference_date": feature_date},
    )
