# Handoff: focus → tdd — Issue #141

## Issue

- **#141** — Serialize models + metadata + smoke tests
- **EXECUTION slice:** P1.5-6
- **Parent:** #135 · **Blocked by:** #138, #139, #140 (all complete)

## Acceptance criteria

- Directory layout: `models/{seller_stage,anomaly,ad_performance}/{version}/model.joblib + metadata.json`
- `metadata.json` includes: `train_date`, `row_count`, `feature_schema_hash`, `metrics`, `promotion_status` (`promoted` | `experimental`)
- `publish_model` / `load_model` public interface; load + infer on golden fixture in smoke test
- Integration test: corrupt model file fails smoke test with clear error
- Integration test: sub-threshold run serializes as `experimental` only (not `promoted`)
- Metrics JSON written alongside model file during publish (no re-run required for exit-gate review)
- No Postgres persistence

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.5-6), `docs/architecture/system-design.md` § ML outputs, `docs/architecture/map.md` |
| Trainers | `src/modules/ml/seller_stage/*`, `anomaly/*`, `ad_performance/*` — all return `TrainResult` with `model`, `metrics`, `metrics_path` |
| Feature schema | `src/modules/ml/features/schema.py` — column tuples for schema hash |
| Golden fixtures | `seller_stage/fixtures.py`, `anomaly/fixtures.py`, `ad_performance/fixtures.py` |
| Inference | `predict_seller_stage`, `predict_anomaly`, `predict_ad_action` |
| Prior art | `docs/handoffs/issue-138-ship.md`, `issue-139-ship.md`, `issue-140-ship.md` |

## Standards applied

- Reliability — fail-fast on corrupt artifacts with clear errors; smoke test validates load + infer path
- Security — no PII in metadata; disk-only artifacts (no Postgres)
- Maintainability — runner-agnostic plain Python; MODULE.md per `map.md`
- Observability — metadata snapshot for lineage audit

## Plugin skills & MCP

- None required (offline joblib on local disk)
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** types → schema hash → promotion thresholds → publish → load → smoke → tests → map.md → ADR

### New files

| File | Purpose |
|------|---------|
| `src/modules/ml/artifacts/types.py` | `ModelSuite`, `ArtifactBundle`, `PromotionStatus`, `LoadedModel` |
| `src/modules/ml/artifacts/schema.py` | `feature_schema_hash(suite)` from authoritative column tuples |
| `src/modules/ml/artifacts/thresholds.py` | Provisional backtest promotion thresholds (finalized in #142) |
| `src/modules/ml/artifacts/promotion.py` | `evaluate_promotion_status(suite, metrics)` |
| `src/modules/ml/artifacts/publish.py` | `publish_model(...)` — joblib + metadata.json + metrics copy |
| `src/modules/ml/artifacts/load.py` | `load_model(suite, version)` |
| `src/modules/ml/artifacts/smoke.py` | `run_smoke_test(suite, version)` — golden fixture inference |
| `src/modules/ml/artifacts/exceptions.py` | `ArtifactLoadError`, `ArtifactPublishError` |
| `src/modules/ml/artifacts/MODULE.md` | Public interface |
| `tests/unit/test_model_artifacts.py` | AC-mapped integration tests |
| `docs/adr/018-phase-15-model-artifacts.md` | ADR for artifact publisher |

### Modified files

| File | Change |
|------|--------|
| `docs/architecture/map.md` | Register `src/modules/ml/artifacts` |
| `.gitignore` | Ignore `models/` runtime artifacts |

### Key patterns

- `publish_model` writes `models/{suite}/{version}/model.joblib`, `metadata.json`, copies `metrics.json` from training output
- Promotion gate compares metrics against provisional thresholds in `thresholds.py`; sub-threshold → `experimental` only
- Schema hash = SHA-256 prefix of joined feature column names from `features/schema.py`
- Smoke test loads artifact and runs suite-specific golden fixture inference (no crash, valid output shape)
- Python public API uses `publish_model` / `load_model` (snake_case); PRD camelCase maps to these

### Tests (TDD)

1. RED: `test_publish_creates_expected_directory_layout`
2. RED: `test_metadata_includes_required_fields`
3. RED: `test_load_model_roundtrip_and_smoke_inference`
4. RED: `test_corrupt_model_file_raises_clear_error`
5. RED: `test_sub_threshold_metrics_marked_experimental`
6. RED: `test_metrics_json_copied_to_artifact_directory`
7. GREEN: implement module incrementally

Run: `pytest tests/unit/test_model_artifacts.py -v`

## DO NOT touch

- Trainer modules beyond optional doc cross-links — serialization is additive
- `web/` UI, TikTok API, Postgres paths
- Threshold sign-off in `system-design.md` (#142 HITL)
