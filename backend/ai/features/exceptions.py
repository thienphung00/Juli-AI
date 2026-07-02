"""Feature builder validation errors."""

from __future__ import annotations


class FeatureValidationError(ValueError):
    """Raised when feature inputs or outputs violate the schema contract."""
