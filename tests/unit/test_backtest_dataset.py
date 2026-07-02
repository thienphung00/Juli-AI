"""Integration tests for backtest dataset assembly — Issue #136."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backend.ai.dataset import (
    ADS_COLUMNS,
    LABELS_COLUMNS,
    ORDER_ITEMS_COLUMNS,
    ORDERS_COLUMNS,
    RETURNS_COLUMNS,
    DatasetValidationError,
    assemble_backtest_dataset,
    validate_backtest_dataset,
)
from backend.ai.dataset.schema import REQUIRED_PARQUET_FILES


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "backtest"


def test_ml_module_public_interface_and_pinned_dependencies():
    """ML module directory exists with MODULE.md; dependencies pinned in requirements."""
    module_md = Path("backend/ai/dataset/MODULE.md")
    assert module_md.exists()
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    for package in ("scikit-learn", "xgboost", "pandas", "pyarrow"):
        assert package in requirements
    assert callable(assemble_backtest_dataset)
    assert callable(validate_backtest_dataset)


def test_assemble_tiny_fixture_with_fixed_seed_writes_manifest_and_parquet(output_dir: Path):
    """Integration test: assemble tiny fixture dataset with fixed seed → manifest + all parquet files present."""
    result = assemble_backtest_dataset(
        output_dir,
        seed=136,
        n_shops=1,
        orders_per_shop=8,
        return_rate=0.5,
        ads_days=3,
    )

    manifest = result["manifest"]
    assert manifest["dataset_version"]
    assert manifest["row_counts"]["orders"] == 8
    assert manifest["date_range"]["start"]
    assert manifest["date_range"]["end"]
    assert manifest["split_boundaries"]["train_end"]
    assert manifest["split_boundaries"]["eval_start"]

    for file_name in REQUIRED_PARQUET_FILES:
        assert (output_dir / file_name).exists()

    saved_manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert saved_manifest["seed"] == 136
    assert saved_manifest["row_counts"] == manifest["row_counts"]


def test_parquet_columns_match_return_schema_contract(output_dir: Path):
    """Parquet files match system-design return schema contract columns."""
    assemble_backtest_dataset(
        output_dir,
        seed=7,
        n_shops=1,
        orders_per_shop=5,
        return_rate=0.4,
        ads_days=2,
    )

    orders_df = pd.read_parquet(output_dir / "orders.parquet")
    order_items_df = pd.read_parquet(output_dir / "order_items.parquet")
    returns_df = pd.read_parquet(output_dir / "returns.parquet")
    labels_df = pd.read_parquet(output_dir / "labels.parquet")
    ads_df = pd.read_parquet(output_dir / "ads.parquet")

    assert list(orders_df.columns) == list(ORDERS_COLUMNS)
    assert list(order_items_df.columns) == list(ORDER_ITEMS_COLUMNS)
    assert list(returns_df.columns) == list(RETURNS_COLUMNS)
    assert list(labels_df.columns) == list(LABELS_COLUMNS)
    assert list(ads_df.columns) == list(ADS_COLUMNS)


def test_labels_parquet_contains_buyer_behavior_labels_only(output_dir: Path):
    """labels.parquet contains buyer-behavior labels only: return_id, ground_truth_anomaly, return_type."""
    assemble_backtest_dataset(
        output_dir,
        seed=99,
        n_shops=1,
        orders_per_shop=12,
        return_rate=0.6,
        ads_days=2,
    )
    labels_df = pd.read_parquet(output_dir / "labels.parquet")
    assert set(labels_df.columns) == {"return_id", "ground_truth_anomaly", "return_type"}
    assert set(labels_df["return_type"].unique()).issubset(
        {"item_swap", "empty_return", "other"}
    )


def test_synthetic_generator_produces_anomaly_labels_and_masked_buyer_ids(output_dir: Path):
    """Synthetic generator produces labeled item_swap and empty_return rows; masked buyer_id only — no PII."""
    assemble_backtest_dataset(
        output_dir,
        seed=2024,
        n_shops=2,
        orders_per_shop=80,
        return_rate=0.25,
        ads_days=5,
    )

    labels_df = pd.read_parquet(output_dir / "labels.parquet")
    return_types = set(labels_df["return_type"].unique())
    assert "item_swap" in return_types
    assert "empty_return" in return_types

    anomaly_rate = labels_df["ground_truth_anomaly"].mean()
    assert 0.0 < anomaly_rate < 0.25

    orders_df = pd.read_parquet(output_dir / "orders.parquet")
    for buyer_id in orders_df["buyer_id"]:
        assert buyer_id.startswith("buyer_")
        assert "@" not in buyer_id


def test_validate_raises_on_missing_return_type_with_actionable_message(output_dir: Path):
    """Integration test: corrupt parquet (missing return_type) raises validation error with actionable message."""
    assemble_backtest_dataset(
        output_dir,
        seed=1,
        n_shops=1,
        orders_per_shop=3,
        return_rate=0.5,
        ads_days=1,
    )

    labels_path = output_dir / "labels.parquet"
    labels_df = pd.read_parquet(labels_path)
    corrupted = labels_df.drop(columns=["return_type"])
    corrupted.to_parquet(labels_path, index=False)

    with pytest.raises(DatasetValidationError) as exc_info:
        validate_backtest_dataset(output_dir)

    message = str(exc_info.value)
    assert "return_type" in message
    assert "labels.parquet" in message
    assert "missing required columns" in message


def test_schema_validation_fails_fast_on_missing_columns(output_dir: Path):
    """Schema manifest validation fails fast on missing columns or invalid enums."""
    assemble_backtest_dataset(
        output_dir,
        seed=3,
        n_shops=1,
        orders_per_shop=2,
        return_rate=0.5,
        ads_days=1,
    )

    returns_path = output_dir / "returns.parquet"
    returns_df = pd.read_parquet(returns_path)
    returns_df.loc[0, "return_type"] = "affiliate_fraud"
    returns_df.to_parquet(returns_path, index=False)

    with pytest.raises(DatasetValidationError) as exc_info:
        validate_backtest_dataset(output_dir)

    assert "invalid values" in str(exc_info.value)
    assert "return_type" in str(exc_info.value)


def test_assembler_has_no_tiktok_api_calls():
    """No TikTok API calls in dataset assembly module."""
    import backend.ai.dataset.assembler as assembler_module
    import backend.ai.dataset.synthetic as synthetic_module

    assembler_source = Path(assembler_module.__file__).read_text(encoding="utf-8")
    synthetic_source = Path(synthetic_module.__file__).read_text(encoding="utf-8")
    forbidden = ("TikTokClient", "tiktokglobalshop", "open-api.tiktok")
    for token in forbidden:
        assert token not in assembler_source
        assert token not in synthetic_source


def test_assembler_has_no_postgres_writes():
    """No Postgres writes in dataset assembly module."""
    import backend.ai.dataset.assembler as assembler_module

    source = Path(assembler_module.__file__).read_text(encoding="utf-8")
    forbidden = ("get_session", "asyncpg", "sqlalchemy", "alembic")
    for token in forbidden:
        assert token not in source
