---
name: data-scientist
description: >-
  Evaluates ML and analytics algorithm choices for Juli-AI: fit to MVP scope, data
  availability, display-grade vs decision-grade tier, and whether a technique belongs
  in the T1–T8 catalog. Use when selecting, vetting, or challenging models —
  not when implementing trainers (see mle-agent).
metadata:
  version: 1.0.0
  category: data-analytics
  updated: 2026-06-19
  tags: [data-science, machine-learning, statistics, modeling, analytics, juli-ai]
---

# Purpose

Use when **evaluating** whether an algorithm, model family, or analytics technique
fits Juli-AI's scope, phase, and data availability — before or alongside implementation.

| Skill | Role |
|-------|------|
| **data-scientist** (this) | *What* to use, *why*, data sufficiency, tier classification, promotion readiness |
| [`mle-agent.md`](mle-agent.md) | *How* to train, publish, batch-infer, monitor drift, and wire copy layer in `src/modules/ml/` |
| [`architect.md`](architect.md) | Module boundaries, phase gates, cross-surface contracts |

Do not conflate advisory display-grade analytics with decision-grade ML that gates
money-moving actions ([ADR-011](../../../docs/decisions/011-display-grade-analytics-layer.md)).

# Authority chain (read before recommending)

1. [`docs/ml_layer.md`](../../../docs/ml_layer.md) — technique catalog T1–T8 + per-KPI mapping
2. [`docs/decisions/011-display-grade-analytics-layer.md`](../../../docs/decisions/011-display-grade-analytics-layer.md) — display vs decision split; rejected options
3. [`docs/system-design.md`](../../../docs/system-design.md) § 3 ML models — promotion targets, backtest protocol
4. [`docs/architecture/data-sources.md`](../../../docs/architecture/data-sources.md) — what data exists per phase
5. [`docs/data-models/feature-store-schema.md`](../../../docs/data-models/feature-store-schema.md) — feature authority
6. [`EXECUTION.md`](../../../EXECUTION.md) — current phase gate

# Evaluation workflow

1. **Classify the ask** — Restate as display-grade (chart + advisory signal) or
   decision-grade (gates approval/execute). Display-grade must never execute an action.
2. **Map to T1–T8** — Every Home KPI maps to one shared technique in
   [`ml_layer.md`](../../../docs/ml_layer.md). Reject one-model-per-KPI sprawl unless
   an ADR amends constraint #3 with workflow traceability.
3. **Check phase + data** — Use the data-availability matrix below. Do not recommend
   live-trained models before Phase 2.0 backtest parquet exists; do not recommend
   live inference before TikTok API approval (Phase 2.5).
4. **Profile the series or table** — Row counts, label sparsity (e.g. `empty_return`),
   history length (≥2 weekly cycles for Holt-Winters seasonality), class balance,
   null rates on schema-locked feature columns.
5. **Pick the simplest adequate method** — Rules and deterministic baselines before
   sklearn; ETS before heavy forecasters; EWMA/z-score before learned anomaly detectors
   for display-grade KPIs.
6. **Evaluate against baselines** — Compare ML to existing rules (`seller_stage/rules.py`,
   `ad_performance/rules.py`) and to the promotion gates in
   `src/modules/ml/artifacts/thresholds.py`.
7. **Communicate fit** — Tier, technique ID, data gaps, metric vs gate, and
   recommend adopt / defer / reject. Quantify business impact with tiers and deltas
   only — never raw financial PII (`core-safety.mdc`).

# Technique catalog — locked choices & vetting criteria

| ID | Technique | Implementation (MVP) | Min data / signals | Upgrade only if |
|----|-----------|------------------------|--------------------|-----------------|
| **T1** | Forecaster | statsmodels ETS / Holt-Winters + naive-seasonal fallback | Daily KPI series; ≥2 full weekly cycles for seasonality | Seasonality materially wrong after ETS tuning — revisit holidays in Phase 3+, not Prophet in MVP |
| **T2** | Ads regressor | `RandomForestRegressor` + scale/cut/hold (`ad_performance/`) | Backtest ad spend + ROAS window | Rules baseline fails AND ROAS MAPE ≤ 50% on held-out window |
| **T3** | Policy rules | Deterministic VP/AHR thresholds (§5) | Platform health fields (API or proxy) | Never ML — policy is source of truth |
| **T4** | Statistical anomaly | EWMA / rolling z-score vs baseline | Sufficient history for stable baseline | Display-grade only; do not promote to execute gate without ADR |
| **T5** | Deadline rule | SLA countdown per order | Order timestamps + SLA config | Never ML |
| **T6** | Return-fraud detector | `RandomForestClassifier` (`anomaly/`) | Labeled returns + buyer aggregate features | Per-class precision/recall ≥ 0.50 on `item_swap` + `empty_return` |
| **T7** | Ranker | Deterministic weighted score-sort (config weights) | Normalized KPI signals per entity | Never learned-to-rank in MVP — explainability requirement |
| **T8** | Router classifier | `RandomForestClassifier` (`seller_stage/`) | Shop lifecycle features | Precision ≥ 0.50 AND macro recall ≥ 0.50; else stay on rules routing |

