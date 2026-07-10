# Handoff: tdd → review — Issue #143

## Issue

- **#143** — Publish Phase 2 target architecture (target-v2.md)

## Branch

- `feature/issue-143-target-v2`

## Changes summary

- New: `docs/architecture/target-v2.md`, `tests/unit/test_target_v2_docs.py`, `docs/handoffs/issue-143-focus.md`
- Modified: `EXECUTION.md` (P1.5-7 + exit gate checked), `docs/architecture/system-design.md` (markdown link), `docs/architecture/map.md` (target architecture section)
- Migrations: none
- MODULE.md added: none

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_target_v2_exists_with_phase2_flow` | AC: end-to-end Phase 2 flow diagram |
| `test_target_v2_phase1_mock_vs_phase2_live` | AC: Phase 1 mock vs Phase 2 live |
| `test_target_v2_references_model_paths_and_schedule` | AC: models/ paths, 08:00 UTC, Ollama, feature build window |
| `test_target_v2_documents_health_data_source_contract` | AC: health_data_source contract, VP/AHR not assumed |
| `test_target_v2_anomaly_buyer_behavior_scope` | AC: item_swap/empty_return only, policy separate |
| `test_target_v2_references_inference_signatures_from_142` | AC: #142 inference signature cross-ref |
| `test_cross_links_point_to_target_v2` | AC: cross-links in EXECUTION, system-design, map |
| `test_target_v2_excludes_forbidden_scope` | AC: no scraping, PII, Celery/Kafka |

## Test results

- All 8 tests passing
- No pre-existing tests broken

## Acceptance criteria status

- [x] `target-v2.md` exists with end-to-end Phase 2 flow diagram — mermaid + ASCII
- [x] Phase 1 mock vs Phase 2 live — comparison table
- [x] models/ paths, 08:00 UTC, Ollama after inference — daily schedule + copy layer section
- [x] health_data_source contract — tier table, P2-1 gate, not exposed disclaimer
- [x] Anomaly buyer-behavior only — ADR-011 section, policy signals separate
- [x] Cross-links in EXECUTION, system-design, map
- [x] Manual review: forbidden scope table (no Seller Center scraping, buyer PII, Celery/Kafka)

## Notes for reviewer

- Docs-only issue; consolidates existing Phase 2 narrative from system-design.md into authoritative target-v2.md
- EXECUTION P1.5-7 and exit gate checkbox marked complete
