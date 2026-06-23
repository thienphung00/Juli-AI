# data-scientist reference

Deep details for algorithm vetting and evaluation. Load on demand — not required for every task.

## Authoritative docs

| Doc | Use for |
|-----|---------|
| [`docs/ml_layer.md`](../../../docs/ml_layer.md) | T1–T8 catalog + per-KPI mapping |
| [`docs/decisions/011-display-grade-analytics-layer.md`](../../../docs/decisions/011-display-grade-analytics-layer.md) | Display vs decision; rejected Prophet/per-KPI models |
| [`docs/decisions/011-buyer-behavior-anomaly-scope.md`](../../../docs/decisions/011-buyer-behavior-anomaly-scope.md) | Anomaly label scope |
| [`docs/decisions/013-phase-15-ml-module-tree.md`](../../../docs/decisions/013-phase-15-ml-module-tree.md) | Python feature-build authority |
| [`docs/system-design.md`](../../../docs/system-design.md) § 3 | Promotion targets, backtest reference run |
| [`docs/data-models/feature-store-schema.md`](../../../docs/data-models/feature-store-schema.md) | Feature groups A–D, inference signatures |
| [`docs/data-models/mock-data-generator.md`](../../../docs/data-models/mock-data-generator.md) | Synthetic parquet rules |
| [`docs/architecture/data-sources.md`](../../../docs/architecture/data-sources.md) | Phase-gated sources |

## T1 forecaster — data profiling

Before recommending ETS / Holt-Winters:

| Check | Threshold | Fallback |
|-------|-----------|----------|
| History length | ≥14 daily points minimum | Insufficient → mock/fixture in P1 |
| Weekly seasonality | ≥2 full weekly cycles | Use naive-seasonal fallback (T1 spec) |
| Zero/inactive days | Note % zeros | May need intermittent-demand rule — escalate, do not auto-add ARIMA |
| Outliers | Flag spikes (returns, campaigns) | Winsorize or separate event rule — document in eval report |

**Rejected for MVP:** Prophet (dependency + marginal benefit at small volume), LSTM (data volume + explainability).

## T4 display anomaly — baseline design

```python
# Conceptual EWMA / z-score — implement in forecaster/anomaly serving module, not sklearn
def rolling_zscore(series, window: int, threshold: float = 2.0) -> bool:
    """Return True when latest point exceeds threshold standard deviations from rolling mean."""
    if len(series) < window:
        return False
    window_slice = series[-window:]
    mean = sum(window_slice) / len(window_slice)
    variance = sum((x - mean) ** 2 for x in window_slice) / len(window_slice)
    std = variance ** 0.5
    if std == 0:
        return series[-1] != mean
    return abs(series[-1] - mean) / std >= threshold
```

Compare against intelligence/scoring σ-deviation (livestream post-stream) — same spirit, different entity grain.

## Backtest protocol (Phase 2.0)

From system-design §3:

1. Train on historical window from assembled parquet manifest.
2. Evaluate on held-out Q4/Q1 window (or manifest-defined eval split).
3. Report suite-specific metrics vs `thresholds.py`.
4. Record `promotion_status`: `promoted` | `experimental` in artifact metadata.
5. Sub-threshold → experimental only; no Phase 2.5 load without Product #142.

### Stratified split pattern (anomaly)

The anomaly trainer uses per-label stratified holdout (`train.py`) — replicate this pattern
when adding eval for new classifiers to avoid empty eval slices for rare labels.

## Rules baselines (always compare)

| Suite | Rules entry | ML entry |
|-------|-------------|----------|
| Seller stage | `seller_stage/rules.py` → `classify_seller_stage` | `seller_stage/train.py` |
| Ad action | `ad_performance/rules.py` | `ad_performance/train.py` |

If rules meet the workflow need, defer ML promotion.

## Sparse label handling

Reference backtest (seed 142) showed `empty_return` 0.00/0.00 precision/recall — expected
with sparse synthetic labels. Evaluation must:

- Report per-class support counts.
- Not claim gate passage on macro averages alone.
- Recommend data collection or label definition review before model complexity increases.

## Time-series feature patterns (T1)

When profiling KPI series for forecast fit:

```python
import numpy as np
import pandas as pd

def profile_series(s: pd.Series) -> dict:
    s = s.dropna()
    return {
        "n": len(s),
        "null_rate": float(s.isna().mean()) if len(s) else 1.0,
        "zero_rate": float((s == 0).mean()) if len(s) else 0.0,
        "cv": float(s.std() / s.mean()) if len(s) and s.mean() != 0 else None,
        "weekly_cycles": len(s) // 7,
    }
```

Cyclical hour/dow encoding applies to intraday streams (intelligence), not daily KPI batch.

## Statistical testing (product / UX only)

Repo has no `hypothesis_tester.py`. For Phase 1 UX engagement (task clicks, approval flow),
use product analytics tooling outside `src/modules/ml/`. When documenting an experiment:

- Pre-register primary metric and minimum detectable effect.
- Report effect size and confidence interval, not p-value alone.
- Do not embed seller financial fields in experiment payloads.

## Challenging common proposals

| User ask | Response pattern |
|----------|------------------|
| "Use XGBoost for anomaly" | Compare RF baseline on backtest N; check explainability for seller-facing signal; ADR if decision-grade |
| "Train a model for each KPI" | Point to ml_layer.md shared T1/T4/T7; ADR-011 rejection |
| "Add sentiment to CSAT" | data-sources #17; defer Phase 3 |
| "Use affiliate signals in return fraud" | ADR-011 exclusion |
| "Promote intelligence/scoring to ML suite" | Separate track; promote only if system-design vetting + workflow mapping |

## Handoff to implementation

When evaluation concludes **Adopt**:

1. File or update issue with technique ID, tier, and acceptance metrics.
2. Load [`mle-agent.md`](mle-agent.md) for trainer/artifact work.
3. Update MODULE.md if public inference contract changes.
4. Draft ADR if display-grade catalog gains a new technique (ADR-011 amendment path).
