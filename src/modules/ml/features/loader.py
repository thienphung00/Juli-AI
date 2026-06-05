"""Parquet loading and anomaly-path column guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.modules.ml.dataset.schema import (
    ORDER_ITEMS_COLUMNS,
    ORDERS_COLUMNS,
    RETURNS_COLUMNS,
)
from src.modules.ml.features.exceptions import FeatureValidationError
from src.modules.ml.features.schema import (
    FORBIDDEN_ANOMALY_INPUT_COLUMNS,
    FORBIDDEN_ANOMALY_INPUT_PREFIXES,
)


def resolve_dataset_dir(manifest: dict[str, Any]) -> Path:
    dataset_dir = manifest.get("dataset_dir")
    if not dataset_dir:
        raise FeatureValidationError(
            "manifest missing 'dataset_dir'; assemble_backtest_dataset must set it"
        )
    root = Path(dataset_dir)
    if not root.is_dir():
        raise FeatureValidationError(f"dataset_dir does not exist: {root}")
    return root


def load_orders(root: Path) -> pd.DataFrame:
    return pd.read_parquet(root / "orders.parquet")


def load_order_items(root: Path) -> pd.DataFrame:
    return pd.read_parquet(root / "order_items.parquet")


def load_returns(root: Path) -> pd.DataFrame:
    return pd.read_parquet(root / "returns.parquet")


def load_ads(root: Path) -> pd.DataFrame:
    return pd.read_parquet(root / "ads.parquet")


def _is_forbidden_column(name: str) -> bool:
    lowered = name.lower()
    if lowered in FORBIDDEN_ANOMALY_INPUT_COLUMNS:
        return True
    return any(lowered.startswith(prefix) for prefix in FORBIDDEN_ANOMALY_INPUT_PREFIXES)


def assert_anomaly_input_columns(
    orders: pd.DataFrame,
    order_items: pd.DataFrame,
    returns: pd.DataFrame,
) -> None:
    """Reject affiliate/creator columns in anomaly feature inputs (ADR-011)."""
    for frame_name, frame, allowed in (
        ("orders", orders, ORDERS_COLUMNS),
        ("order_items", order_items, ORDER_ITEMS_COLUMNS),
        ("returns", returns, RETURNS_COLUMNS),
    ):
        extra = [column for column in frame.columns if column not in allowed]
        forbidden = [column for column in frame.columns if _is_forbidden_column(column)]
        if forbidden:
            raise FeatureValidationError(
                f"{frame_name}.parquet contains forbidden affiliate/creator columns: "
                f"{', '.join(sorted(forbidden))}"
            )
        if extra:
            raise FeatureValidationError(
                f"{frame_name}.parquet contains non-canonical columns: "
                f"{', '.join(sorted(extra))}"
            )
