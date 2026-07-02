"""Integration tests for model artifact publisher — Issue #141."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.ai.ad_performance import train_ad_performance
from backend.ai.anomaly import train_anomaly
from backend.ai.artifacts import (
    ArtifactLoadError,
    evaluate_promotion_status,
    feature_schema_hash,
    load_model,
    publish_model,
    run_all_smoke_tests,
    run_smoke_test,
)
from backend.ai.dataset import assemble_backtest_dataset
from backend.ai.seller_stage import train_seller_stage


@pytest.fixture
def trained_seller_stage(tmp_path: Path) -> tuple[object, dict, str]:
    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(
        dataset_dir,
        seed=141,
        n_shops=8,
        orders_per_shop=40,
        return_rate=0.12,
        ads_days=20,
    )
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    output_dir = tmp_path / "training"
    result = train_seller_stage(manifest, output_dir, seed=141)
    return result.model, result.metrics, result.metrics_path


@pytest.fixture
def models_root(tmp_path: Path) -> Path:
    return tmp_path / "models"


def test_publish_creates_expected_directory_layout(trained_seller_stage, models_root):
    """Directory layout matches system-design: models/{suite}/{version}/model.joblib + metadata.json."""
    model, metrics, metrics_path = trained_seller_stage
    bundle = publish_model(
        "seller_stage",
        model=model,
        metrics=metrics,
        version="v1",
        models_root=models_root,
        metrics_path=metrics_path,
    )

    assert bundle.model_path == models_root / "seller_stage" / "v1" / "model.joblib"
    assert bundle.metadata_path == models_root / "seller_stage" / "v1" / "metadata.json"
    assert bundle.model_path.is_file()
    assert bundle.metadata_path.is_file()


def test_metadata_includes_required_fields(trained_seller_stage, models_root):
    """metadata.json includes train_date, row_count, feature_schema_hash, metrics, promotion_status."""
    model, metrics, metrics_path = trained_seller_stage
    bundle = publish_model(
        "seller_stage",
        model=model,
        metrics=metrics,
        version="v1",
        models_root=models_root,
        train_date="2026-06-06T08:00:00Z",
        metrics_path=metrics_path,
    )
    metadata = json.loads(bundle.metadata_path.read_text(encoding="utf-8"))

    assert metadata["train_date"] == "2026-06-06T08:00:00Z"
    assert metadata["row_count"] == metrics["train_rows"] + metrics["eval_rows"]
    assert metadata["feature_schema_hash"] == feature_schema_hash("seller_stage")
    assert metadata["metrics"] == metrics
    assert metadata["promotion_status"] in {"promoted", "experimental"}


def test_load_model_roundtrip_and_smoke_inference(trained_seller_stage, models_root):
    """publish_model / load_model roundtrip; smoke test runs golden fixture inference."""
    model, metrics, metrics_path = trained_seller_stage
    publish_model(
        "seller_stage",
        model=model,
        metrics=metrics,
        version="v1",
        models_root=models_root,
        metrics_path=metrics_path,
    )

    loaded = load_model("seller_stage", "v1", models_root=models_root)
    assert loaded.suite == "seller_stage"
    assert loaded.version == "v1"
    assert loaded.metadata["promotion_status"] in {"promoted", "experimental"}

    run_smoke_test("seller_stage", "v1", models_root=models_root)


def test_corrupt_model_file_raises_clear_error(trained_seller_stage, models_root):
    """Corrupt model file fails load/smoke with clear error."""
    model, metrics, metrics_path = trained_seller_stage
    publish_model(
        "seller_stage",
        model=model,
        metrics=metrics,
        version="v1",
        models_root=models_root,
        metrics_path=metrics_path,
    )

    model_path = models_root / "seller_stage" / "v1" / "model.joblib"
    model_path.write_bytes(b"not-a-valid-joblib-payload")

    with pytest.raises(ArtifactLoadError, match="failed to load model artifact"):
        load_model("seller_stage", "v1", models_root=models_root)

    with pytest.raises(ArtifactLoadError, match="failed to load model artifact"):
        run_smoke_test("seller_stage", "v1", models_root=models_root)


def test_sub_threshold_metrics_marked_experimental():
    """Sub-threshold run serializes as experimental only (not promoted)."""
    sub_threshold = {
        "precision": 0.1,
        "recall_macro": 0.1,
        "train_rows": 10,
        "eval_rows": 2,
    }
    assert evaluate_promotion_status("seller_stage", sub_threshold) == "experimental"

    anomaly_sub = {
        "per_class": {
            "item_swap": {"precision": 0.1, "recall": 0.1},
            "empty_return": {"precision": 0.9, "recall": 0.9},
        },
        "train_rows": 10,
        "eval_rows": 2,
    }
    assert evaluate_promotion_status("anomaly", anomaly_sub) == "experimental"

    ad_sub = {"roas_mape": 99.0, "train_rows": 10, "eval_rows": 2}
    assert evaluate_promotion_status("ad_performance", ad_sub) == "experimental"


def test_meeting_threshold_metrics_marked_promoted():
    """Metrics meeting thresholds serialize as promoted."""
    promoted = {"precision": 0.9, "recall_macro": 0.85, "train_rows": 10, "eval_rows": 2}
    assert evaluate_promotion_status("seller_stage", promoted) == "promoted"

    anomaly_promoted = {
        "per_class": {
            "item_swap": {"precision": 0.8, "recall": 0.7},
            "empty_return": {"precision": 0.75, "recall": 0.6},
        },
        "train_rows": 10,
        "eval_rows": 2,
    }
    assert evaluate_promotion_status("anomaly", anomaly_promoted) == "promoted"

    ad_promoted = {"roas_mape": 12.5, "train_rows": 10, "eval_rows": 2}
    assert evaluate_promotion_status("ad_performance", ad_promoted) == "promoted"


def test_sub_threshold_publish_writes_experimental_status(trained_seller_stage, models_root):
    """Published artifact with sub-threshold metrics has promotion_status experimental."""
    model, _metrics, metrics_path = trained_seller_stage
    sub_threshold = {
        "precision": 0.1,
        "recall_macro": 0.1,
        "train_rows": 4,
        "eval_rows": 1,
    }
    bundle = publish_model(
        "seller_stage",
        model=model,
        metrics=sub_threshold,
        version="experimental-run",
        models_root=models_root,
        metrics_path=metrics_path,
    )
    assert bundle.metadata["promotion_status"] == "experimental"
    assert bundle.metadata["promotion_status"] != "promoted"


def test_metrics_json_copied_to_artifact_directory(trained_seller_stage, models_root):
    """Metrics JSON written alongside model file during publish."""
    model, metrics, metrics_path = trained_seller_stage
    bundle = publish_model(
        "seller_stage",
        model=model,
        metrics=metrics,
        version="v1",
        models_root=models_root,
        metrics_path=metrics_path,
    )

    assert bundle.metrics_path is not None
    assert bundle.metrics_path.is_file()
    copied = json.loads(bundle.metrics_path.read_text(encoding="utf-8"))
    assert copied == metrics


def test_all_three_suites_publish_load_and_smoke(tmp_path, models_root):
    """CI smoke path: train, publish, load, and infer for all three suites."""
    dataset_dir = tmp_path / "backtest"
    assemble_backtest_dataset(
        dataset_dir,
        seed=141,
        n_shops=8,
        orders_per_shop=40,
        return_rate=0.12,
        ads_days=20,
    )
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    version = "smoke-v1"

    seller = train_seller_stage(manifest, tmp_path / "train-seller", seed=141)
    publish_model(
        "seller_stage",
        model=seller.model,
        metrics=seller.metrics,
        version=version,
        models_root=models_root,
        metrics_path=seller.metrics_path,
    )

    anomaly = train_anomaly(manifest, tmp_path / "train-anomaly", seed=141)
    publish_model(
        "anomaly",
        model=anomaly.model,
        metrics=anomaly.metrics,
        version=version,
        models_root=models_root,
        metrics_path=anomaly.metrics_path,
    )

    ad = train_ad_performance(manifest, tmp_path / "train-ad", seed=141)
    publish_model(
        "ad_performance",
        model=ad.model,
        metrics=ad.metrics,
        version=version,
        models_root=models_root,
        metrics_path=ad.metrics_path,
    )

    run_all_smoke_tests(version, models_root=models_root)

    for suite in ("seller_stage", "anomaly", "ad_performance"):
        loaded = load_model(suite, version, models_root=models_root)  # type: ignore[arg-type]
        assert loaded.model is not None
        assert "promotion_status" in loaded.metadata


def test_publish_model_has_no_postgres_persistence():
    """Artifact publisher does not import Postgres or SQLAlchemy session layers."""
    import backend.ai.artifacts.publish as publish_module

    source = Path(publish_module.__file__).read_text(encoding="utf-8")
    forbidden = ("sqlalchemy", "postgres", "supabase", "get_session")
    for token in forbidden:
        assert token not in source.lower()
