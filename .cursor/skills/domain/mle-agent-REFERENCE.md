# mle-agent reference

Deep details for Phase 1.5 ML work and Phase 2 MLOps. Load on demand — not required for every task.

## Authoritative docs

| Doc | Use for |
|-----|---------|
| [`docs/system-design.md`](../../../docs/system-design.md) § 3 ML models | Suite purposes, promotion targets, artifact layout |
| [`docs/system-design.md`](../../../docs/system-design.md) § 4 Copy layer | Ollama vs rules fallback, signal JSON contract |
| [`docs/data-models/feature-store-schema.md`](../../../docs/data-models/feature-store-schema.md) | Feature groups, inference signatures |
| [`docs/data-models/canonical-entities.md`](../../../docs/data-models/canonical-entities.md) | Return/Order field alignment P1→P2 |
| [`docs/data-models/mock-data-generator.md`](../../../docs/data-models/mock-data-generator.md) | Synthetic parquet rules |
| [`docs/architecture/data-sources.md`](../../../docs/architecture/data-sources.md) | Allowed/forbidden ingestion |
| [`EXECUTION.md`](../../../EXECUTION.md) | Phase slicing and explicit out-of-scope |
| [`src/modules/ml/artifacts/thresholds.py`](../../../src/modules/ml/artifacts/thresholds.py) | Promotion gate values — do not hard-code elsewhere |

## ADRs

| ADR | Topic |
|-----|-------|
| [011](../../../docs/decisions/011-buyer-behavior-anomaly-scope.md) | Anomaly classes; no affiliate scope |
| [010](../../../docs/decisions/010-ml-module-tree-and-trainers.md) | `src/modules/ml/` module tree |

## Phase 1.5 pipeline (offline)

```
assemble_backtest_dataset (dataset/)
        ↓
build_*_features (features/)
        ↓
train_* (seller_stage | anomaly | ad_performance)
        ↓
publish_model + evaluate_promotion_status + run_smoke_test (artifacts/)
```

### CLI entry points

```bash
python -m src.modules.ml.dataset.cli assemble-backtest-dataset ...
python -m src.modules.ml.seller_stage.cli train-seller-stage ...
python -m src.modules.ml.anomaly.cli train-anomaly ...
python -m src.modules.ml.ad_performance.cli train-ad ...
```

## Three suites

| Suite | Labels / target | Model | Powers workflow |
|-------|-----------------|-------|-----------------|
| `seller_stage` | `new \| leakage \| growth` | `RandomForestClassifier` | New Seller Copilot routing |
| `anomaly` | `item_swap`, `empty_return` (+ `other` negative) | `RandomForestClassifier` | Revenue Leakage Detection |
| `ad_performance` | scale / cut / hold + ROAS | `RandomForestRegressor` + classifier | Growth Copilot |

Rules baselines exist for seller stage (`classify_seller_stage`) and ad action labels;
compare ML vs rules before promotion.

## Artifact store layout

```
models/
  {suite}/
    {version}/
      model.joblib
      metadata.json
      metrics.json
```

## Artifact metadata schema

```python
# metadata.json — validated at load time
{
    "suite": "seller_stage",           # seller_stage | anomaly | ad_performance
    "version": "v1.0.0",
    "train_date": "2026-06-19T08:00:00Z",
    "row_count": 4500,
    "feature_schema_hash": "a1b2c3d4",
    "seed": 142,
    "promotion_status": "promoted",     # promoted | experimental
    "promoted_by": "Product #142"
}
```

```python
# metrics.json — NO raw financial values
# seller_stage: { "precision": 0.62, "recall_macro": 0.55, ... }
# anomaly: { "precision_item_swap": 0.58, "recall_empty_return": 0.0, ... }
# ad_performance: { "roas_mape_pct": 41.3, ... }
```

Phase 2 inference validates `feature_schema_hash` at load time.

## Promotion gates (provisional — #142 sign-off)

| Suite | Gate | Status on fail |
|-------|------|----------------|
| `seller_stage` | precision ≥ 0.50 AND recall_macro ≥ 0.50 | `experimental`; not loaded in batch |
| `anomaly` | per-class precision ≥ 0.50 AND recall ≥ 0.50 on `item_swap` + `empty_return` | Same; `empty_return` sparse in synthetic — document, do not gate alone |
| `ad_performance` | ROAS MAPE ≤ 50.0% on held-out window | Same |

```python
from src.modules.ml.artifacts import evaluate_promotion_status

result = evaluate_promotion_status(
    suite="seller_stage",
    metrics_path="models/seller_stage/v1.0.0/metrics.json",
)
# result.status: "promoted" | "experimental"
```

## Rollback procedure

1. Set `promotion_status` to `experimental` in `metadata.json`.
2. Inference falls back to rules baselines — `load_model` only surfaces promoted artifacts.
3. Document in the issue thread; do not delete the artifact.
4. Post-mortem with backtest evidence before re-promoting.

## Batch inference (Phase 2+)

