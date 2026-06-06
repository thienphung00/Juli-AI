# ADR 019: Phase 2 Target Architecture Document

## Status
Accepted

## Context

Phase 1.5 delivered offline trainers (#138–#140), model artifact serialization (#141),
and canonical feature-store / inference signatures (#142). Phase 2 requires a single
authoritative document describing the live inference pipeline: TikTok API poll → ETL →
canonical entities → feature build → batch inference → copy layer → UI → executor.

`docs/system-design.md` already contained a draft end-to-end flow, but it mixed
subsystem detail with pipeline orchestration. `docs/architecture/map.md` needed a
cross-link entry so agents and engineers can find the Phase 2 pipeline authority
without reading the full system-design doc.

Issue #143 (P1.5-7) is the exit gate for MVP 1.5 documentation before Phase 2
implementation slices begin.

## Decision

- **We will:** Publish `docs/architecture/target-v2.md` as the **Phase 2 pipeline
  authority** — daily schedule (06:00–08:00 UTC), model artifact paths, copy layer
  (Ollama + rules fallback), `health_data_source` contract, and buyer-behavior-only
  anomaly scope (ADR-011).
- **We will:** Add cross-links from `EXECUTION.md`, `system-design.md`, and
  `map.md` pointing to `target-v2.md`.
- **We will:** Lock acceptance criteria with doc contract tests in
  `tests/unit/test_target_v2_docs.py`.
- **We will not:** Introduce Celery, Kafka, Seller Center scraping, or buyer PII
  collection in Phase 2 scope.
- **We will not:** Assume VP/AHR API fields are exposed — document
  `health_data_source: api | proxy | unavailable` per ADR-009.

## Rationale

- Consolidates scattered Phase 2 narrative into one navigable doc for implementation
  agents and reviewers.
- Doc contract tests prevent regression on forbidden scope and critical contracts
  (inference schedule, model paths, anomaly scope).
- `system-design.md` remains subsystem authority; `target-v2.md` owns orchestration
  and Phase 1 mock vs Phase 2 live comparison.

## Consequences

- `map.md` gains a target-architecture cross-link section (triggers architectural
  change detection in CI validate gates).
- Phase 2 slices (P2-1 onward) reference `target-v2.md` for schedule and contracts.
- No runtime code changes — documentation-only ADR.
