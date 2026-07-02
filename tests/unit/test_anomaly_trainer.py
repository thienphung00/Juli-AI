"""Integration tests for buyer-behavior anomaly detector — Issue #139."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.ai.dataset import assemble_backtest_dataset
from backend.ai.features.schema import (
    FORBIDDEN_ANOMALY_INPUT_COLUMNS,
    FORBIDDEN_ANOMALY_INPUT_PREFIXES,
)


@pytest.fixture
def trained_anomaly_model(tmp_path: Path):
    from backend.ai.anomaly import train_anomaly

    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(
        dataset_dir,
        seed=139,
        n_shops=10,
        orders_per_shop=50,
        return_rate=0.15,
        ads_days=20,
    )
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    output_dir = tmp_path / "training"
    result = train_anomaly(manifest, output_dir, seed=139)
    return result.model, manifest


def test_golden_item_swap_scores_as_anomaly(trained_anomaly_model):
    """Golden item_swap row scores as anomaly with class item_swap."""
    from backend.ai.anomaly import GOLDEN_ANOMALY_FIXTURES, predict_anomaly

    model, _manifest = trained_anomaly_model
    fixture = next(item for item in GOLDEN_ANOMALY_FIXTURES if item["id"] == "item_swap")
    result = predict_anomaly(model, fixture["features"])

    assert result.is_anomaly is True
    assert result.anomaly_class == "item_swap"
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.feature_summary, dict)
    assert result.feature_summary


def test_golden_empty_return_scores_as_anomaly(trained_anomaly_model):
    """Golden empty_return row scores as anomaly with class empty_return."""
    from backend.ai.anomaly import GOLDEN_ANOMALY_FIXTURES, predict_anomaly

    model, _manifest = trained_anomaly_model
    fixture = next(item for item in GOLDEN_ANOMALY_FIXTURES if item["id"] == "empty_return")
    result = predict_anomaly(model, fixture["features"])

    assert result.is_anomaly is True
    assert result.anomaly_class == "empty_return"
    assert 0.0 <= result.confidence <= 1.0
    assert result.feature_summary


def test_golden_other_scores_non_anomaly(trained_anomaly_model):
    """Golden other (legitimate return) scores below threshold or as non-anomaly."""
    from backend.ai.anomaly import GOLDEN_ANOMALY_FIXTURES, predict_anomaly

    model, _manifest = trained_anomaly_model
    fixture = next(item for item in GOLDEN_ANOMALY_FIXTURES if item["id"] == "other")
    result = predict_anomaly(model, fixture["features"])

    assert result.is_anomaly is False
    assert result.anomaly_class is None


def test_training_frame_has_no_affiliate_creator_columns(tmp_path: Path):
    """Feature matrix for anomaly training contains no affiliate/creator column names."""
    from backend.ai.anomaly.train import build_anomaly_training_frame

    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(dataset_dir, seed=139, n_shops=4, orders_per_shop=30, return_rate=0.12)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    frame, _features, _labels = build_anomaly_training_frame(manifest)

    for column in frame.columns:
        assert column not in FORBIDDEN_ANOMALY_INPUT_COLUMNS
        assert not any(column.startswith(prefix) for prefix in FORBIDDEN_ANOMALY_INPUT_PREFIXES)


def test_train_writes_per_class_metrics_json(tmp_path: Path):
    """Train writes metrics JSON with per-class precision/recall for item_swap and empty_return."""
    from backend.ai.anomaly import CLASS_IMBALANCE_STRATEGY, train_anomaly

    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(dataset_dir, seed=139, n_shops=8, orders_per_shop=40, return_rate=0.14)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    output_dir = tmp_path / "out"
    result = train_anomaly(manifest, output_dir, seed=139)

    metrics = json.loads(Path(result.metrics_path).read_text(encoding="utf-8"))
    training_log = json.loads(Path(result.training_log_path).read_text(encoding="utf-8"))

    assert "per_class" in metrics
    assert "item_swap" in metrics["per_class"]
    assert "empty_return" in metrics["per_class"]
    assert "precision" in metrics["per_class"]["item_swap"]
    assert "recall" in metrics["per_class"]["item_swap"]
    assert "precision" in metrics["per_class"]["empty_return"]
    assert "recall" in metrics["per_class"]["empty_return"]
    assert metrics["class_imbalance_strategy"] == CLASS_IMBALANCE_STRATEGY
    assert training_log["class_imbalance_strategy"] == CLASS_IMBALANCE_STRATEGY


def test_inference_output_schema_documented():
    """Inference output schema includes anomaly_class, confidence, feature_summary."""
    from backend.ai.anomaly.types import InferenceResult

    result = InferenceResult(
        anomaly_class="item_swap",
        confidence=0.91,
        feature_summary={"buyer_item_swap_count_30d": 3.0},
        is_anomaly=True,
    )
    payload = result.to_dict()
    assert set(payload.keys()) == {"anomaly_class", "confidence", "feature_summary", "is_anomaly"}


def test_anomaly_trainer_has_no_tiktok_api_calls():
    """No TikTok API calls in anomaly trainer module."""
    import backend.ai.anomaly.train as train_module

    source = Path(train_module.__file__).read_text(encoding="utf-8")
    forbidden = ("TikTokClient", "tiktokglobalshop", "open-api.tiktok")
    for token in forbidden:
        assert token not in source