```python
# src/tasks/ml_inference_batch.py — illustrative
from celery import shared_task
from src.modules.ml.artifacts import load_model

@shared_task(name="ml.batch_inference.seller_stage")
def run_seller_stage_inference():
    model = load_model("seller_stage")
    features = build_seller_stage_features()
    predictions = model.predict(features)
    _write_inference_results("seller_stage", predictions)
# anomaly and ad_performance tasks follow the same pattern
```

```python
# Celery beat — 08:00 UTC daily
CELERYBEAT_SCHEDULE = {
    "seller-stage-inference": {"task": "ml.batch_inference.seller_stage", "schedule": "0 8 * * *"},
    "anomaly-inference":      {"task": "ml.batch_inference.anomaly",      "schedule": "0 8 * * *"},
    "ad-inference":           {"task": "ml.batch_inference.ad_performance", "schedule": "0 8 * * *"},
}
```

Refresh `seller_kpi_snapshot` materialized view after all three tasks complete.

## Drift detection

```python
# src/modules/ml/monitoring/drift.py — conceptual
import numpy as np
from dataclasses import dataclass

@dataclass
class DriftResult:
    feature: str
    ks_statistic: float
    is_drifted: bool
    note: str = ""

def ks_drift(reference: np.ndarray, current: np.ndarray) -> float:
    n, m = len(reference), len(current)
    combined = np.sort(np.concatenate([reference, current]))
    cdf_ref = np.searchsorted(reference, combined, side="right") / n
    cdf_cur = np.searchsorted(current, combined, side="right") / m
    return float(np.max(np.abs(cdf_ref - cdf_cur)))
```

| Signal | Threshold | Action |
|--------|-----------|--------|
| Feature KS > 0.20 | Warning | Log; schedule re-evaluation |
| Feature KS > 0.35 | Critical | Flag for re-training review (#142) |
| Prediction KS > 0.15 | Warning | Compare recent vs backtest metrics |
| Gate failure on re-run | Blocker | Stay on rules baseline |

## CI/CD for model artifacts

```yaml
# .github/workflows/ml-artifact-validate.yml — illustrative
on:
  pull_request:
    paths: ["models/**", "src/modules/ml/**", "docs/data-models/feature-store-schema.md"]
jobs:
  validate-artifacts:
    steps:
      - run: python -m src.modules.ml.artifacts.cli validate-metadata --all
      - run: python -m pytest tests/ml/ -k "smoke" --tb=short
      - run: python -m src.modules.ml.artifacts.cli check-schema-hash --all
      - run: python scripts/ci/check_metrics_pii.py models/
```

### Promotion checklist (before merging `models/`)

- [ ] `promotion_status` is `promoted` (or `experimental` with justification)
- [ ] `feature_schema_hash` matches current `feature-store-schema.md`
- [ ] `metrics.json` meets all gates in `thresholds.py`
- [ ] Smoke test passes with `GOLDEN_*_FIXTURES`
- [ ] `promoted_by` cites Product issue (#142)
- [ ] No raw financial values in `metrics.json`

## Monitoring checklist (Phase 2+)

- [ ] Feature drift: backtest reference vs last 7d inference inputs
- [ ] Prediction distribution vs backtest predictions
- [ ] Re-evaluate promotion gates on recent labeled data
- [ ] `run_smoke_test` against golden fixtures
- [ ] Celery beat: all three batch tasks complete within 30 min of 08:00 UTC

## Troubleshooting

| Problem | Likely cause | Resolution |
|---------|-------------|------------|
| `feature_schema_hash` mismatch | Column renamed without updating metadata | Re-run `publish_model` after Alembic migration |
| Batch task fails silently | Worker OOM or timeout | Check worker memory; profile feature builder |
| `load_model` raises | No promoted artifact | Confirm `promotion_status: promoted` |
| Drift alerts on all features at launch | Backtest ≠ live distribution (expected) | Re-establish reference from first 2 weeks live data |
| `check_metrics_pii.py` fails | Raw financial values in metrics | Use tiers/deltas only (`core-safety.mdc`) |
| Celery beat not running | Scheduler not started | Confirm `celery -A src.celery beat` is running |

## Intelligence heuristics (separate track)

| Module | Key functions | Notes |
|--------|---------------|-------|
| `intelligence/scoring` | `score_livestream`, `detect_anomalies`, `analyze_comments` | Post-stream API data only (#7) |
| `intelligence/forecasting` | `get_forecast`, `get_low_stock_risks`, `get_velocity_changes` | SKU depletion; ≥30d → linear regression |

These modules do **not** write to DB. Anomaly here is σ-deviation on revenue/orders/viewers —
not buyer-behavior `item_swap` / `empty_return` (that is `ml/anomaly`).

## Copy layer signal JSON (Phase 2)

Input to Ollama: structured fields only — signal type, severity, tier labels,
recommended action. Never raw financial PII. Rules fallback keyed by signal type
(e.g. `anomaly:item_swap`, `ad:scale_candidate`).

## Related review context

When adding LLM or external model calls, also load:

- `.cursor/skills/standalone/review/checklists/ai-integration.md`
- `.cursor/rules/reliability.mdc`, `.cursor/rules/observability.mdc`
