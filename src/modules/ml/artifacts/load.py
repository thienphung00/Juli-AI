"""Load serialized model artifacts from disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib

from src.modules.ml.artifacts.exceptions import ArtifactLoadError
from src.modules.ml.artifacts.publish import METADATA_FILENAME, MODEL_FILENAME
from src.modules.ml.artifacts.types import LoadedModel, ModelSuite


def _artifact_dir(models_root: Path, suite: ModelSuite, version: str) -> Path:
    return models_root / suite / version


def load_model(
    suite: ModelSuite,
    version: str,
    *,
    models_root: str | Path = "models",
) -> LoadedModel:
    """Load model.joblib and metadata.json for a suite/version."""
    root = Path(models_root)
    artifact_dir = _artifact_dir(root, suite, version)
    model_path = artifact_dir / MODEL_FILENAME
    metadata_path = artifact_dir / METADATA_FILENAME

    if not model_path.is_file():
        raise ArtifactLoadError(f"missing model artifact: {model_path}")
    if not metadata_path.is_file():
        raise ArtifactLoadError(f"missing metadata artifact: {metadata_path}")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactLoadError(f"invalid metadata JSON at {metadata_path}: {exc}") from exc

    try:
        model = joblib.load(model_path)
    except Exception as exc:  # noqa: BLE001 — boundary wraps deserialization failures
        raise ArtifactLoadError(f"failed to load model artifact at {model_path}: {exc}") from exc

    return LoadedModel(suite=suite, version=version, model=model, metadata=metadata)


def load_metadata(
    suite: ModelSuite,
    version: str,
    *,
    models_root: str | Path = "models",
) -> dict[str, Any]:
    """Load metadata.json without deserializing the model."""
    metadata_path = _artifact_dir(Path(models_root), suite, version) / METADATA_FILENAME
    if not metadata_path.is_file():
        raise ArtifactLoadError(f"missing metadata artifact: {metadata_path}")
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactLoadError(f"invalid metadata JSON at {metadata_path}: {exc}") from exc
