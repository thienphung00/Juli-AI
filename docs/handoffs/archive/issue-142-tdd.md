# Handoff: tdd → review — Issue #142

## Issue

- **#142** — Feature specs, inference signatures, threshold sign-off

## Branch

- `feature/issue-142-feature-specs`

## Changes summary

- **New:** `tests/unit/test_feature_store_docs.py` — 8 AC-mapped doc contract tests
- **Modified:** `docs/data-models/feature-store-schema.md` — Group D (seller stage), Group E (ad), schema hash table, three inference signatures
- **Modified:** `docs/system-design.md` — promotion targets filled, backtest reference metrics, inference signature cross-links
- **Migrations:** none

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_feature_store_documents_all_three_feature_groups` | All column tuples from schema.py documented |
| `test_inference_signatures_document_input_and_output_fields` | Three suites with input/output + model paths |
| `test_feature_schema_hashes_match_artifact_metadata_contract` | Hashes match `feature_schema_hash()` |
| `test_system_design_ml_targets_have_no_tbd_placeholders` | No `_TBD_`; promotion targets present |
| `test_system_design_cross_links_inference_signatures` | Cross-link to feature-store-schema.md |
| `test_anomaly_group_references_adr_011_scope` | ADR-011 in Group A |
| `test_ad_features_align_with_ads_parquet_layout` | ads.parquet column alignment |
| `test_return_schema_fields_referenced_in_anomaly_features` | Return contract fields referenced |

## Test results

- All 8 doc tests passing
- Full unit suite green

## Acceptance criteria status

- [x] Seller-stage, anomaly, ad feature groups documented — schema.py column match test
- [x] Inference signature per suite with cross-link from system-design.md
- [x] system-design.md ML targets filled (no `_TBD_`)
- [x] Feature schema hashes match #141 metadata contract
- [x] Field names align with Return schema and ads parquet
- [ ] **HITL:** Product lead confirms threshold numbers in PR before close
- [x] ADR-011 reflected in Group A descriptions

## Notes for reviewer

- Promotion targets: precision/recall ≥ 0.50, ROAS MAPE ≤ 50% (from `thresholds.py`)
- Backtest reference run (seed 142) documented; empty_return class sparse on synthetic data
- Docs-only issue — no production code changes
