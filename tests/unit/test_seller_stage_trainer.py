"""Integration tests for seller stage classifier — Issue #138."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.ml.dataset import assemble_backtest_dataset
from src.modules.ml.seller_stage import (
    AD_SPEND_GROWTH_MIN_VND,
    CLASS_IMBALANCE_STRATEGY,
    ORDER_COUNT_GROWTH_MIN,
    ORDER_COUNT_NEW_MAX,
    RETURN_RATE_LEAKAGE_MIN,
    SHOP_AGE_NEW_MAX_DAYS,
    STAGE_BOUNDARY_FIXTURES,
    classify_seller_stage,
    compare_to_rules_baseline,
    predict_seller_stage,
    train_seller_stage,
)


@pytest.fixture
def trained_model(tmp_path: Path) -> tuple[object, dict]:
    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(
        dataset_dir,
        seed=138,
        n_shops=8,
        orders_per_shop=40,
        return_rate=0.12,
        ads_days=20,
    )
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    output_dir = tmp_path / "training"
    result = train_seller_stage(manifest, output_dir, seed=138)
    return result.model, manifest


def test_threshold_constants_match_phase1():
    """Rules baseline mirrors Phase 1 threshold constants."""
    assert RETURN_RATE_LEAKAGE_MIN == 0.1
    assert ORDER_COUNT_NEW_MAX == 15
    assert SHOP_AGE_NEW_MAX_DAYS == 45
    assert ORDER_COUNT_GROWTH_MIN == 50
    assert AD_SPEND_GROWTH_MIN_VND == 5_000_000


@pytest.mark.parametrize("fixture", STAGE_BOUNDARY_FIXTURES, ids=lambda f: f["id"])
def test_rules_baseline_golden_boundary_fixtures(fixture):
    """Golden boundary profiles → expected stage from rules baseline."""
    assert classify_seller_stage(fixture["profile"]) == fixture["expected_stage"]


def test_ml_inference_on_golden_profiles_valid_class_and_confidence(trained_model):
    """ML inference on golden profiles returns valid class + confidence in [0, 1]."""
    model, _manifest = trained_model
    valid_stages = {"new", "leakage", "growth"}

    for fixture in STAGE_BOUNDARY_FIXTURES:
        profile = fixture["profile"]
        features = {
            **profile,
            "gmv_30d_vnd": 10_000_000.0,
        }
        result = predict_seller_stage(model, features)
        assert result.stage in valid_stages
        assert 0.0 <= result.confidence <= 1.0


def test_compare_to_rules_baseline_includes_agreement_rate(trained_model):
    """compare_to_rules_baseline report includes agreement_rate field."""
    model, _manifest = trained_model
    profiles = [fixture["profile"] for fixture in STAGE_BOUNDARY_FIXTURES]
    report = compare_to_rules_baseline(model, profiles)
    payload = report.to_dict()

    assert "agreement_rate" in payload
    assert 0.0 <= payload["agreement_rate"] <= 1.0
    assert payload["total_profiles"] == len(profiles)
    assert payload["agreements"] + len(payload["disagreements"]) == len(profiles)


def test_class_imbalance_strategy_documented(tmp_path: Path):
    """Class imbalance strategy documented in metrics and training log JSON."""
    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(dataset_dir, seed=138, n_shops=4, orders_per_shop=25)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    result = train_seller_stage(manifest, tmp_path / "out", seed=138)

    assert "balanced" in result.class_imbalance_strategy.lower()
    assert result.metrics["class_imbalance_strategy"] == CLASS_IMBALANCE_STRATEGY


def test_train_writes_metrics_json(tmp_path: Path):
    """CLI train path writes metrics JSON with precision, recall macro, confusion matrix."""
    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(dataset_dir, seed=138, n_shops=6, orders_per_shop=30)
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    output_dir = tmp_path / "out"

    result = train_seller_stage(manifest, output_dir, seed=138)
    metrics = json.loads(Path(result.metrics_path).read_text(encoding="utf-8"))
    training_log = json.loads(Path(result.training_log_path).read_text(encoding="utf-8"))

    assert "precision" in metrics
    assert "recall_macro" in metrics
    assert "confusion_matrix" in metrics
    assert metrics["class_imbalance_strategy"] == CLASS_IMBALANCE_STRATEGY
    assert training_log["class_imbalance_strategy"] == CLASS_IMBALANCE_STRATEGY
    assert "sample_predictions" in training_log


def test_seller_stage_has_no_tiktok_api_calls():
    """No TikTok API calls in seller stage trainer module."""
    import src.modules.ml.seller_stage.train as train_module

    source = Path(train_module.__file__).read_text(encoding="utf-8")
    forbidden = ("TikTokClient", "tiktokglobalshop", "open-api.tiktok")
    for token in forbidden:
        assert token not in source


def test_seller_stage_has_no_ui_changes():
    """Seller stage trainer does not import web UI modules."""
    import ast

    import src.modules.ml.seller_stage as seller_stage_pkg

    package_dir = Path(seller_stage_pkg.__file__).parent
    for path in package_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("web"):
                raise AssertionError(f"unexpected web import in {path.name}: {node.module}")
