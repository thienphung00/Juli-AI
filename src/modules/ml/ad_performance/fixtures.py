"""Golden campaign feature profiles for ad performance integration tests."""

from __future__ import annotations

from typing import Any

GOLDEN_AD_FIXTURES: list[dict[str, Any]] = [
    {
        "id": "scale",
        "features": {
            "spend_vnd": 3_000_000.0,
            "roas": 6.0,
            "cpc_vnd": 5_000.0,
            "conversions": 50,
            "impressions": 10_000,
            "clicks": 600,
            "account_avg_roas_30d": 3.0,
            "account_spend_velocity_30d": 50_000_000.0,
        },
        "expected_action": "scale",
    },
    {
        "id": "cut",
        "features": {
            "spend_vnd": 4_000_000.0,
            "roas": 0.5,
            "cpc_vnd": 30_000.0,
            "conversions": 20,
            "impressions": 8_000,
            "clicks": 120,
            "account_avg_roas_30d": 3.0,
            "account_spend_velocity_30d": 50_000_000.0,
        },
        "expected_action": "cut",
    },
    {
        "id": "sparse",
        "features": {
            "spend_vnd": 100_000.0,
            "roas": 2.0,
            "cpc_vnd": 0.0,
            "conversions": 0,
            "impressions": 5,
            "clicks": 1,
            "account_avg_roas_30d": 3.0,
            "account_spend_velocity_30d": 1_000_000.0,
        },
        "expected_action": "hold",
    },
]
