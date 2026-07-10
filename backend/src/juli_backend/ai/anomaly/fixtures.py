"""Golden buyer feature profiles for anomaly detector integration tests."""

from __future__ import annotations

from typing import Any

GOLDEN_ANOMALY_FIXTURES: list[dict[str, Any]] = [
    {
        "id": "item_swap",
        "features": {
            "buyer_return_count_30d": 4,
            "buyer_item_swap_count_30d": 3,
            "buyer_empty_return_count_30d": 0,
            "buyer_repeat_anomaly_flag": 1,
            "return_rate_30d": 0.18,
            "seller_fault_cancel_rate_30d": 0.0,
        },
        "expected_class": "item_swap",
    },
    {
        "id": "empty_return",
        "features": {
            "buyer_return_count_30d": 3,
            "buyer_item_swap_count_30d": 0,
            "buyer_empty_return_count_30d": 3,
            "buyer_repeat_anomaly_flag": 1,
            "return_rate_30d": 0.12,
            "seller_fault_cancel_rate_30d": 0.0,
        },
        "expected_class": "empty_return",
    },
    {
        "id": "other",
        "features": {
            "buyer_return_count_30d": 1,
            "buyer_item_swap_count_30d": 0,
            "buyer_empty_return_count_30d": 0,
            "buyer_repeat_anomaly_flag": 0,
            "return_rate_30d": 0.04,
            "seller_fault_cancel_rate_30d": 0.0,
        },
        "expected_class": "other",
    },
]
