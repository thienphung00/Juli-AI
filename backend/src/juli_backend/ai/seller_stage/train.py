"""Seller stage classifier training on backtest features."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from juli_backend.ai.features import SELLER_STAGE_FEATURE_COLUMNS, build_seller_stage_features
from juli_backend.ai.seller_stage.inference import predict_seller_stage
from juli_backend.ai.seller_stage.rules import classify_seller_stage
from juli_backend.ai.seller_stage.types import TrainResult

CLASS_IMBALANCE_STRATEGY = "class_weight=balanced on RandomForestClassifier (no resampling)"
DEFAULT_RANDOM_SEED = 138


def _profile_from_row(row: pd.Series) -> dict[str, Any]:
    return_rate = row["return_rate_30d"]
    return {
        "shop_age_days": int(row["shop_age_days"]),
        "order_count_30d": int(row["order_count_30d"]),
        "return_rate_30d": 0.0 if pd.isna(return_rate) else float(return_rate),
        "ad_spend_30d_vnd": float(row["ad_spend_30d_vnd"]),
    }


def _rules_label(row: pd.Series) -> str:
    profile = _profile_from_row(row)
    features = row.to_dict()
    features.update(profile)
    return classify_seller_stage(profile)  # type: ignore[arg-type]


def _load_shop_train_mask(manifest: dict[str, Any], shop_ids: pd.Series) -> pd.Series:
    """Assign shops to train split using manifest split_boundaries and earliest order date."""
    boundaries = manifest.get("split_boundaries", {})
    train_end = boundaries.get("train_end")
    if not train_end:
        return pd.Series(True, index=shop_ids.index)

    dataset_dir = Path(manifest["dataset_dir"])
    orders = pd.read_parquet(dataset_dir / "orders.parquet")
    earliest = (
        orders.groupby("shop_id")["created_at"]
        .min()
        .map(lambda value: value[:10] if isinstance(value, str) else str(value)[:10])
    )
    mask = shop_ids.map(lambda shop_id: earliest.get(shop_id, train_end) <= train_end)
    if mask.sum() == 0 or mask.sum() == len(mask):
        rng = np.random.default_rng(manifest.get("seed", DEFAULT_RANDOM_SEED))
        indices = np.arange(len(shop_ids))
        rng.shuffle(indices)
        split_at = max(1, int(len(indices) * 0.8))
        train_indices = set(indices[:split_at])
        mask = shop_ids.index.to_series().map(lambda idx: idx in train_indices)
    return mask


def train_seller_stage(
    manifest: dict[str, Any],
    output_dir: str | Path,
    *,
    seed: int = DEFAULT_RANDOM_SEED,
) -> TrainResult:
    """Train seller stage classifier; write metrics and structured training log JSON."""
    matrix = build_seller_stage_features(manifest)
    frame = matrix.frame.copy()
    frame["stage_label"] = frame.apply(_rules_label, axis=1)

    train_mask = _load_shop_train_mask(manifest, frame["shop_id"])
    train_frame = frame.loc[train_mask]
    eval_frame = frame.loc[~train_mask]

    if eval_frame.empty:
        eval_frame = train_frame.sample(frac=0.2, random_state=seed)
        train_frame = train_frame.drop(eval_frame.index)

    feature_frame = train_frame[list(SELLER_STAGE_FEATURE_COLUMNS)].fillna(0.0)
    labels = train_frame["stage_label"].tolist()

    model = RandomForestClassifier(
        n_estimators=100,
        class_weight="balanced",
        random_state=seed,
    )
    model.fit(feature_frame, labels)

    eval_features = eval_frame[list(SELLER_STAGE_FEATURE_COLUMNS)].fillna(0.0)
    eval_labels = eval_frame["stage_label"].tolist()
    predictions = model.predict(eval_features)

    precision, recall, _, _ = precision_recall_fscore_support(
        eval_labels,
        predictions,
        average="macro",
        zero_division=0,
    )
    cm = confusion_matrix(eval_labels, predictions, labels=sorted(set(labels + list(predictions))))

    metrics = {
        "precision": float(precision),
        "recall_macro": float(recall),
        "confusion_matrix": {
            "labels": sorted(set(labels + list(predictions))),
            "matrix": cm.tolist(),
        },
        "eval_rows": len(eval_frame),
        "train_rows": len(train_frame),
        "class_imbalance_strategy": CLASS_IMBALANCE_STRATEGY,
        "random_seed": seed,
    }

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    metrics_path = root / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    golden_checks = []
    for _, row in frame.head(3).iterrows():
        profile = _profile_from_row(row)
        features = row.to_dict()
        result = predict_seller_stage(model, features)
        golden_checks.append(
            {
                "shop_id": row["shop_id"],
                "predicted_stage": result.stage,
                "confidence": result.confidence,
                "rules_stage": classify_seller_stage(profile),  # type: ignore[arg-type]
            }
        )

    training_log = {
        "trained_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dataset_version": manifest.get("dataset_version"),
        "seed": seed,
        "class_imbalance_strategy": CLASS_IMBALANCE_STRATEGY,
        "split_boundaries": manifest.get("split_boundaries"),
        "metrics_summary": {
            "precision": metrics["precision"],
            "recall_macro": metrics["recall_macro"],
        },
        "sample_predictions": golden_checks,
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
