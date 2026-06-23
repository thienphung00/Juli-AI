---
name: mle-agent
description: >-
  ML implementation and operations for Juli-AI: training, feature engineering,
  artifact publish/load, promotion gates, drift monitoring, Phase 2 batch
  inference (Celery), CI validation, and the LLM copy layer. Use for work in
  src/modules/ml/, models/, and intelligence/ — not algorithm selection
  (data-scientist) or KPI framework design (business-intelligence).
metadata:
  version: 2.0.0
  category: data-analytics
  updated: 2026-06-19
  tags: [ml, mlops, training, artifacts, inference, celery, juli-ai]
---

# Purpose

Use when working on **ML implementation and operations** in this repo:
training, feature engineering, artifact lifecycle, promotion gates, drift
monitoring, Phase 2 batch inference, CI validation, and the LLM copy layer
(`src/modules/ml/`, `src/modules/catalog/domain/intelligence/`, `models/`).

| Skill | Role |
|-------|------|
| **mle-agent** (this) | Train, serialize, publish, smoke-test, batch-infer, monitor drift, copy layer |
| [`data-scientist.md`](data-scientist.md) | *What* to use — algorithm selection, T1–T8 vetting, data sufficiency |
| [`analytics-engineer/SKILL.md`](analytics-engineer/SKILL.md) | Feature schema migrations; materialized views feeding batch jobs |

For **algorithm selection and data-fit review** before implementation, load
[`data-scientist.md`](data-scientist.md).

# Two tracks (do not conflate)

| Track | Location | When | Algorithm |
|-------|----------|------|-----------|
| **Phase 2.0 ML layer (T1–T8)** | `src/modules/ml/` | Seller-money Home KPIs + recycled suites | ETS / EWMA / rules / `RandomForest*` → joblib where trained |
| **Intelligence heuristics** | `src/modules/catalog/domain/intelligence/` | Post-stream livestream + SKU inventory (Phase 1 rules) | Deterministic stats (σ, linear regression, lexicon) |

New work on buyer-behavior anomaly, seller stage, or ad performance belongs under `ml/`.
Livestream scoring and SKU depletion forecasting belong under `intelligence/` unless
system-design explicitly promotes them to a trained suite.

# Repo layout

```
src/modules/ml/
  dataset/       # synthetic parquet + manifest (backtest only)
  features/      # shared feature builders (schema-locked column names)
  seller_stage/  # lifecycle classifier
  anomaly/       # item_swap + empty_return detector (ADR-011)
  ad_performance/# ROAS regressor + scale/cut/hold classifier
  artifacts/     # publish, load, smoke, promotion gates
  monitoring/    # drift detection (Phase 2+)

models/{suite}/{version}/   # model.joblib + metadata.json + metrics.json

docs/data-models/feature-store-schema.md   # feature + inference authority
docs/system-design.md                      # § ML models, Copy layer, phases
```

Load the `MODULE.md` for each touched package before editing.

# Phase gates

| Phase | ML behavior |
|-------|-------------|
| **1** | Rules/mocks only; no trained models; hardcoded copy fixtures |
| **1.5** | Train on backtest parquet; serialize artifacts; evaluate promotion gates |
| **2** | Batch inference (08:00 UTC Celery); Ollama copy layer summarizes signals only |

