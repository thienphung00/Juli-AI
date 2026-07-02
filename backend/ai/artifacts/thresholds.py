"""Provisional backtest promotion thresholds — finalized in #142."""

from __future__ import annotations

# Seller stage classifier
SELLER_STAGE_MIN_PRECISION = 0.5
SELLER_STAGE_MIN_RECALL_MACRO = 0.5

# Anomaly detector (per anomaly class)
ANOMALY_MIN_PRECISION = 0.5
ANOMALY_MIN_RECALL = 0.5

# Ad performance analyzer (lower is better)
AD_PERFORMANCE_MAX_ROAS_MAPE = 50.0
