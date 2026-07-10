"""Artifact serialization errors."""

from __future__ import annotations


class ArtifactError(Exception):
    """Base error for model artifact operations."""


class ArtifactLoadError(ArtifactError):
    """Raised when a serialized model cannot be loaded."""


class ArtifactPublishError(ArtifactError):
    """Raised when model publication fails."""
