# PRD: MVP 1.5 — Phase 1.5 ML Models

> **Phase:** 1.5 (Weeks 6–9) · **Authority:** [`EXECUTION.md`](../../../EXECUTION.md) · **Design:** [`docs/system-design.md`](../../system-design.md)
>
> **Exit gate:** All three model suites trained and serialized; precision/recall meets backtest targets (recorded in `system-design.md`); `docs/architecture/target-v2.md` published.

---

## Problem Statement

Phase 1 validated that the three seller-money workflows (New Seller Copilot, Revenue Leakage Detection, Growth Copilot) resonate with test sellers when powered by mock data and rules-based routing. Before wiring live TikTok APIs and daily inference in Phase 2, the team must prove that ML can outperform or replace the Phase 1 rules baseline on historical data.

Today there are no trained models, no backtest parquet datasets aligned to the P1 → P2 schema contract, and no serialized artifacts ready for a Phase 2 inference job. Without Phase 1.5, Phase 2 would ship untested classifiers and regressors against live seller data — risking false positives on return anomalies, mis-routed workflows, and unreliable ad scale/cut recommendations.

Phase 1.5 must train three model suites offline, validate precision/recall (and ROAS error for the ad model) on a held-out Q4/Q1 backtest window, document feature specs and inference signatures, serialize artifacts with metadata, and publish the Phase 2 target architecture — all without production inference, live API calls, or UI changes beyond what Phase 1 already ships.

---

## Solution

Build an offline ML pipeline that assembles backtest parquet (historical TikTok Shop data or synthetic when unavailable), engineers features per model suite, trains and evaluates three models against documented ground truth, compares the seller-stage classifier to the Phase 1 rules router baseline, serializes passing models with metadata, and updates canonical docs with thresholds, feature specs, inference signatures, and the Phase 2 target design.

The anomaly detector detects **buyer-behavior return anomalies only** — `item_swap` (wrong item returned) and `empty_return` (empty parcel) — per [ADR-011](../../decisions/011-buyer-behavior-anomaly-scope.md). Inputs are limited to **Order**, **OrderItem**, and **Return** records and buyer aggregate features derived from them. It does **not** score affiliate activity, commission disputes, creator-attributed refunds, VP/AHR milestones, or balance withholding — those remain deterministic policy rules in Phase 2, not ML.

UX stays on Phase 1 mock fixtures; Phase 1.5 produces artifacts and documentation consumed by Phase 2 inference and ETL.

---

## User Stories

### Backtest data assembly (P1.5-1)

> **Anomaly backtest:** orders, order_items, returns, and buyer-behavior labels only — no affiliate parquet ([ADR-011](../../decisions/011-buyer-behavior-anomaly-scope.md), [`data-sources.md`](../../architecture/data-sources.md)).

