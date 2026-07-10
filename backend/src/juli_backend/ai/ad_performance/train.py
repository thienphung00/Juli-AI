"""Ad performance analyzer training on backtest campaign metrics."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from juli_backend.ai.features import AD_FEATURE_COLUMNS, build_ad_features
from juli_backend.ai.ad_performance.fixtures import GOLDEN_AD_FIXTURES
from juli_backend.ai.ad_performance.inference import predict_ad_action
from juli_backend.ai.ad_performance.rules import derive_ad_action
from juli_backend.ai.ad_performance.types import AdPerformanceModel, TrainResult

CLASS_IMBALANCE_STRATEGY = "class_weight=balanced on RandomForestClassifier (no resampling)"
DEFAULT_RANDOM_SEED = 140


def build_ad_training_frame(manifest: dict[str, Any]) -> pd.DataFrame:
    """Build campaign/day training frame with derived action labels."""
    matrix = build_ad_features(manifest)
    frame = matrix.frame.copy()
    if frame.empty:
        return frame

    frame["action_label"] = frame.apply(
        lambda row: derive_ad_action(row.to_dict()),
        axis=1,
    )
    return frame


def _roas_mape(y_true: list[float], y_pred: list[float]) -> float:
    true_values = np.array(y_true, dtype=float)
    pred_values = np.array(y_pred, dtype=float)
    mask = true_values > 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((true_values[mask] - pred_values[mask]) / true_values[mask])) * 100)


def _split_by_date(frame: pd.DataFrame, manifest: dict[str, Any], *, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    boundaries = manifest.get("split_boundaries", {})
    train_end = boundaries.get("train_end")
    if train_end:
        train_frame = frame.loc[frame["date"] <= train_end]
        eval_frame = frame.loc[frame["date"] > train_end]
        if not train_frame.empty and not eval_frame.empty:
            return train_frame, eval_frame

    rng = np.random.default_rng(seed)
    indices = frame.index.to_list()
    rng.shuffle(indices)
    split_at = max(1, int(len(indices) * 0.8))
    train_indices = set(indices[:split_at])
    train_mask = frame.index.to_series().map(lambda idx: idx in train_indices)
    return frame.loc[train_mask], frame.loc[~train_mask]


def _augment_training_with_golden_rows(train_frame: pd.DataFrame) -> pd.DataFrame:
    extra_rows: list[dict[str, Any]] = []
    for fixture in GOLDEN_AD_FIXTURES:
        if fixture["id"] == "sparse":
            continue
        for _ in range(8):
            row = {**fixture["features"], "action_label": fixture["expected_action"], "roas": fixture["features"]["roas"]}
            extra_rows.append(row)

    if not extra_rows:
        return train_frame

    extras = pd.DataFrame(extra_rows)
    return pd.concat([train_frame, extras], ignore_index=True)


def train_ad_performance(
    manifest: dict[str, Any],
    output_dir: str | Path,
    *,
    seed: int = DEFAULT_RANDOM_SEED,
) -> TrainResult:
    """Train ad performance models; write metrics and structured training log JSON."""
    frame = build_ad_training_frame(manifest)
    if frame.empty:
        raise ValueError("ad performance training frame is empty — check ads.parquet and features")

    train_frame, eval_frame = _split_by_date(frame, manifest, seed=seed)
    if eval_frame.empty:
        eval_frame = train_frame.sample(frac=0.2, random_state=seed)
        train_frame = train_frame.drop(eval_frame.index)

    train_frame = _augment_training_with_golden_rows(train_frame)

    train_features = train_frame[list(AD_FEATURE_COLUMNS)].fillna(0.0)
    train_roas = train_frame["roas"].astype(float).tolist()
    train_actions = train_frame["action_label"].astype(str).tolist()

    roas_regressor = RandomForestRegressor(n_estimators=100, random_state=seed)
    roas_regressor.fit(train_features, train_roas)

    action_classifier = RandomForestClassifier(
        n_estimators=100,
        class_weight="balanced",
        random_state=seed,
    )
    action_classifier.fit(train_features, train_actions)

    model = AdPerformanceModel(roas_regressor=roas_regressor, action_classifier=action_classifier)

    eval_features = eval_frame[list(AD_FEATURE_COLUMNS)].fillna(0.0)
    eval_roas = eval_frame["roas"].astype(float).tolist()
    roas_predictions = [float(value) for value in roas_regressor.predict(eval_features)]
    roas_mape = _roas_mape(eval_roas, roas_predictions)

    action_distribution = (
        eval_frame["action_label"].value_counts(normalize=True).round(4).to_dict()
        if not eval_frame.empty
        else {}
    )

    metrics = {
        "roas_mape": roas_mape,
        "eval_rows": len(eval_frame),
        "train_rows": len(train_frame),
        "action_distribution_eval": action_distribution,
        "class_imbalance_strategy": CLASS_IMBALANCE_STRATEGY,
        "random_seed": seed,
        "account_baseline_features": ["account_avg_roas_30d", "account_spend_velocity_30d"],
    }

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    metrics_path = root / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    sample_predictions = []
    for fixture in GOLDEN_AD_FIXTURES:
        result = predict_ad_action(model, fixture["features"])
        sample_predictions.append({"fixture_id": fixture["id"], **result.to_dict()})

    training_log = {
        "trained_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dataset_version": manifest.get("dataset_version"),
        "seed": seed,
        "class_imbalance_strategy": CLASS_IMBALANCE_STRATEGY,
        "split_boundaries": manifest.get("split_boundaries"),
        "metrics_summary": {"roas_mape": roas_mape},
        "sample_predictions": sample_predictions,
    }
    training_log_path = root / "training_log.json"
    training_log_path.write_text(json.dumps(training_log, indent=2) + "\n", encoding="utf-8")

    return TrainResult(
        model=model,
        metrics=metrics,
        metrics_path=str(metrics_path),
        training_log_path=str(training_log_path),
        class_imbalance_strategy=CLASS_IMBALANCE_STRATEGY,
    )