**Intelligence heuristics (separate track — not T1–T8):**

| Module | Method | Data source | Notes |
|--------|--------|-------------|-------|
| `intelligence/forecasting` | Linear regression (≥30d) or moving average | Completed orders → SKU velocity | Read-only; equal SKU attribution MVP proxy |
| `intelligence/scoring` | Weighted score, ≥2σ anomaly, lexicon sentiment | Post-stream summary API (#7) | Not buyer-behavior anomaly; no realtime telemetry |

# Data availability by phase

Consult [`data-sources.md`](../../../docs/architecture/data-sources.md) before any recommendation.

| Phase | ML/analytics data | Implication for algorithm choice |
|-------|-------------------|----------------------------------|
| **P1** | Mock/fixtures only | UI validation; no training metrics; rules/mocks for signals |
| **P2.0** (was P1.5) | Synthetic + backtest parquet (`src/modules/ml/dataset/`) | Offline train/eval; promotion gates; sparse labels expected |
| **P2.5** (was P2) | Live TikTok polling + 08:00 UTC batch | Production inference; schema-hash validation at load |
| **P3** | Polyglot store; optional sentiment inputs | CSAT/sentiment only after legal text source exists |

**Hard data limits:**

- Order history ~90d bounded — long-horizon deep learning rarely justified.
- Buyer chat / review text **forbidden** (#17) — no CSAT/sentiment model in MVP.
- Only legal free-text for fraud signals: `return_reason` (+ inspection-derived labels).
- Affiliate/creator features **out of scope** for anomaly model ([ADR-011](../../../docs/decisions/011-buyer-behavior-anomaly-scope.md)).
- Masked `buyer_id` only — no PII in features, parquet, or eval reports.

# Algorithm selection — Juli-specific (not generic)

| Scenario | Use | Avoid (MVP) | Why |
|----------|-----|-------------|-----|
| KPI time-series on Home tab | T1 ETS / Holt-Winters | Prophet, LSTM, one forecaster per KPI | ADR-011: lightweight, explainable, shared across KPIs |
| Tabular shop/return/ad classification | `RandomForest*` + `class_weight="balanced"` | XGBoost, neural nets, SMOTE | Small/medium backtest N; existing suite pattern; seed + joblib artifacts |
| Display KPI risk flag | T4 EWMA / z-score | Isolation Forest, autoencoder | Advisory-only; auditable threshold |
| Entity prioritization (SKU, campaign) | T7 config weights | Learning-to-rank | Transparency for seller-facing copy |
| Post-stream livestream anomaly | σ-deviation in `intelligence/scoring` | Reuse T6 buyer anomaly | Different data contract (#7 post-stream only) |
| Copy / narrative | Rules + Ollama summarize | LLM decides actions | LLM rewrites signals only; never changes recommendations |

**When to escalate complexity:** only after (a) simpler baseline documented, (b) held-out
backtest shows gate failure is due to model capacity not data sparsity, and (c) Product
sign-off (#142) for decision-grade changes.

# Metrics & promotion gates

Decision-grade recycled suites — encoded in `src/modules/ml/artifacts/thresholds.py`:

| Suite / technique | Primary metrics | Gate |
|-------------------|-----------------|------|
| T8 router (`seller_stage`) | precision, recall_macro | ≥ 0.50 / ≥ 0.50 |
| T6 return-fraud (`anomaly`) | per-class precision, recall on `item_swap`, `empty_return` | ≥ 0.50 each |
| T2 ads regressor (`ad_performance`) | ROAS MAPE (lower better) | ≤ 50.0% |

**Display-grade (T1, T4):** report interval coverage, naive-seasonal baseline RMSE/MAPE,
and qualitative explainability — no promotion gate unless a technique starts gating execute.

**Classification eval (when labels exist):**

```python
from sklearn.metrics import precision_recall_fscore_support

def evaluate_multiclass(y_true, y_pred, labels: tuple[str, ...]) -> dict[str, dict[str, float]]:
    p, r, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0,
    )
    return {
        label: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f1[i]), "support": int(support[i])}
        for i, label in enumerate(labels)
    }
```

**Regression eval (ads ROAS):**

```python
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error

def roas_mape_pct(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = y_true != 0
    if not mask.any():
        return float("inf")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)
```

Run eval via suite CLIs — not ad-hoc notebooks in `src/`:

```bash
python -m src.modules.ml.dataset.cli assemble-backtest-dataset ...
python -m src.modules.ml.seller_stage.cli train-seller-stage ...
python -m src.modules.ml.anomaly.cli train-anomaly ...
python -m src.modules.ml.ad_performance.cli train-ad ...
```

# Feature engineering (repo constraints)

- Column names from [`feature-store-schema.md`](../../../docs/data-models/feature-store-schema.md) only.
- Build via `src/modules/ml/features/` (`build_anomaly_features`, `build_seller_stage_features`, `build_ad_features`) — no parallel feature pipelines.
- Time windows: reuse `features/time_windows.py` rolling aggregates (30d buyer/seller signals).
- For T1 forecasts: engineer calendar features inside the forecaster module, not per-KPI bespoke pipelines.
- Validate `feature_schema_hash` at artifact load — renaming columns is a breaking change.

# Vet new technique checklist

Before proposing anything outside T1–T8:

- [ ] Maps to ≥1 validated workflow ([ADR-013](../../../docs/decisions/013-operations-pipeline-spine.md))
- [ ] Classified display-grade (advisory) or decision-grade (needs #142 + thresholds)
- [ ] Data source row exists in `data-sources.md` for the active phase
- [ ] Simpler deterministic alternative considered and documented
- [ ] No forbidden inputs (buyer PII, affiliate fraud scope, scraping)
- [ ] No raw financial metrics in eval reports, prompts, or handoffs
- [ ] ADR drafted if the decision is hard to reverse

# Explicitly rejected or deferred

| Proposal | Status | Authority |
|----------|--------|-----------|
| ~19 trained models (one per KPI) | Rejected | ADR-011 |
| Prophet / heavy holiday forecasters | Rejected for MVP | ADR-011 |
| Learned ranker | Rejected for MVP | ADR-011 (T7 deterministic) |
| Sentiment / CSAT model | Deferred Phase 3 | No legal text source; ADR-011 |
| XGBoost / LightGBM / neural nets as default | Defer | RF sufficient at current N; revisit with live-volume evidence |
| Generic A/B test infra in repo | Out of scope | Phase 1 UX metrics via product analytics — not ML pipeline |
| MLflow / W&B experiment tracking | Out of scope | `metadata.json` + `metrics.json` per artifact version |

# Evaluation report template

```markdown
# Analytics fit review: [KPI / workflow / proposal]

## Tier
Display-grade | Decision-grade

## Technique mapping
T?_ … | New (requires ADR)

## Phase & data
Current phase: …
Sources available: … (data-sources.md rows)
Gaps: …

## Baseline vs candidate
| Method | Metric | Value | Meets gate? |
|--------|--------|-------|-------------|

## Recommendation
Adopt | Defer until [phase/data] | Reject

## Risks
Sparsity, leakage, explainability, PII exposure

## Next step
Implementation owner: mle-agent | architect | grill-with-docs
```

# Integration points

- **Implementation:** hand off approved technique to [`mle-agent.md`](mle-agent.md).
- **Architecture:** boundary or phase changes → [`architect.md`](architect.md).
- **Domain language:** new signal types → `CONTEXT.md` / domain-modeling skill.
- **Deep reference:** CLI tree, ADR index, intelligence vs ML split → [data-scientist-REFERENCE.md](data-scientist-REFERENCE.md).

# Success criteria

- Every algorithm recommendation names a T1–T8 technique or documents why an ADR is required.
- Data availability is verified against `data-sources.md` for the active phase before model choice.
- Decision-grade proposals include baseline comparison and promotion gate metrics.
- Display-grade proposals include explainability path (signal → KPI → workflow).
- Sparse or missing labels (e.g. `empty_return`) are flagged — not hidden behind aggregate accuracy.
- Financial impact uses tiers/deltas only; eval artifacts contain no raw seller financial PII.

# Scope & limitations

**In scope:** Algorithm and technique selection, data sufficiency review, backtest design,
promotion gate evaluation, challenging model sprawl, feature-scope alignment with schema.

**Out of scope:** Trainer implementation, artifact ops, copy-layer prompts, batch
scheduling (`mle-agent`), dashboard/UI, Celery/Kafka pipeline design outside ML batch.

**Limitations:** Backtest runs today use synthetic/parquet — live-volume non-stationarity
may differ. Reference metrics in system-design §3 are seed-142 synthetic, not production.
Validate gates on held-out windows before Phase 2.5 promotion.
