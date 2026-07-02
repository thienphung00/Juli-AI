"""Campaign/day ad performance feature builder."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.ai.features.loader import load_ads, load_orders, resolve_dataset_dir
from backend.ai.features.schema import AD_FEATURE_COLUMNS
from backend.ai.features.time_windows import in_last_n_days, resolve_reference_date
from backend.ai.features.types import FeatureMatrix


def build_ad_features(manifest: dict[str, Any]) -> FeatureMatrix:
    """Build campaign/day ad features with account-level baselines."""
    root = resolve_dataset_dir(manifest)
    ads = load_ads(root)
    orders = load_orders(root)

    reference_dt = resolve_reference_date(manifest, orders)
    reference = pd.Timestamp(reference_dt)
    window = ads.loc[in_last_n_days(ads["date"], reference.to_pydatetime())].copy()

    if window.empty:
        frame = pd.DataFrame(columns=["shop_id", "campaign_id", "date", *AD_FEATURE_COLUMNS])
        return FeatureMatrix(
            grain="campaign×day",
            feature_columns=AD_FEATURE_COLUMNS,
            frame=frame,
            metadata={"reference_date": reference.date().isoformat()},
        )

    window["spend_vnd"] = window["spend_vnd"].astype(float)
    window["cpc_vnd"] = window["cpc_vnd"].astype(float)
    window["roas"] = window["roas"].astype(float)

    shop_baselines = (
        window.groupby("shop_id", as_index=False)
        .agg(
            account_avg_roas_30d=("roas", "mean"),
            account_spend_velocity_30d=("spend_vnd", "sum"),
        )
    )

    frame = window.merge(shop_baselines, on="shop_id", how="left")
    frame = frame[["shop_id", "campaign_id", "date", *AD_FEATURE_COLUMNS]]

    return FeatureMatrix(
        grain="campaign×day",
        feature_columns=AD_FEATURE_COLUMNS,
        frame=frame,
        metadata={"reference_date": reference.date().isoformat()},
    )
