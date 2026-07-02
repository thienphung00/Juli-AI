"""Schema validation for assembled backtest parquet datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from backend.ai.dataset.exceptions import DatasetValidationError
from backend.ai.dataset.schema import (
    ADS_COLUMNS,
    LABELS_COLUMNS,
    ORDER_ITEMS_COLUMNS,
    ORDERS_COLUMNS,
    REQUIRED_PARQUET_FILES,
    RETURN_CONDITION_VALUES,
    RETURN_STATUS_VALUES,
    RETURN_TYPE_VALUES,
    RETURNS_COLUMNS,
)


def _missing_columns(actual: list[str], required: tuple[str, ...]) -> list[str]:
    return [column for column in required if column not in actual]


def _validate_enum_column(
    df: pd.DataFrame,
    column: str,
    allowed: frozenset[str],
    file_name: str,
) -> None:
    if column not in df.columns:
        return
    invalid = sorted({str(value) for value in df[column].dropna().unique()} - allowed)
    if invalid:
        raise DatasetValidationError(
            f"{file_name}: column '{column}' has invalid values {invalid}. "
            f"Allowed: {sorted(allowed)}"
        )


def validate_backtest_dataset(output_dir: str | Path) -> dict[str, Any]:
    """Validate parquet files and manifest under output_dir. Raises on failure."""
    root = Path(output_dir)
    if not root.exists():
        raise DatasetValidationError(f"Dataset directory does not exist: {root}")

    for file_name in REQUIRED_PARQUET_FILES:
        path = root / file_name
        if not path.exists():
            raise DatasetValidationError(
                f"Missing required parquet file: {file_name}. "
                f"Expected all of {list(REQUIRED_PARQUET_FILES)} in {root}"
            )

    orders_df = pd.read_parquet(root / "orders.parquet")
    order_items_df = pd.read_parquet(root / "order_items.parquet")
    returns_df = pd.read_parquet(root / "returns.parquet")
    labels_df = pd.read_parquet(root / "labels.parquet")
    ads_df = pd.read_parquet(root / "ads.parquet")

    column_checks = [
        ("orders.parquet", orders_df, ORDERS_COLUMNS),
        ("order_items.parquet", order_items_df, ORDER_ITEMS_COLUMNS),
        ("returns.parquet", returns_df, RETURNS_COLUMNS),
        ("labels.parquet", labels_df, LABELS_COLUMNS),
        ("ads.parquet", ads_df, ADS_COLUMNS),
    ]
    for file_name, frame, required in column_checks:
        missing = _missing_columns(list(frame.columns), required)
        if missing:
            raise DatasetValidationError(
                f"{file_name}: missing required columns {missing}. "
                f"Expected columns: {list(required)}"
            )

    _validate_enum_column(labels_df, "return_type", RETURN_TYPE_VALUES, "labels.parquet")
    _validate_enum_column(returns_df, "return_type", RETURN_TYPE_VALUES, "returns.parquet")
    _validate_enum_column(
        returns_df, "return_condition", RETURN_CONDITION_VALUES, "returns.parquet"
    )
    _validate_enum_column(returns_df, "status", RETURN_STATUS_VALUES, "returns.parquet")

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise DatasetValidationError(
            f"Missing manifest.json in {root}. Run assemble-backtest-dataset first."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_manifest_keys = {
        "dataset_version",
        "row_counts",
        "date_range",
        "split_boundaries",
    }
    missing_keys = sorted(required_manifest_keys - set(manifest.keys()))
    if missing_keys:
        raise DatasetValidationError(
            f"manifest.json missing keys: {missing_keys}. "
            f"Required: {sorted(required_manifest_keys)}"
        )

    return {
        "orders": len(orders_df),
        "order_items": len(order_items_df),
        "returns": len(returns_df),
        "labels": len(labels_df),
        "ads": len(ads_df),
        "manifest": manifest,
    }
