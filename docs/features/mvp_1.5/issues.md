# MVP 1.5 — Phase 1.5 Issue Queue

**Parent PRD:** Local [`PRD.md`](PRD.md) · GitHub parent issue: [#135](https://github.com/thienphung00/Juli-AI/issues/135)

Process issues top-to-bottom. **#138**, **#139**, and **#140** can run in parallel after **#137**. **#141** and **#142** can run in parallel after all three trainers land.

> **GitHub sync:** Authoritative Phase 1.5 issue set is **#135–#143** below (created 2026-06-05).

| Order | Issue | Title | Type | Blocked by | EXECUTION slice | Modules |
|-------|-------|-------|------|------------|-----------------|---------|
| 0 | [#135](https://github.com/thienphung00/Juli-AI/issues/135) | PRD: MVP 1.5 — Phase 1.5 ML Models | AFK | — | (parent) | — |
| 1 | [#136](https://github.com/thienphung00/Juli-AI/issues/136) | Backtest dataset assembly (parquet + synthetic) | AFK | — | P1.5-1 | `ml/dataset` |
| 2 | [#137](https://github.com/thienphung00/Juli-AI/issues/137) | Feature builder for all three model suites | AFK | #136 | — | `ml/features` |
| 3 | [#138](https://github.com/thienphung00/Juli-AI/issues/138) | Seller stage classifier — train + rules baseline | AFK | #137 | P1.5-2 | `ml/seller_stage` |
| 4 | [#139](https://github.com/thienphung00/Juli-AI/issues/139) | Anomaly detector — buyer behavior only | AFK | #137 | P1.5-3 | `ml/anomaly` |
| 5 | [#140](https://github.com/thienphung00/Juli-AI/issues/140) | Ad performance analyzer — train + backtest | AFK | #137 | P1.5-4 | `ml/ad_performance` |
| 6 | [#141](https://github.com/thienphung00/Juli-AI/issues/141) | Serialize models + metadata + smoke tests | AFK | #138, #139, #140 | P1.5-6 | `ml/artifacts` |
| 7 | [#142](https://github.com/thienphung00/Juli-AI/issues/142) | Feature specs, inference signatures, threshold sign-off | HITL | #138, #139, #140 | P1.5-5 | `docs/data-models`, `docs/system-design` |
| 8 | [#143](https://github.com/thienphung00/Juli-AI/issues/143) | Publish Phase 2 target architecture (`target-v2.md`) | AFK | #141, #142 | P1.5-7 | `docs/architecture` |

## Anomaly detector scope (ADR-011)

- **In scope:** buyer-behavior return anomalies — `item_swap`, `empty_return`; negative class `other`.
- **Inputs:** Order, OrderItem, Return parquet and buyer aggregate features derived from return history only.
- **Out of scope:** affiliate signals, creator-attributed refunds, commission fraud — not part of the anomaly model (policy rules in Phase 2).

## Parallelization

After **#137** lands, **#138**, **#139**, and **#140** are disjoint (`ml/seller_stage`, `ml/anomaly`, `ml/ad_performance`) and may run in parallel per `issue-workflow.mdc`.

After all three trainers land, **#141** and **#142** are disjoint (code artifacts vs canonical docs) and may run in parallel. **#142** requires Product sign-off on backtest thresholds before close.

**Do not extend** legacy `src/modules/catalog/domain/intelligence/scoring/` — new seller-money ML lives under the module tree bootstrapped in **#136**.

---

## Issue bodies (create in this order)

### #124 — PRD: MVP 1.5 — Phase 1.5 ML Models

## What to build

Parent tracking issue for Phase 1.5 (Weeks 6–9): offline ML pipeline — backtest parquet, three trained model suites (seller stage, buyer-behavior anomaly, ad performance), feature specs, serialized artifacts with metadata, and Phase 2 target architecture doc. No production inference, no TikTok API calls, no UI changes.

Full PRD: `docs/features/mvp_1.5/PRD.md`

## Acceptance criteria

- Child issues #125–#132 created and linked
- Phase 1.5 exit gate criteria documented in PRD (precision/recall targets, `target-v2.md` published)
- EXECUTION.md P1.5-1 through P1.5-7 slices traceable to child issues
- Anomaly detector scoped to buyer-behavior returns only per ADR-011

## Blocked by

None — can start immediately

---

### #125 — Backtest dataset assembly (parquet + synthetic)

## Parent

#124

## What to build

End-to-end backtest data layer: bootstrap the Phase 1.5 Python ML module tree (MODULE.md per `map.md`), pin ML dependencies (scikit-learn, xgboost, pandas, pyarrow), and ship a runner-agnostic dataset assembler that produces versioned parquet under `backtest/` — orders, order_items, returns, buyer-behavior labels, and ads — with synthetic fallback when historical TikTok data is unavailable. Schema validation runs before any downstream job. **No affiliate parquet** in the anomaly path (ADR-011).

## Acceptance criteria

- ML module directory exists with MODULE.md; dependencies pinned in requirements
- CLI `assemble-backtest-dataset` (or equivalent) writes manifest JSON with row counts, date range, split boundaries, and dataset version
- Parquet files: `orders.parquet`, `order_items.parquet`, `returns.parquet`, `labels.parquet`, `ads.parquet` with columns matching `system-design.md` § Return schema contract
- `labels.parquet` contains buyer-behavior labels only: `return_id`, `ground_truth_anomaly`, `return_type` (`item_swap` | `empty_return` | `other`)
- Synthetic generator produces labeled `item_swap` and `empty_return` rows at realistic prevalence; masked `buyer_id` only — no PII
- Schema manifest validation fails fast on missing columns or invalid enums
- Integration test: assemble tiny fixture dataset with fixed seed → manifest + all parquet files present
- Integration test: corrupt parquet (missing `return_type`) raises validation error with actionable message
- No TikTok API calls; no Postgres writes

## Blocked by

None — can start immediately

**User stories:** 1–10, 50–52

---

### #126 — Feature builder for all three model suites

## Parent

#124

## What to build

Shared feature builder that reads a dataset manifest + parquet from #125 and produces per-model feature matrices with column names matching [`docs/data-models/feature-store-schema.md`](../../data-models/feature-store-schema.md). Three public entrypoints: seller-stage features (shop-level), anomaly features (return/buyer aggregates from Order/OrderItem/Return only), and ad features (campaign/day grain). Runner-agnostic plain Python functions — no scheduler coupling.

## Acceptance criteria

- `buildSellerStageFeatures(manifest) → FeatureMatrix` with documented shop-level columns (shop age, order count, return rate, ad spend, GMV)
- `buildAnomalyFeatures(manifest) → FeatureMatrix` using Group A features only; **rejects** affiliate/creator columns if present in input
- `buildAdFeatures(manifest) → FeatureMatrix` with spend, ROAS, CPC, conversion, and account-baseline columns
- Buyer aggregates computable: `buyer_return_count_30d`, `buyer_item_swap_count_30d`, `buyer_empty_return_count_30d`, `buyer_repeat_anomaly_flag`, `return_rate_30d`
- Unit test: golden mini-parquet → anomaly feature matrix column names match `feature-store-schema.md` exactly
- Unit test: anomaly builder raises or strips if non Order/OrderItem/Return columns are passed
- Unit test: buyer aggregate counts match hand-computed expected values on fixture
- Integration test: all three builders run on #125 tiny fixture without error

## Blocked by

Blocked by #125

**User stories:** 8, 24, 32, 39, 50

---

### #127 — Seller stage classifier — train + rules baseline

## Parent

#124

## What to build

Train a seller lifecycle classifier (`new | leakage | growth`) on backtest features from #126. Evaluate precision/recall on held-out window. Port Phase 1 rules baseline thresholds from `web/src/lib/seller-stage-router/thresholds.ts` into a Python comparable module and produce a rules-vs-ML comparison report on the same profiles. Expose stable inference signature (input feature vector → class + confidence). Fixed random seed; structured JSON training logs (no PII).

## Acceptance criteria

- CLI train entrypoint runs on #125 backtest split; writes metrics JSON (precision, recall macro, confusion matrix)
- Class imbalance strategy documented (class weights, resampling, or stratified split)
- Rules baseline module mirrors `ORDER_COUNT_NEW_MAX`, `RETURN_RATE_LEAKAGE_MIN`, `SHOP_AGE_NEW_MAX_DAYS`, `ORDER_COUNT_GROWTH_MIN`, `AD_SPEND_GROWTH_MIN_VND`
- Comparison report: agreement rate + disagreement cases exportable as JSON
- Integration test: golden profiles (new, leakage, growth + threshold edge cases) → expected stage from rules baseline
- Integration test: ML inference on same golden profiles returns valid class + confidence in `[0, 1]`
- Integration test: `compareToRulesBaseline` report includes agreement rate field
- No TikTok API calls; no UI changes

## Blocked by

Blocked by #126

**User stories:** 11–18, 53–54, 56–57

---

### #128 — Anomaly detector — buyer behavior only

## Parent

#124

## What to build

Train an anomaly detector exclusively on buyer-behavior return signals: classes `item_swap` and `empty_return`, with `other` as negative examples. Features from #126 anomaly builder only (Order, OrderItem, Return — no affiliate or creator data). Report precision/recall **per class** on held-out labeled ground truth. Output includes anomaly class, confidence, and contributing feature summary for Phase 2 UI evidence.

## Acceptance criteria

- Training uses only Order/OrderItem/Return-derived features and buyer-behavior labels from `labels.parquet`
- Per-class metrics reported separately for `item_swap` and `empty_return` on held-out split
- Integration test: golden `item_swap` row scores as anomaly with class `item_swap`
- Integration test: golden `empty_return` row scores as anomaly with class `empty_return`
- Integration test: golden `other` (legitimate return) scores below anomaly threshold or as non-anomaly
- Integration test: feature matrix for anomaly training contains no affiliate/creator column names
- Inference output schema documented: `{ anomaly_class, confidence, feature_summary }`
- No affiliate fraud, commission dispute, or creator-attributed refund signals in training or inference (ADR-011)
- No TikTok API calls

## Blocked by

Blocked by #126

**User stories:** 19–27, 53–54

---

### #129 — Ad performance analyzer — train + backtest

## Parent

#124

## What to build

Train ad performance model on backtest campaign metrics from #126 ad features. Predict ROAS and rank campaigns as scale, cut, or hold with confidence. Report MAPE (or equivalent) on held-out window. Handle sparse ad history with low-confidence hold — no crash on new sellers with minimal data.

## Acceptance criteria

- CLI train entrypoint runs on #125 ads parquet split; writes metrics JSON including ROAS MAPE on held-out window
- Model outputs discrete action: `scale | cut | hold` plus confidence per campaign
- Account-level baseline features included (average ROAS, spend velocity)
- Integration test: golden scale candidate campaign → `scale` action with confidence above hold threshold
- Integration test: golden cut candidate campaign → `cut` action
- Integration test: sparse-history campaign → `hold` with low confidence (does not raise)
- No TikTok API calls

## Blocked by

Blocked by #126

**User stories:** 28–34, 53–54

---

### #130 — Serialize models + metadata + smoke tests

## Parent

#124

## What to build

Model artifact publisher: serialize all three trained suites from #127–#129 as joblib under `models/{seller_stage,anomaly,ad_performance}/{version}/` with `metadata.json` (train date, row count, feature schema hash, metrics snapshot). Promotion gate: models meeting backtest thresholds marked `promoted`; sub-threshold runs marked `experimental` only. CI smoke test loads each artifact and runs inference on golden fixtures.

## Acceptance criteria

- Directory layout matches `system-design.md`:
  ```
  models/seller_stage/{version}/model.joblib + metadata.json
  models/anomaly/{version}/model.joblib + metadata.json
  models/ad_performance/{version}/model.joblib + metadata.json
  ```
- `metadata.json` includes: `train_date`, `row_count`, `feature_schema_hash`, `metrics`, `promotion_status` (`promoted` | `experimental`)
- `publishModel` / `loadModel` public interface; load + infer on golden fixture in smoke test
- Integration test: corrupt model file fails smoke test with clear error
- Integration test: sub-threshold run serializes as `experimental` only (not `promoted`)
- Metrics JSON written alongside model file during training (no re-run required for exit-gate review)
- No Postgres persistence

## Blocked by

Blocked by #127, #128, #129

**User stories:** 40–44, 37

---

### #131 — Feature specs, inference signatures, threshold sign-off

## Parent

#124

## What to build

Document feature specs and inference signatures for all three model suites in [`docs/data-models/feature-store-schema.md`](../../data-models/feature-store-schema.md) (seller-stage and ad feature groups if not already complete). Cross-link inference signatures from `system-design.md`. Replace `_TBD_` precision/recall/MAPE placeholders in `system-design.md` with agreed backtest targets from actual #127–#129 metrics. **Requires Product lead sign-off** on numeric thresholds before issue close.

## Acceptance criteria

- Seller-stage, anomaly (Group A complete), and ad feature groups documented in `feature-store-schema.md` with exact field names matching #126 output
- Inference signature per suite: input schema, output schema, model version pointer — cross-linked from `system-design.md`
- `system-design.md` § ML models targets filled (no `_TBD_` for seller stage, anomaly per-class, ad MAPE)
- Feature schema hashes in docs match `metadata.json` from #130 promoted artifacts
- Field names align with Return schema contract and ads parquet layout (no P1.5 → P2 drift)
- **HITL:** Product lead confirms threshold numbers in PR or linked comment before close
- Manual review: doc links resolve; ADR-011 anomaly scope reflected in feature group descriptions

## Blocked by

Blocked by #127, #128, #129

**User stories:** 35–39, 38, 60

---

### #132 — Publish Phase 2 target architecture (`target-v2.md`)

## Parent

#124

## What to build

Author `docs/architecture/target-v2.md` describing the Phase 2 inference pipeline: TikTok API poll → ETL → canonical entities → feature build (06:00–07:00 UTC) → batch inference (08:00 UTC) → copy layer (Ollama + rules fallback) → UI swap → executor. Reference serialized model paths from #130, inference signatures from #131, and `health_data_source: api | proxy | unavailable` contract for VP/AHR. Cross-link from `EXECUTION.md`, `system-design.md`, and `map.md`.

## Acceptance criteria

- `docs/architecture/target-v2.md` exists with end-to-end Phase 2 flow diagram or equivalent
- Documents what stays mock in Phase 1 vs goes live in Phase 2
- References `models/` artifact paths, 08:00 UTC inference schedule, Ollama placement after inference
- Documents `health_data_source` contract; no assumption that VP/AHR API fields are exposed
- Anomaly ML section states buyer-behavior only (`item_swap`, `empty_return`); policy signals separate
- Cross-links added in `EXECUTION.md`, `system-design.md`, and `map.md` pointing to `target-v2.md`
- Manual review: no Seller Center scraping, no buyer PII, no Celery/Kafka in Phase 2 scope

## Blocked by

Blocked by #130, #131

**User stories:** 45–49

---

## Handoff: to-issues → implementation

### Issue Queue (dependency order)

1. #136 — Backtest dataset assembly (parquet + synthetic) — AFK — blocked by: none
2. #137 — Feature builder for all three model suites — AFK — blocked by: #136
3. #138 — Seller stage classifier — train + rules baseline — AFK — blocked by: #137
4. #139 — Anomaly detector — buyer behavior only — AFK — blocked by: #137
5. #140 — Ad performance analyzer — train + backtest — AFK — blocked by: #137
6. #141 — Serialize models + metadata + smoke tests — AFK — blocked by: #138, #139, #140
7. #142 — Feature specs, inference signatures, threshold sign-off — HITL — blocked by: #138, #139, #140
8. #143 — Publish Phase 2 target architecture (`target-v2.md`) — AFK — blocked by: #141, #142

### Parent PRD

- Local: `docs/features/mvp_1.5/PRD.md`
- GitHub: [#135](https://github.com/thienphung00/Juli-AI/issues/135)

### Implementation Order

Process issues top-to-bottom. For each AFK issue: run **focus → tdd → review → ship**. Skip **#142** until Product confirms backtest thresholds.

### EXECUTION.md mapping

| EXECUTION slice | Issue |
|-----------------|-------|
| P1.5-1 Backtest dataset assembly | #136 |
| P1.5-2 Seller stage classifier | #138 |
| P1.5-3 Anomaly detector (buyer behavior) | #139 |
| P1.5-4 Ad performance analyzer | #140 |
| P1.5-5 Feature specs + inference signatures | #142 |
| P1.5-6 Serialize models + metadata | #141 |
| P1.5-7 Publish `target-v2.md` | #143 |

*(#137 Feature builder is shared infrastructure between P1.5-1 and the three trainers.)*
