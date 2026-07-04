# Handoff: tdd → review — Issue #141

## Issue

- **#141** — Serialize models + metadata + smoke tests

## Branch

- `feature/issue-141-model-artifacts`

## Changes summary

- New: `src/modules/ml/artifacts/*` (types, schema, thresholds, promotion, publish, load, smoke, MODULE.md)
- New: `tests/unit/test_model_artifacts.py`
- New: `docs/decisions/018-phase-15-model-artifacts.md`
- New: `docs/handoffs/issue-141-focus.md`
- Modified: `docs/architecture/map.md`
- Modified: `.gitignore` (ignore `models/`)

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_publish_creates_expected_directory_layout` | models/{suite}/{version}/model.joblib + metadata.json |
| `test_metadata_includes_required_fields` | train_date, row_count, feature_schema_hash, metrics, promotion_status |
| `test_load_model_roundtrip_and_smoke_inference` | publish_model / load_model + smoke on golden fixture |
| `test_corrupt_model_file_raises_clear_error` | Corrupt joblib → ArtifactLoadError with clear message |
| `test_sub_threshold_metrics_marked_experimental` | Promotion gate returns experimental |
| `test_meeting_threshold_metrics_marked_promoted` | Promotion gate returns promoted |
| `test_sub_threshold_publish_writes_experimental_status` | Published metadata promotion_status experimental |
| `test_metrics_json_copied_to_artifact_directory` | metrics.json copied alongside model |
| `test_all_three_suites_publish_load_and_smoke` | All three suites train → publish → smoke |
| `test_publish_model_has_no_postgres_persistence` | No Postgres imports |

## Test results

- All 10 new tests passing
- Full ML unit suite passing

## Acceptance criteria status

- [x] Directory layout matches system-design.md — `test_publish_creates_expected_directory_layout`
- [x] metadata.json required fields — `test_metadata_includes_required_fields`
- [x] publish_model / load_model + smoke — `test_load_model_roundtrip_and_smoke_inference`, `test_all_three_suites_publish_load_and_smoke`
- [x] Corrupt model clear error — `test_corrupt_model_file_raises_clear_error`
- [x] Sub-threshold → experimental — `test_sub_threshold_*`
- [x] Metrics JSON alongside model — `test_metrics_json_copied_to_artifact_directory`
- [x] No Postgres persistence — `test_publish_model_has_no_postgres_persistence`

## Notes for reviewer

- Promotion thresholds provisional in `thresholds.py` until #142 Product sign-off
- Python API uses snake_case (`publish_model` / `load_model`); PRD camelCase maps to these
- `models/` gitignored; CI smoke runs in pytest temp dirs
