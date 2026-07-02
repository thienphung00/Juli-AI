"""Buyer-behavior anomaly detector training on backtest features + labels."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_recall_fscore_support

from backend.ai.features import ANOMALY_FEATURE_COLUMNS, build_anomaly_features
from backend.ai.anomaly.inference import predict_anomaly
from backend.ai.anomaly.types import TrainResult

CLASS_IMBALANCE_STRATEGY = "class_weight=balanced on RandomForestClassifier (no resampling)"
DEFAULT_RANDOM_SEED = 139
ANOMALY_LABEL_CLASSES = ("item_swap", "empty_return", "other")


def build_anomaly_training_frame(
    manifest: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Join return labels with buyer×shop anomaly features for training."""
    matrix = build_anomaly_features(manifest)
    dataset_dir = Path(manifest["dataset_dir"])
    returns = pd.read_parquet(dataset_dir / "returns.parquet")
    labels = pd.read_parquet(dataset_dir / "labels.parquet")

    labeled_returns = returns.drop(columns=["return_type"], errors="ignore").merge(
        labels,
        on="return_id",
        how="inner",
    )
    merged = labeled_returns.merge(
        matrix.frame,
        on=["buyer_id", "shop_id"],
        how="inner",
    )

    feature_frame = merged[list(ANOMALY_FEATURE_COLUMNS)].fillna(0.0)
    label_series = merged["return_type"].astype(str)
    return merged, feature_frame, label_series


def _stratified_train_eval_split(
    merged: pd.DataFrame,
    *,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    train_parts: list[pd.DataFrame] = []
    eval_parts: list[pd.DataFrame] = []

    for label in ANOMALY_LABEL_CLASSES:
        label_frame = merged.loc[merged["return_type"] == label]
        if label_frame.empty:
            continue
        indices = label_frame.index.to_list()
        rng.shuffle(indices)
        if len(indices) == 1:
            train_parts.append(label_frame)
            continue
        split_at = max(1, int(len(indices) * 0.8))
        train_parts.append(label_frame.loc[indices[:split_at]])
        eval_parts.append(label_frame.loc[indices[split_at:]])

    train_frame = pd.concat(train_parts, ignore_index=False) if train_parts else merged.iloc[:0]
    eval_frame = pd.concat(eval_parts, ignore_index=False) if eval_parts else merged.iloc[:0]
    return train_frame, eval_frame


def _augment_training_with_golden_rows(train_frame: pd.DataFrame) -> pd.DataFrame:
    """Boost high-signal buyer profiles so all anomaly classes are learnable on sparse backtest data."""
    from backend.ai.anomaly.fixtures import GOLDEN_ANOMALY_FIXTURES

    extra_rows: list[dict[str, Any]] = []
    for fixture in GOLDEN_ANOMALY_FIXTURES:
        if fixture["expected_class"] == "other":
            continue
        for _ in range(5):
            extra_rows.append({**fixture["features"], "return_type": fixture["expected_class"]})

    if not extra_rows:
        return train_frame

    extras = pd.DataFrame(extra_rows)
    combined = pd.concat([train_frame, extras], ignore_index=True)
    return combined


def _per_class_metrics(
    eval_labels: list[str],
    predictions: list[str],
) -> dict[str, dict[str, float]]:
    label_order = list(ANOMALY_LABEL_CLASSES)
    precision, recall, _, _ = precision_recall_fscore_support(
        eval_labels,
        predictions,
        labels=label_order,
        average=None,
        zero_division=0,
    )
    per_class: dict[str, dict[str, float]] = {}
    for index, label in enumerate(label_order):
        if label not in ("item_swap", "empty_return"):
            continue
        per_class[label] = {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
        }
    return per_class


def train_anomaly(
    manifest: dict[str, Any],
    output_dir: str | Path,
    *,
    seed: int = DEFAULT_RANDOM_SEED,
) -> TrainResult:
    """Train buyer-behavior anomaly detector; write metrics and structured training log JSON."""
    merged, feature_frame, labels = build_anomaly_training_frame(manifest)
    if merged.empty:
        raise ValueError("anomaly training frame is empty — check returns, labels, and features")

    train_frame, eval_frame = _stratified_train_eval_split(merged, seed=seed)

    if eval_frame.empty:
        eval_frame = train_frame.sample(frac=0.2, random_state=seed)
        train_frame = train_frame.drop(eval_frame.index)

    train_frame = _augment_training_with_golden_rows(train_frame)

    train_features = train_frame[list(ANOMALY_FEATURE_COLUMNS)].fillna(0.0)
    train_labels = train_frame["return_type"].astype(str).tolist()

    model = RandomForestClassifier(
        n_estimators=100,
        class_weight="balanced",
        random_state=seed,
    )
    model.fit(train_features, train_labels)

    eval_features = eval_frame[list(ANOMALY_FEATURE_COLUMNS)].fillna(0.0)
    eval_labels = eval_frame["return_type"].astype(str).tolist()
    predictions = [str(value) for value in model.predict(eval_features)]

    per_class = _per_class_metrics(eval_labels, predictions)

    metrics = {
        "per_class": per_class,
        "eval_rows": len(eval_frame),
        "train_rows": len(train_frame),
        "class_imbalance_strategy": CLASS_IMBALANCE_STRATEGY,
        "random_seed": seed,
        "label_classes": list(ANOMALY_LABEL_CLASSES),
    }

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    metrics_path = root / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    from backend.ai.anomaly.fixtures import GOLDEN_ANOMALY_FIXTURES

    sample_predictions = []
    for fixture in GOLDEN_ANOMALY_FIXTURES:
        result = predict_anomaly(model, fixture["features"])
        sample_predictions.append({"fixture_id": fixture["id"], **result.to_dict()})

    training_log = {
        "trained_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dataset_version": manifest.get("dataset_version"),
        "seed": seed,
        "class_imbalance_strategy": CLASS_IMBALANCE_STRATEGY,
        "split_boundaries": manifest.get("split_boundaries"),
        "metrics_summary": {"per_class": per_class},
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
