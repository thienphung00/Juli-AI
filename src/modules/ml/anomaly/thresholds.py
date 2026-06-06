"""Threshold constants for buyer-behavior anomaly detection."""

from __future__ import annotations

ANOMALY_CLASSES: frozenset[str] = frozenset({"item_swap", "empty_return"})
ANOMALY_CONFIDENCE_THRESHOLD = 0.5
