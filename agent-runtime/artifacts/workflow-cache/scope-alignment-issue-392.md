# Scope alignment — Issue #392

**Parent:** #278  
**Slice:** P2-A2 (webhook receiver / catalog surface)  
**Companion:** `issue-context-cache-392.json`

## Decision summary

| Topic | Decision |
|-------|----------|
| Part A raw archive | Build `webhook_raw_events` |
| Part B domain tables | Do not build (ETL already live) |
| S3 archival | Defer (Phase 3 / ADR-012) |
| Automated pruning | Defer; index `received_at` now |
| PII | Denylist redaction before store; skip body on malformed JSON |
| Catalog | Zero changes to `webhook_catalog.py` |

## Authority confirmations

- Child AC wins for storage/audit behaviors.
- Parent epic deferrals unchanged (no new infra, no ML, no web/ios).
- Related #382 remains Partner Center confirmation — out of scope here.