Promotion thresholds live in `src/modules/ml/artifacts/thresholds.py` and
`evaluate_promotion_status`. Sub-threshold runs serialize as `experimental` only.
Do not promote without Product sign-off (#142) and system-design targets.

# Artifact lifecycle

Juli-AI does **not** use MLflow or W&B. Each `models/{suite}/{version}/` directory
holds `model.joblib`, `metadata.json`, and `metrics.json` — the single source of truth.

**Pipeline:** `TrainResult` → `publish_model` → `evaluate_promotion_status` → `run_smoke_test`

| Field | Rule |
|-------|------|
| `promotion_status` | `promoted` only when gates pass + Product #142; else `experimental` |
| `feature_schema_hash` | Validated at every `load_model` call — mismatch is a hard error |
| `metrics.json` | Suite-specific eval metrics only — no raw financial PII |

`load_model` surfaces **promoted** artifacts only. On rollback, set
`promotion_status` to `experimental` — inference falls back to rules baselines
(`seller_stage/rules.py`, `ad_performance/rules.py`).

For metadata schema, promotion gate table, CI checklist, and rollback steps, see
[mle-agent-REFERENCE.md](mle-agent-REFERENCE.md).

# Batch inference (Phase 2+)

Daily at **08:00 UTC** via Celery beat — three tasks (seller_stage, anomaly,
ad_performance). Phase 1 uses rules/mocks; no Celery ML jobs.

- Each task: `load_model` → `build_*_features` → predict → write results.
- Refresh Supabase `seller_kpi_snapshot` materialized view **after** all three
  tasks complete (Celery chord or chain).
- Coordinate feature schema changes with [`analytics-engineer`](analytics-engineer/SKILL.md)
  before running batch on new columns.

For task stubs, beat schedule, and monitoring checklist, see
[mle-agent-REFERENCE.md](mle-agent-REFERENCE.md).

# Drift monitoring (Phase 2+)

Drift signals **inform re-training decisions** — no auto-rollback or auto-retrain.
Re-training decision-grade suites requires Product #142 approval.

- **Feature drift:** KS statistic vs backtest reference distribution (threshold 0.15).
- **Prediction drift:** KS on output distribution vs backtest predictions.
- **Alerts:** KS > 0.20 = warning; KS > 0.35 = critical (flag for review).

Run drift checks weekly or after each batch. Drift alerts are advisory only.

For detection code and troubleshooting table, see [mle-agent-REFERENCE.md](mle-agent-REFERENCE.md).

# Copy layer boundary

```
ML / rules → structured signal JSON → LLM (summarize + localize) → UI
                                    ↘ rules fallback on timeout/budget
```

- The LLM **never** decides recommendations — only rewrites deterministic signals.
- Phase 2 uses **Ollama** locally; enforce daily token budget; log `copy_source`.
- Test prompt **template structure**, not model output quality.

# Financial PII (always on)

Seller financial fields (revenue, gmv, roas, ad_spend, cpa, cpc, ctr, aov, etc.)
are PII-classified per `core-safety.mdc`:

- Do not pass raw values into LLM prompts — use tiers, deltas, trend direction.
- Do not log at INFO+ in production training/inference paths.
- Do not embed in commit messages, PR bodies, or handoff docs.
- CI `check_metrics_pii.py` blocks raw financial values in `metrics.json`.

# Preferred patterns

- **Feature schema:** column names from `feature-store-schema.md` only; validate via `feature_schema_hash` at artifact load.
- **Training:** fixed `seed`; `class_weight="balanced"` when imbalanced — document in metrics JSON.
- **Dataset:** masked `buyer_id` only; no PII in parquet or logs.
- **Jobs:** runner-agnostic CLI modules (`python -m src.modules.ml.<suite>.cli`); Celery only in Phase 2 batch inference.
- **Artifacts:** `TrainResult` → `publish_model` → `run_smoke_test` with golden fixtures (`GOLDEN_*_FIXTURES`).
- **Anomaly scope:** buyer-behavior labels only (`item_swap`, `empty_return`, `other`); no affiliate/creator features ([ADR-011](../../../docs/decisions/011-buyer-behavior-anomaly-scope.md)).
- **Heuristics:** keep intelligence modules read-only against `src/data`; shop-scoped queries.

# Avoid

- Conflating intelligence heuristics with Phase 1.5 sklearn suites.
- Affiliate fraud, commission disputes, or creator signals in the anomaly model.
- Seller Center scraping or forbidden data sources (`data-sources.md`).
- Unit tests that assert model accuracy — test transforms, fixtures, and schema contracts instead.
- Inline prompt templates without versioning.
- New model suites without system-design.md vetting and ADR when the decision is hard to reverse.
- Hard-coding promotion gate values outside `thresholds.py`.
- Auto-retraining on drift without Product #142 sign-off.

# TDD overrides (when focus lists `mle-agent`)

- Unit-test data transformation and feature builders, not precision/recall.
- Mock TikTok Shop API responses at the service boundary.
- Test LLM prompt template structure and fallback wiring, not LLM output.
- Use golden fixtures per suite for smoke/integration paths.

# Code review checklist

- **Schema:** feature columns match `feature-store-schema.md`; hash checked on load.
- **Scope:** anomaly path excludes affiliate/creator columns; ADR-011 respected.
- **Phases:** no Phase 2 inference scheduling sneaking into Phase 1.5 trainers.
- **PII:** no raw financial metrics in logs, prompts, or test fixtures beyond masked/synthetic data.
- **Copy layer:** LLM cannot alter recommended actions; rules fallback exists.
- **Reproducibility:** seed fixed; metrics JSON written; promotion status recorded.
- **Artifacts:** `promoted_by` cites Product issue; experimental artifacts not loaded in batch.
- **MODULE.md:** public interface and out-of-scope sections still accurate.

# Agent instructions

- Read `docs/system-design.md` § ML models and Copy layer before structural changes.
- Read `docs/data-models/feature-store-schema.md` before adding or renaming features.
- Prefer extending existing `build_*_features` and CLI trainers over new parallel pipelines.
- When accuracy work is needed, use backtest CLI + held-out eval — not ad-hoc notebook logic in `src/`.
- For artifact metadata, batch scheduling, drift detection, CI pipeline, and ADR index, see
  [mle-agent-REFERENCE.md](mle-agent-REFERENCE.md).

# Scope & limitations

**In scope:** Model training, feature builders, artifact publish/load, promotion gates,
smoke tests, Phase 2 Celery batch inference, drift monitoring, CI artifact validation,
rollback procedures, copy layer wiring, intelligence heuristics.

**Out of scope:** Algorithm selection and T1–T8 vetting (`data-scientist`), Supabase
schema migrations (`analytics-engineer`), KPI framework design (`business-intelligence`),
ad-hoc SQL analysis (`data-analyst`).

**Limitations:** No MLflow/W&B — `metadata.json` + `metrics.json` per version only.
Drift detection uses KS statistic; multivariate drift is out of scope for Phase 2.
Auto-retraining on drift requires human review and Product #142 approval.
