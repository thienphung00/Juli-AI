"""Serialize trained models to versioned on-disk artifacts."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from juli_backend.ai.artifacts.exceptions import ArtifactPublishError
from juli_backend.ai.artifacts.promotion import evaluate_promotion_status
from juli_backend.ai.artifacts.schema import feature_schema_hash
from juli_backend.ai.artifacts.types import ArtifactBundle, ModelSuite

MODEL_FILENAME = "model.joblib"
METADATA_FILENAME = "metadata.json"
METRICS_FILENAME = "metrics.json"


def _artifact_dir(models_root: Path, suite: ModelSuite, version: str) -> Path:
    return models_root / suite / version


def _row_count_from_metrics(metrics: dict[str, Any]) -> int:
    train_rows = int(metrics.get("train_rows", 0))
    eval_rows = int(metrics.get("eval_rows", 0))
    return train_rows + eval_rows


def publish_model(
    suite: ModelSuite,
    *,
    model: Any,
    metrics: dict[str, Any],
    version: str,
    models_root: str | Path = "models",
    train_date: str | None = None,
    row_count: int | None = None,
    feature_schema_hash_value: str | None = None,
    metrics_path: str | Path | None = None,
) -> ArtifactBundle:
    """Serialize model + metadata under models/{suite}/{version}/."""
    root = Path(models_root)
    artifact_dir = _artifact_dir(root, suite, version)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    model_path = artifact_dir / MODEL_FILENAME
    metadata_path = artifact_dir / METADATA_FILENAME
    copied_metrics_path: Path | None = None

    try:
        joblib.dump(model, model_path)
    except Exception as exc:  # noqa: BLE001 — boundary wraps serialization failures
        raise ArtifactPublishError(f"failed to serialize {suite} model: {exc}") from exc

    resolved_train_date = train_date or (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    resolved_row_count = row_count if row_count is not None else _row_count_from_metrics(metrics)
    resolved_schema_hash = feature_schema_hash_value or feature_schema_hash(suite)
    promotion_status = evaluate_promotion_status(suite, metrics)

    metadata = {
        "suite": suite,
        "version": version,
        "train_date": resolved_train_date,
        "row_count": resolved_row_count,
        "feature_schema_hash": resolved_schema_hash,
        "metrics": metrics,
        "promotion_status": promotion_status,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    if metrics_path is not None:
        source = Path(metrics_path)
        if source.is_file():
            copied_metrics_path = artifact_dir / METRICS_FILENAME
            shutil.copy2(source, copied_metrics_path)

    return ArtifactBundle(
        suite=suite,
        version=version,
        model_path=model_path,
        metadata_path=metadata_path,
        metrics_path=copied_metrics_path,
        metadata=metadata,
    )
