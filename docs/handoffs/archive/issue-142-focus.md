# Handoff: focus → tdd — Issue #142

## Issue

- **#142** — Feature specs, inference signatures, threshold sign-off
- **EXECUTION slice:** P1.5-5
- **Parent:** #135 · **Blocked by:** #138, #139, #140 (all complete)

## Acceptance criteria

- Seller-stage, anomaly (Group A complete), and ad feature groups documented in `feature-store-schema.md` with exact field names matching #137 output
- Inference signature per suite: input schema, output schema, model version pointer — cross-linked from `system-design.md`
- `system-design.md` § ML models targets filled (no `_TBD_` for seller stage, anomaly per-class, ad MAPE)
- Feature schema hashes in docs match `metadata.json` from #141 promoted artifacts
- Field names align with Return schema contract and ads parquet layout (no P1.5 → P2 drift)
- **HITL:** Product lead confirms threshold numbers in PR or linked comment before close
- Manual review: doc links resolve; ADR-011 anomaly scope reflected in feature group descriptions

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.5-5), `docs/architecture/system-design.md` § ML models + Return schema |
| Feature schema | `src/modules/ml/features/schema.py` — authoritative column tuples |
| Schema hashes | `src/modules/ml/artifacts/schema.py` — `feature_schema_hash(suite)` |
| Promotion thresholds | `src/modules/ml/artifacts/thresholds.py` — provisional gates (Product sign-off) |
| Inference | `seller_stage/inference.py`, `anomaly/inference.py`, `ad_performance/inference.py` |
| Parquet contracts | `src/modules/ml/dataset/schema.py` — `ADS_COLUMNS`, `RETURNS_COLUMNS` |
| Prior art | `docs/handoffs/issue-137-ship.md`, `issue-141-ship.md` |

## Standards applied

- Maintainability — docs are single source of truth; tests lock schema.py ↔ docs alignment
- Reliability — no P1.5 → P2 field drift; hashes detect training/inference mismatch

## Plugin skills & MCP

- None required (canonical docs only)

## Implementation approach

**Dependency order:** doc validation tests (RED) → feature-store-schema.md (seller + ad groups + 3 inference signatures) → system-design.md (thresholds + cross-links) → GREEN

### New files

| File | Purpose |
|------|---------|
| `tests/unit/test_feature_store_docs.py` | AC-mapped doc contract tests |

### Modified files

| File | Change |
|------|--------|
| `docs/api/data-models/feature-store-schema.md` | Group D (seller stage), Group E (ad), three inference signatures, schema hash table |
| `docs/architecture/system-design.md` | Fill ML promotion targets, cross-link inference signatures, backtest reference metrics |

### Key patterns

- Feature names = `features/schema.py` tuples (already tested in #137 for anomaly)
- Schema hashes: seller `a9752c5a8d1f5e9f`, anomaly `71b21e6d94257389`, ad `1287eca5ccbae7fe`
- Promotion targets from `thresholds.py`: precision/recall ≥ 0.5, ROAS MAPE ≤ 50%
- HITL: PR includes Product sign-off checklist for threshold numbers

### Tests (TDD)

1. RED: `test_feature_store_documents_all_three_feature_groups`
2. RED: `test_inference_signatures_document_input_and_output_fields`
3. RED: `test_feature_schema_hashes_match_artifact_metadata_contract`
4. RED: `test_system_design_ml_targets_have_no_tbd_placeholders`
5. RED: `test_anomaly_group_references_adr_011_scope`
6. GREEN: update canonical docs

Run: `pytest tests/unit/test_feature_store_docs.py -v`

## DO NOT touch

- Trainer modules, artifact publisher — docs-only issue
- `web/` UI, TikTok API, Postgres paths