1. As an **ML engineer**, I want a versioned backtest dataset in parquet format (orders, order_items, returns, labels, ads), so that all three model suites train on the same schema contract with the anomaly path limited to buyer-behavior entities.
2. As an **ML engineer**, I want parquet columns to match the Return schema contract in `system-design.md` (`order_id`, `return_id`, `buyer_id`, `product_id`, `sku_id`, `return_type`, `return_condition`, etc.), so that Phase 2 ETL mapping does not require rework.
3. As an **ML engineer**, I want a synthetic data generator when historical TikTok data is unavailable, so that Phase 1.5 is not blocked on external data procurement.
4. As an **ML engineer**, I want the synthetic generator to produce labeled `item_swap` and `empty_return` rows with realistic buyer aggregate features, so that the anomaly detector has ground truth to validate against.
5. As an **ML engineer**, I want train/validation/test splits documented (e.g., train on earlier window, evaluate on held-out Q4/Q1), so that backtest metrics are reproducible and not overfit.
6. As a **data engineer**, I want parquet files validated against a schema manifest before any training job runs, so that corrupt rows fail fast with actionable errors.
7. As a **product owner**, I want the dataset row counts and date ranges recorded in metadata, so that exit-gate reviewers know what the models were trained on.
8. As an **ML engineer**, I want buyer aggregate features (`buyer_return_count_30d`, `buyer_item_swap_count_30d`, `buyer_empty_return_count_30d`, `buyer_repeat_anomaly_flag`) computable from returns parquet, so that anomaly model inputs match the documented contract.
9. As a **compliance reviewer**, I want backtest data to use masked `buyer_id` values only with no PII fields, so that Phase 1.5 complies with data-source policy (#17).
10. As an **ML engineer**, I want ads backtest parquet with daily spend, CPC, conversions, and ROAS fields, so that the ad performance analyzer has sufficient signal.

### Seller stage classifier (P1.5-2)

11. As an **ML engineer**, I want to train a seller lifecycle classifier (`new | leakage | growth`) from shop-level features (shop age, order count, return rate, ad spend, GMV), so that Phase 2 can replace rules-based routing with learned boundaries.
12. As a **product owner**, I want backtest precision and recall reported against labeled historical stages, so that we know the classifier is accurate enough to ship.
13. As an **ML engineer**, I want a side-by-side comparison of ML predictions vs the Phase 1 `classifySellerStage()` rules baseline on the same backtest profiles, so that ML must demonstrably improve on or match rules before promotion.
14. As a **QA engineer**, I want golden fixture profiles (new, leakage, growth + threshold edge cases) scored by both rules and ML, so that regressions are catchable in CI.
15. As an **ML engineer**, I want the classifier to expose a stable inference signature (input feature vector schema, output class + confidence), so that Phase 2 batch inference can consume it without guesswork.
16. As a **seller** *(indirect)*, I want workflow routing in Phase 2 to reflect my actual shop metrics rather than hand-tuned thresholds alone, so that recommendations feel personalized.
17. As an **ML engineer**, I want class imbalance handled explicitly (documented strategy: class weights, resampling, or stratified splits), so that minority stages are not ignored.
18. As a **developer**, I want training scripts runnable from the CLI with a fixed random seed, so that results are reproducible across machines.

### Anomaly detector — buyer behavior only (P1.5-3)

> **In scope:** `item_swap`, `empty_return`, and legitimate returns (`other` as negative class).  
> **Out of scope:** affiliate signals, creator-attributed refunds, commission fraud — not part of this model.

19. As an **ML engineer**, I want to train an anomaly detector exclusively on buyer-behavior return signals (`item_swap`, `empty_return`), so that Revenue Leakage Detection ML aligns with ADR-011.
20. As a **product owner**, I want precision and recall reported separately for `item_swap` and `empty_return` on labeled ground truth, so that exit-gate thresholds can be set per anomaly class.
21. As an **ML engineer**, I want legitimate returns (`return_type: other`) in the training set as negative examples, so that the model does not flag normal size/SNAD returns as anomalies.
22. As an **ML engineer**, I want the anomaly training dataset to contain only Order, OrderItem, and Return parquet — no affiliate or creator columns — so that the model learns buyer return behavior and nothing else.
23. As a **seller** *(indirect)*, I want false positives minimized on return anomalies, so that I am not overwhelmed with incorrect leakage alerts in Phase 2.
24. As an **ML engineer**, I want buyer-level aggregate features (return counts, repeat-anomaly flags) computed from return history only, as documented in `feature-store-schema.md`, so that repeat offenders are detectable.
25. As a **QA engineer**, I want labeled golden cases (one `item_swap`, one `empty_return`, one `other`) that score predictably, so that inference behavior is regression-tested.
26. As an **ML engineer**, I want the detector output to include anomaly class, confidence score, and contributing feature summary, so that Phase 2 UI can show evidence without exposing raw model internals.
27. As a **compliance reviewer**, I want anomaly features and labels sourced exclusively from order/return records with masked `buyer_id` and no PII, so that ADR-011 buyer-behavior scope is enforced in code and tests.

### Ad performance analyzer (P1.5-4)

28. As an **ML engineer**, I want to train an ad performance model on backtest campaign metrics (spend, ROAS, CPC, conversions, impressions), so that Growth Copilot can rank scale/cut candidates in Phase 2.
29. As a **product owner**, I want MAPE or equivalent ROAS prediction error on the held-out backtest window, so that ad recommendations are grounded in measurable accuracy.
30. As an **ML engineer**, I want the model to flag campaigns as scale candidates, cut candidates, or hold, with confidence, so that the Growth workflow has discrete actions to surface.
31. As a **seller** *(indirect)*, I want scale/cut suggestions backed by historical performance patterns, not arbitrary thresholds, so that I trust ad recommendations.
32. As an **ML engineer**, I want account-level baselines (average ROAS, spend velocity) as features, so that recommendations are relative to the seller's norm.
33. As a **QA engineer**, I want golden ad campaign fixtures with known scale/cut labels, so that inference output is verifiable in tests.
34. As an **ML engineer**, I want missing or sparse ad history handled gracefully (low-confidence hold, not crash), so that new sellers with minimal ad data do not break inference.

### Feature specs and inference signatures (P1.5-5)

35. As a **Phase 2 engineer**, I want feature specs for all three models documented in [`docs/data-models/feature-store-schema.md`](../../data-models/feature-store-schema.md), so that the Phase 2 feature-build job knows exactly which columns to materialize.
36. As a **Phase 2 engineer**, I want inference signatures (input schema, output schema, model version pointer) documented per suite in `feature-store-schema.md` and cross-linked from `system-design.md`, so that the daily batch job at 08:00 UTC has a contract to implement against.
37. As an **ML engineer**, I want feature schema hashes recorded alongside models, so that training/inference drift is detectable.
38. As a **reviewer**, I want backtest precision/recall targets filled in (replacing `_TBD_` placeholders) in `system-design.md` before Phase 2 starts, so that promotion criteria are explicit.
39. As a **developer**, I want field names in feature specs to match the Return schema contract and ads parquet layout exactly, so that there is no naming drift between P1.5 and P2.

### Model serialization and metadata (P1.5-6)

40. As a **Phase 2 engineer**, I want serialized models (joblib/pickle) under a versioned directory layout (`models/seller_stage/{version}/`, etc.), so that inference loads artifacts predictably.
41. As an **ML engineer**, I want each artifact bundle to include `metadata.json` with train date, row count, feature schema hash, and metrics snapshot, so that ops can audit model lineage.
42. As a **CI system**, I want a smoke test that loads each serialized model and runs inference on a golden fixture, so that corrupt artifacts fail the build.
43. As a **product owner**, I want only models meeting backtest thresholds serialized as `promoted`, with sub-threshold runs marked `experimental`, so that Phase 2 does not accidentally deploy failing models.
44. As an **ML engineer**, I want training scripts to write metrics JSON alongside the model file, so that exit-gate review does not require re-running training.

### Phase 2 target architecture (P1.5-7)

45. As an **architect**, I want `docs/architecture/target-v2.md` published describing the Phase 2 inference pipeline (poll → feature build → batch infer → copy layer → UI swap), so that Phase 2 implementation has a shared blueprint.
46. As a **Phase 2 engineer**, I want target-v2 to reference the serialized model paths, inference schedule (08:00 UTC), and Ollama copy-layer placement, so that scheduling and deployment planning can begin before Phase 2 kickoff.
47. As a **product owner**, I want target-v2 to explicitly state what stays mock in Phase 1 vs what goes live in Phase 2, so that scope boundaries are clear for the eng team.
48. As an **architect**, I want target-v2 to document the `health_data_source: api | proxy | unavailable` contract for VP/AHR polling, so that Phase 2-1 does not assume unavailable API fields.
49. As a **reviewer**, I want target-v2 cross-linked from `EXECUTION.md`, `system-design.md`, and `map.md`, so that canonical docs stay consistent.

### Cross-cutting ML pipeline

50. As an **ML engineer**, I want separate runner-agnostic jobs for dataset assembly, feature build, train, and evaluate, so that Phase 2 swaps the scheduler without rewriting model code.
51. As a **developer**, I want all ML dependencies (scikit-learn, xgboost, pandas, pyarrow) pinned in requirements, so that training and inference environments match.
52. As a **reviewer**, I want no real TikTok API calls in any Phase 1.5 job, so that phase gating in `data-sources.md` is respected.
53. As a **developer**, I want unit and integration tests for data validation, feature computation, and inference on golden fixtures, so that ML code meets the ≥80% coverage bar for critical paths.
54. As an **ML engineer**, I want training logs structured (JSON) with run ID, dataset version, and hyperparameters, so that experiments are auditable without logging PII.
55. As a **product owner**, I want Phase 1 UX unchanged during Phase 1.5, so that the 100-seller Phase 1 test is not disrupted by half-wired ML in the UI.

### Rules baseline comparison

56. As an **ML engineer**, I want the Phase 1 rules router thresholds imported as a comparable baseline module, so that seller-stage ML evaluation uses the same input profiles as `web/src/lib/seller-stage-router/`.
57. As a **product owner**, I want a summary report showing rules vs ML agreement rate and disagreement cases on backtest, so that we can decide whether ML replaces rules entirely or hybrid routing is needed in Phase 2.

### Governance and exit gate

58. As a **product lead**, I want EXECUTION.md P1.5-1 through P1.5-7 slices traceable to implementation issues, so that governance links code to the plan.
59. As an **eng lead**, I want each PR cite the driving EXECUTION.md slice and data-source rows from `data-sources.md`, so that review gates pass.
60. As a **product lead**, I want numeric precision/recall thresholds agreed and recorded before the Phase 1.5 exit gate, so that promotion to Phase 2 is objective.

---

## Implementation Decisions

### Modules to build or modify (by responsibility)

| Module | Responsibility | Public interface (behavioral) |
|--------|----------------|------------------------------|
| **Backtest dataset assembler** | Build/version parquet datasets (orders, returns, labels, ads); synthetic generator; schema validation | `assembleBacktestDataset(config) → DatasetManifest`; `generateSyntheticLabels(seed) → labels.parquet` |
| **Feature builder** | Transform raw parquet → per-model feature matrices with documented column names | `buildSellerStageFeatures(manifest) → FeatureMatrix`; `buildAnomalyFeatures(manifest) → FeatureMatrix`; `buildAdFeatures(manifest) → FeatureMatrix` |
| **Seller stage trainer** | Train classifier; evaluate vs labeled stages and rules baseline | `trainSellerStage(features, labels) → TrainResult`; `compareToRulesBaseline(profiles) → ComparisonReport` |
| **Anomaly detector trainer** | Train buyer-behavior return detector (`item_swap`, `empty_return`) from Order/OrderItem/Return features only; per-class metrics | `trainAnomalyDetector(features, labels) → TrainResult`; `evaluateAnomalyClasses(y_true, y_pred) → ClassMetrics` |
| **Ad performance trainer** | Train regressor/classifier for ROAS and scale/cut ranking | `trainAdAnalyzer(features, labels) → TrainResult`; `evaluateRoasError(y_true, y_pred) → RoasMetrics` |
| **Model artifact publisher** | Serialize joblib + metadata.json; promotion gate on thresholds | `publishModel(suite, result, version) → ArtifactBundle`; `loadModel(suite, version) → Model` |
| **Feature spec documenter** | Update [`feature-store-schema.md`](../../data-models/feature-store-schema.md) with seller-stage and ad feature groups; cross-link inference signatures and filled thresholds in `system-design.md` | Script or manual PR updating canonical docs (P1.5-5) |
| **Target-v2 publisher** | Author `docs/architecture/target-v2.md` for Phase 2 pipeline | Markdown doc cross-linked from EXECUTION.md (P1.5-7) |

### Architectural decisions

- **Offline only:** No production inference, no Postgres writes for ML artifacts in Phase 1.5 (artifacts on disk under `models/`). No TikTok API calls.
- **Schema contract authority:** Entity shapes follow [`canonical-entities.md`](../../data-models/canonical-entities.md); feature names follow [`feature-store-schema.md`](../../data-models/feature-store-schema.md); return/ads field alignment index in `system-design.md` § Return schema contract; phase rows in `data-sources.md`. P1 mock TypeScript schemas gain P1.5 fields (`product_id`, `sku_id`, `return_type`, `return_condition`) in the dataset layer — aligned but not required to block training if parquet is self-contained.
- **Anomaly scope (ADR-011):** The anomaly detector is **buyer-behavior only** — classes `item_swap` and `empty_return` from Order, OrderItem, and Return data. No affiliate, creator, or commission features in training, labels, or inference. Policy signals (VP, disputes, withholding) are separate deterministic rules in Phase 2, not this model.
- **Rules baseline:** Seller-stage ML must be evaluated against the existing Phase 1 `classifySellerStage()` thresholds (ported or wrapped for Python backtest). ML replaces rules in Phase 2 only if backtest metrics and comparison report justify it.
- **Algorithm choices:** scikit-learn for seller stage classifier and anomaly detection (e.g., gradient boosting or random forest — chosen at implementation with reproducibility); xgboost or sklearn regressor for ad ROAS per `system-design.md` dependencies table. Pin versions at implementation.
- **Artifact layout:** Per `system-design.md`:
  ```
  models/
    seller_stage/{version}/model.joblib + metadata.json
    anomaly/{version}/model.joblib + metadata.json
    ad_performance/{version}/model.joblib + metadata.json
  ```
- **Backtest split:** Train on earlier historical window; evaluate on held-out Q4/Q1 (or synthetic equivalent with documented seed). Exact date boundaries recorded in dataset manifest.
- **Promotion gate:** Models failing documented precision/recall (or MAPE for ads) are serialized as `experimental` only — Phase 2 must not load them without Product sign-off.
- **Job separation:** Dataset → features → train → evaluate → publish as separate CLI entrypoints (runner-agnostic), matching Phase 2 scheduler swap design.
- **No UI changes:** Phase 1 mock UI unchanged. Phase 1.5 validates ML offline; Phase 2 swaps mock inference for real.
- **No Ollama in P1.5:** Copy layer remains rules-only templates from backtest signals (optional offline validation) — Ollama is Phase 2 per EXECUTION.md.

### Schema assumptions (backtest parquet)

Per `system-design.md` § Return schema contract and P1.5 parquet layout:

- **orders.parquet:** `order_id`, `shop_id`, `buyer_id`, `status`, `total_amount`, `created_at`, `line_items[]`
- **returns.parquet:** `return_id`, `order_id`, `buyer_id`, `product_id`, `sku_id`, `return_reason`, `return_type`, `return_condition`, `refund_amount`, `status`, `created_at`
- **labels.parquet:** `return_id`, `ground_truth_anomaly` (bool), `return_type` (`item_swap` | `empty_return` | `other`) — buyer-behavior labels only; no affiliate or creator labels
- **ads.parquet:** campaign/day grain with spend, impressions, clicks, conversions, ROAS (exact columns documented in P1.5-5)

**Not in anomaly backtest:** TikTok Affiliate data is absent from P1.5 backtest per [`data-sources.md`](../../architecture/data-sources.md) and ADR-011.

### Assumptions

- Historical TikTok Shop Q4/Q1 data may be unavailable; synthetic generator is the fallback path and must still produce valid labeled anomalies.
- Numeric precision/recall targets will be proposed during P1.5-5 and finalized before exit gate (replacing `_TBD_` in system-design.md).
- ML code lives under a new Python module tree (e.g., `src/jobs/ml/` — exact path chosen at P1.5-1 with MODULE.md added per [`map.md`](../../architecture/map.md) policy). No ML modules exist yet in the repo.
- Phase 1 rules router thresholds in `web/src/lib/seller-stage-router/thresholds.ts` are the authoritative baseline constants for comparison.
- Legacy `intelligence/scoring` livestream module is out of scope and slated for removal — do not extend it for seller-money ML.

---

## Testing Decisions

### What makes a good test

- Test **observable behavior** through public training/inference interfaces — not private sklearn internals.
- Prefer integration-style tests: load golden parquet fixture → build features → run inference → assert class/score on known rows.
- One behavior per test for data validation edge cases (schema mismatch, missing column, empty partition).
- Training tests use tiny fixtures and fixed seeds for determinism; full backtest runs are manual/CI nightly, not per-PR unit tests.

### Modules to test

| Module | Test style | Priority |
|--------|------------|----------|
| Backtest dataset assembler | Integration — schema validation, synthetic label distribution | High |
| Feature builder | Unit — column names match contract; buyer aggregates computed correctly | High |
| Seller stage trainer | Integration — golden profiles → expected stage; rules comparison report shape | High |
| Anomaly detector | Integration — labeled item_swap/empty_return/other cases score correctly; assert no affiliate/creator columns in feature matrix | High |
| Ad performance trainer | Integration — golden campaigns → scale/cut/hold with ROAS error bounds | High |
| Model artifact publisher | Integration — load published model, smoke inference, metadata fields present | High |
| Feature spec / target-v2 docs | Manual review + link check in CI if available | Medium |

### Prior art

- `tests/unit/test_scoring.py` — one-behavior-per-test pattern with golden fixtures (legacy module; pattern reusable).
- `web/src/__tests__/test_seller_stage_router.test.ts` — threshold boundary fixtures for rules baseline.
- Phase 1 mock schemas in `web/src/lib/mock-data/seller-personas/schemas.ts` — field naming reference for alignment.

---

## Out of Scope

Per [`EXECUTION.md`](../../../EXECUTION.md) — explicitly **not** in Phase 1.5:

- Production inference or daily batch jobs (Phase 2)
- Live TikTok API polling (Phase 2)
- Ollama copy layer (Phase 2)
- Swapping mock UI data for ML predictions (Phase 2)
- Real task execution / executor triggers (Phase 2)
- Postgres persistence of ML scores or feature tables (Phase 2)
- Anomaly ML beyond buyer-behavior returns — no affiliate signals, creator refunds, or commission fraud ([ADR-011](../../decisions/011-buyer-behavior-anomaly-scope.md))
- VP/AHR/withholding/dispute ML scoring (deterministic policy rules in Phase 2)
- Creator ↔ Shop matching (Phase 3+)
- Vendor scrapers (Kalodata / Shoplus — Phase 2.5+)
- Celery, Kafka, multi-node workers
- iOS/web UI changes for ML surfacing
- Extending legacy `intelligence/scoring` livestream module
- Seller Center scraping, buyer PII, unofficial streams (forbidden)

---

## Further Notes

### EXECUTION.md slice mapping

| Slice | PRD coverage |
|-------|----------------|
| P1.5-1 Backtest dataset assembly | User stories 1–10; Backtest dataset assembler |
| P1.5-2 Seller stage classifier | User stories 11–18, 56–57; Seller stage trainer |
| P1.5-3 Anomaly detector | User stories 19–27; Anomaly detector trainer |
| P1.5-4 Ad performance analyzer | User stories 28–34; Ad performance trainer |
| P1.5-5 Feature specs + inference signatures | User stories 35–39; Feature spec documenter |
| P1.5-6 Serialize models + metadata | User stories 40–44; Model artifact publisher |
| P1.5-7 Publish target-v2.md | User stories 45–49; Target-v2 publisher |

### Backtest metric targets (to fill during P1.5-5)

| Model | Metric | Target (initial proposal) |
|-------|--------|---------------------------|
| Seller stage classifier | Precision / recall (macro) | ≥ 0.80 / ≥ 0.75 (Product to confirm) |
| Anomaly detector | Precision / recall on `item_swap` + `empty_return` | ≥ 0.85 / ≥ 0.70 per class (Product to confirm) |
| Ad performance analyzer | ROAS MAPE on held-out window | ≤ 15% (Product to confirm) |

Replace placeholders in `system-design.md` when Product signs off during P1.5-5.

### Risks

| Risk | Mitigation |
|------|------------|
| No historical TikTok data | Synthetic generator with labeled anomalies; document synthetic ratio in metadata |
| Schema drift P1.5 → P2 | Single contract in system-design.md; validation tests on column names |
| Anomaly scope creep beyond buyer-behavior returns | ADR-011 enforced: feature builder rejects non Order/OrderItem/Return columns; code review + schema tests |
| Overfit on small backtest | Held-out window; cross-validation report; promotion gate |
| Legacy scoring module confusion | Do not extend `intelligence/scoring`; new seller-money ML module with MODULE.md |

### Rollout

- Internal training runs → threshold sign-off → serialize promoted artifacts → publish target-v2 → Phase 1.5 exit gate review with Product lead.
- No production deployment in Phase 1.5; artifacts consumed starting Phase 2.

### Observability

- Structured training logs: `run_id`, `dataset_version`, `suite`, `metrics`, `duration_ms` — no PII.
- `metadata.json` per model for lineage audit.

### Follow-ups (Phase 2)

- Wire daily batch inference at 08:00 UTC using published inference signatures.
- Map TikTok API order/return fields to schema contract (P2-1).
- Swap mock UI tasks for ML + Ollama copy output (P2-4).
- Enable live task execution behind approval flow (P2-5).

---

## Deep modules summary (for to-issues)

1. **Backtest dataset assembler** — parquet + synthetic + schema validation
2. **Feature builder** — per-suite feature matrices aligned to contract
3. **Seller stage trainer** — train + rules baseline comparison
4. **Anomaly detector trainer** — buyer-behavior returns only (`item_swap`, `empty_return`); no affiliate inputs
5. **Ad performance trainer** — ROAS + scale/cut ranking
6. **Model artifact publisher** — serialize + metadata + promotion gate
7. **Feature spec documenter** — system-design.md thresholds + signatures
8. **Target-v2 publisher** — Phase 2 architecture doc
