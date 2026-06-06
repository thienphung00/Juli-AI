"""Threshold constants for ad performance action ranking."""

from __future__ import annotations

AD_ACTIONS: frozenset[str] = frozenset({"scale", "cut", "hold"})
HOLD_CONFIDENCE_THRESHOLD = 0.5
SPARSE_HISTORY_MIN_IMPRESSIONS = 50
SPARSE_HISTORY_MIN_CLICKS = 5
SPARSE_HISTORY_MIN_CONVERSIONS = 1
SPARSE_MAX_CONFIDENCE = 0.35
SCALE_ROAS_RATIO = 1.2
CUT_ROAS_RATIO = 0.75
