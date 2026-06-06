# Handoff: focus → tdd — Issue #143

## Issue

- **#143** — Publish Phase 2 target architecture (target-v2.md)
- **EXECUTION slice:** P1.5-7
- **Parent:** #135 · **Blocked by:** #141, #142 (both complete)

## Acceptance criteria

- `docs/architecture/target-v2.md` exists with end-to-end Phase 2 flow diagram or equivalent
- Documents what stays mock in Phase 1 vs goes live in Phase 2
- References `models/` artifact paths, 08:00 UTC inference schedule, Ollama placement after inference
- Documents `health_data_source` contract; no assumption that VP/AHR API fields are exposed
- Anomaly ML section states buyer-behavior only (`item_swap`, `empty_return`); policy signals separate
- Cross-links added in `EXECUTION.md`, `system-design.md`, and `map.md` pointing to `target-v2.md`
- Manual review: no Seller Center scraping, no buyer PII, no Celery/Kafka in Phase 2 scope

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.5-7, Phase 2 slices), `docs/system-design.md` § end-to-end flow |
| Prior art | `docs/handoffs/issue-141-ship.md`, `issue-142-ship.md` |
| Model artifacts | `docs/data-models/feature-store-schema.md` § Inference signatures, ADR-018 |
| Health contract | `docs/data-models/canonical-entities.md` § Shop, `data-sources.md` |
| Anomaly scope | ADR-011, `feature-store-schema.md` Group A |
| Platform policy | ADR-008, ADR-009, `tiktok_platform/seller/implementation-hooks.md` |

## Standards applied

- Maintainability — docs-only; test-locked contract like #142
- Security — explicit forbidden list (no scraping, no buyer PII)

## Plugin skills & MCP

- None required (canonical docs only)

## Implementation approach

**Dependency order:** doc contract tests (RED) → `target-v2.md` → cross-links in EXECUTION/system-design/map → GREEN

### New files

| File | Purpose |
|------|---------|
| `docs/architecture/target-v2.md` | Phase 2 target architecture (primary deliverable) |
| `tests/unit/test_target_v2_docs.py` | AC-mapped doc contract tests |

### Modified files

| File | Change |
|------|--------|
| `docs/system-design.md` | Convert `architecture/target-v2.md` reference to markdown link |
| `docs/architecture/map.md` | Add target architecture cross-link section |
| `EXECUTION.md` | Mark P1.5-7 complete; ensure link resolves |

### Key patterns

- Consolidate existing Phase 2 narrative from `system-design.md` into authoritative `target-v2.md`
- Reference #141 artifact layout (`models/{suite}/{version}/`) and #142 inference signatures
- Mermaid or ASCII flow diagram for end-to-end pipeline
- Phase 1 vs Phase 2 comparison table (mock vs live per subsystem)

### Tests (TDD)

1. RED: `test_target_v2_exists_with_phase2_flow`
2. RED: `test_target_v2_phase1_mock_vs_phase2_live`
3. RED: `test_target_v2_references_model_paths_and_schedule`
4. RED: `test_target_v2_documents_health_data_source_contract`
5. RED: `test_target_v2_anomaly_buyer_behavior_scope`
6. RED: `test_cross_links_point_to_target_v2`
7. RED: `test_target_v2_excludes_forbidden_scope`
8. GREEN: write `target-v2.md` + cross-links

Run: `pytest tests/unit/test_target_v2_docs.py -v`

## DO NOT touch

- Trainer modules, artifact publisher, UI, TikTok API client
- No Celery/Kafka/Celery references in Phase 2 scope doc
