"""Integration tests for ad performance analyzer — Issue #140."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.ml.dataset import assemble_backtest_dataset
from src.modules.ml.features.schema import AD_FEATURE_COLUMNS


@pytest.fixture
def trained_ad_model(tmp_path: Path):
    from src.modules.ml.ad_performance import train_ad_performance

    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(
        dataset_dir,
        seed=140,
        n_shops=10,
        orders_per_shop=50,
        return_rate=0.12,
        ads_days=25,
    )
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    output_dir = tmp_path / "training"
    result = train_ad_performance(manifest, output_dir, seed=140)
    return result.model, manifest


def test_golden_scale_candidate_returns_scale_with_high_confidence(trained_ad_model):
    """Golden scale candidate campaign → scale action with confidence above hold threshold."""
    from src.modules.ml.ad_performance import GOLDEN_AD_FIXTURES, HOLD_CONFIDENCE_THRESHOLD, predict_ad_action

    model, _manifest = trained_ad_model
    fixture = next(item for item in GOLDEN_AD_FIXTURES if item["id"] == "scale")
    result = predict_ad_action(model, fixture["features"])

    assert result.action == "scale"
    assert result.confidence > HOLD_CONFIDENCE_THRESHOLD
    assert result.predicted_roas > 0.0


def test_golden_cut_candidate_returns_cut(trained_ad_model):
    """Golden cut candidate campaign → cut action."""
    from src.modules.ml.ad_performance import GOLDEN_AD_FIXTURES, predict_ad_action

    model, _manifest = trained_ad_model
    fixture = next(item for item in GOLDEN_AD_FIXTURES if item["id"] == "cut")
    result = predict_ad_action(model, fixture["features"])

    assert result.action == "cut"
    assert 0.0 <= result.confidence <= 1.0


def test_sparse_history_campaign_returns_hold_low_confidence(trained_ad_model):
    """Sparse-history campaign → hold with low confidence (does not raise)."""
    from src.modules.ml.ad_performance import GOLDEN_AD_FIXTURES, HOLD_CONFIDENCE_THRESHOLD, predict_ad_action

    model, _manifest = trained_ad_model
    fixture = next(item for item in GOLDEN_AD_FIXTURES if item["id"] == "sparse")
    result = predict_ad_action(model, fixture["features"])

    assert result.action == "hold"
    assert result.confidence < HOLD_CONFIDENCE_THRESHOLD


def test_train_writes_roas_mape_metrics_json(tmp_path: Path):
    """CLI train path writes metrics JSON including ROAS MAPE on held-out window."""
    from src.modules.ml.ad_performance import CLASS_IMBALANCE_STRATEGY, train_ad_performance

    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(dataset_dir, seed=140, n_shops=8, orders_per_shop=40, ads_days=20)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    output_dir = tmp_path / "out"
    result = train_ad_performance(manifest, output_dir, seed=140)

    metrics = json.loads(Path(result.metrics_path).read_text(encoding="utf-8"))
    training_log = json.loads(Path(result.training_log_path).read_text(encoding="utf-8"))

    assert "roas_mape" in metrics
    assert isinstance(metrics["roas_mape"], float)
    assert metrics["roas_mape"] >= 0.0
    assert metrics["class_imbalance_strategy"] == CLASS_IMBALANCE_STRATEGY
    assert "account_avg_roas_30d" in metrics["account_baseline_features"]
    assert "account_spend_velocity_30d" in metrics["account_baseline_features"]
    assert training_log["metrics_summary"]["roas_mape"] == metrics["roas_mape"]


def test_training_frame_includes_account_baseline_features(tmp_path: Path):
    """Account-level baseline features included in ad training frame."""
    from src.modules.ml.ad_performance.train import build_ad_training_frame

    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(dataset_dir, seed=140, n_shops=4, orders_per_shop=30, ads_days=15)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    frame = build_ad_training_frame(manifest)

    for column in ("account_avg_roas_30d", "account_spend_velocity_30d"):
        assert column in frame.columns
        assert column in AD_FEATURE_COLUMNS


def test_inference_output_schema_documented():
    """Inference output schema includes action, confidence, predicted_roas."""
    from src.modules.ml.ad_performance.types import InferenceResult

    result = InferenceResult(action="scale", confidence=0.82, predicted_roas=4.5)
    payload = result.to_dict()
    assert set(payload.keys()) == {"action", "confidence", "predicted_roas"}


def test_ad_performance_trainer_has_no_tiktok_api_calls():
    """No TikTok API calls in ad performance trainer module."""
    import src.modules.ml.ad_performance.train as train_module

    source = Path(train_module.__file__).read_text(encoding="utf-8")
    forbidden = ("TikTokClient", "tiktokglobalshop", "open-api.tiktok")
    for token in forbidden:
        assert token not in source
