# Handoff: focus → tdd — Issue #140

## Issue

- **#140** — Ad performance analyzer — train + backtest
- **EXECUTION slice:** P1.5-4
- **Parent:** #135 · **Blocked by:** #137 (complete)

## Acceptance criteria

- CLI train entrypoint runs on #136 ads parquet split; writes metrics JSON including ROAS MAPE on held-out window
- Model outputs discrete action: `scale | cut | hold` plus confidence per campaign
- Account-level baseline features included (average ROAS, spend velocity)
- Integration test: golden scale candidate campaign → `scale` action with confidence above hold threshold
- Integration test: golden cut candidate campaign → `cut` action
- Integration test: sparse-history campaign → `hold` with low confidence (does not raise)
- No TikTok API calls

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.5-4), `docs/system-design.md` § ML models, `docs/architecture/map.md` |
| Feature builder | `src/modules/ml/features/ad.py`, `schema.py`, `MODULE.md` |
| Dataset contract | `src/modules/ml/dataset/assembler.py`, `ads.parquet` schema |
| Prior art | `src/modules/ml/seller_stage/*`, `src/modules/ml/anomaly/*`, `docs/handoffs/issue-137-ship.md`, `issue-139-ship.md` |
| Decisions | `docs/decisions/013-phase-15-ml-module-tree.md`, `014-phase-15-feature-builder.md` |

## Standards applied

- Reliability — fixed random seed; sparse-history graceful hold; fail-fast on empty training frame
- Security — no PII in training logs; structured JSON only
- Observability — structured JSON training logs (ROAS MAPE, action distribution)
- Maintainability — runner-agnostic plain Python; MODULE.md per `map.md`

## Plugin skills & MCP

- None required (offline sklearn on parquet)
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** types → thresholds → rules → fixtures → inference → train → cli → tests → map.md → ADR

### New files

| File | Purpose |
|------|---------|
| `src/modules/ml/ad_performance/types.py` | `TrainResult`, `InferenceResult`, `AdPerformanceModel` |
| `src/modules/ml/ad_performance/thresholds.py` | action thresholds, sparse-history constants |
| `src/modules/ml/ad_performance/rules.py` | `derive_ad_action(features)` for training labels |
| `src/modules/ml/ad_performance/fixtures.py` | Golden scale / cut / sparse campaign profiles |
| `src/modules/ml/ad_performance/inference.py` | `predict_ad_action(model, features)` |
| `src/modules/ml/ad_performance/train.py` | `train_ad_performance(manifest, output_dir)` |
| `src/modules/ml/ad_performance/cli.py` | `train-ad` CLI |
| `src/modules/ml/ad_performance/MODULE.md` | Public interface + inference schema |
| `tests/unit/test_ad_performance_trainer.py` | AC-mapped integration tests |
| `docs/decisions/017-phase-15-ad-performance-trainer.md` | ADR for new module |

### Modified files

| File | Change |
|------|--------|
| `docs/architecture/map.md` | Register `src/modules/ml/ad_performance` |

### Key patterns

- Training frame from `build_ad_features(manifest)` on campaign/day grain
- ROAS regressor (`RandomForestRegressor`) + action classifier (`RandomForestClassifier(class_weight="balanced")`)
- Action labels derived from ROAS vs `account_avg_roas_30d` rules (scale/cut/hold)
- Held-out eval split by ad `date` vs manifest `split_boundaries.train_end`
- Metrics JSON: `roas_mape` on eval window, action distribution, class imbalance strategy
- Sparse history: impressions/clicks/conversions below threshold → `hold` with low confidence, no raise
- Golden fixture augmentation in training for stable integration tests on small datasets

### Tests (TDD)

1. RED: `test_golden_scale_candidate_returns_scale_with_high_confidence`
2. RED: `test_golden_cut_candidate_returns_cut`
3. RED: `test_sparse_history_campaign_returns_hold_low_confidence`
4. RED: `test_train_writes_roas_mape_metrics_json`
5. RED: `test_inference_output_schema_documented`
6. GREEN: implement module incrementally

Run: `pytest tests/unit/test_ad_performance_trainer.py -v`

## DO NOT touch

- `ml/seller_stage`, `ml/anomaly` — parallel shipped modules
- `web/` UI — no changes per AC
- Model serialization (#141)
- TikTok API / Postgres paths
