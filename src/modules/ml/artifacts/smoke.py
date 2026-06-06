"""Smoke tests: load artifacts and run golden fixture inference."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.modules.ml.ad_performance.fixtures import GOLDEN_AD_FIXTURES
from src.modules.ml.ad_performance.inference import predict_ad_action
from src.modules.ml.anomaly.fixtures import GOLDEN_ANOMALY_FIXTURES
from src.modules.ml.anomaly.inference import predict_anomaly
from src.modules.ml.artifacts.exceptions import ArtifactLoadError
from src.modules.ml.artifacts.load import load_model
from src.modules.ml.artifacts.types import MODEL_SUITES, ModelSuite
from src.modules.ml.seller_stage.fixtures import STAGE_BOUNDARY_FIXTURES
from src.modules.ml.seller_stage.inference import predict_seller_stage


def _infer_seller_stage(model: Any) -> None:
    fixture = STAGE_BOUNDARY_FIXTURES[0]
    profile = fixture["profile"]
    features = {**profile, "gmv_30d_vnd": 10_000_000.0}
    result = predict_seller_stage(model, features)
    if not result.stage or not (0.0 <= result.confidence <= 1.0):
        raise ArtifactLoadError("seller_stage smoke inference returned invalid output")


def _infer_anomaly(model: Any) -> None:
    fixture = GOLDEN_ANOMALY_FIXTURES[0]
    result = predict_anomaly(model, fixture["features"])
    if not (0.0 <= result.confidence <= 1.0):
        raise ArtifactLoadError("anomaly smoke inference returned invalid confidence")


def _infer_ad_performance(model: Any) -> None:
    fixture = GOLDEN_AD_FIXTURES[0]
    result = predict_ad_action(model, fixture["features"])
    if result.action not in {"scale", "cut", "hold"}:
        raise ArtifactLoadError("ad_performance smoke inference returned invalid action")
    if not (0.0 <= result.confidence <= 1.0):
        raise ArtifactLoadError("ad_performance smoke inference returned invalid confidence")


_INFERENCE_HANDLERS = {
    "seller_stage": _infer_seller_stage,
    "anomaly": _infer_anomaly,
    "ad_performance": _infer_ad_performance,
}


def run_smoke_test(
    suite: ModelSuite,
    version: str,
    *,
    models_root: str | Path = "models",
) -> None:
    """Load artifact and run one golden fixture inference; raise on failure."""
    loaded = load_model(suite, version, models_root=models_root)
    handler = _INFERENCE_HANDLERS.get(suite)
    if handler is None:
        raise ArtifactLoadError(f"no smoke handler for suite: {suite}")
    try:
        handler(loaded.model)
    except ArtifactLoadError:
        raise
    except Exception as exc:  # noqa: BLE001 — smoke boundary surfaces inference failures
        raise ArtifactLoadError(f"{suite} smoke test failed during inference: {exc}") from exc


def run_all_smoke_tests(
    version: str,
    *,
    models_root: str | Path = "models",
) -> None:
    """Run smoke tests for all three model suites at a version."""
    for suite in MODEL_SUITES:
        run_smoke_test(suite, version, models_root=models_root)
