# Issue #602: Phase 3.5-A2: CDP Batch layer — staggered reconcile & dual budgets
State: OPEN
Labels: enhancement, PRD

## Assumptions

- **A0 Foundation ([#598](https://github.com/thienphung00/Juli-AI/issues/598)) must exit first** — medallion schemas and serving gold contract live.
- Architect split locked in [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md): this PRD is the **Batch layer** (OLAP-shaped throughput path).
- **A1 Speed** may run **in parallel** with A2 after A0; A2 does **not** block 3.5-B ([#599](https://github.com/thienphung00/Juli-AI/issues/599)) or Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600)).
- **Read-replica isolation** for cold-start fleet scale is **Phase 3 / 3.5-C** (ADR-050 C2) — not an A2 exit requirement.
- Grill handoff ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md), [ADR-029](docs/adr/029-phase-2.9-analytics-historical-backfill.md), [ADR-046](docs/adr/046-cdp-medallion-physical-model.md)) authoritative; no re-interview.
- **Fujiwa Mock reference shop** for scheduler prove-out; multi-tenant OAuth out of scope.
- Default tests: Daily staggered reconcile scheduler, dual budget guards, partition resume, batch orchestrator writing same gold.

## Problem Statement

The **Speed layer (A1)** drives event-driven freshness for the Mock reference shop, but at fleet scale webhooks miss, Partner gaps appear, and historical windows need resumable throughput jobs. Without an **OLAP-shaped Batch layer**, multi-shop gap reconciliation would either overload the speed path (poll-heavy per webhook) or leave envelopes stale for days.

After A0 establishes medallion schemas, the platform needs **daily staggered per-shop reconcile**, checkpoint-resumable partition backfill, and explicit **two budgets** — Partner API and Postgres I/O — so batch jobs write the **same** `gold.kpi_envelopes` without forking KPI formulas or serving tables.

## Solution

Ship **Phase 3.5-A2 Batch** — the **Batch layer** on medallion foundation:

**Scheduled shop-scoped reconcile / partition jobs → bounded Partner fetch → Shared Compute (bronze→silver→gold) → same `gold.kpi_envelopes` → Redis read-through**

Key themes:
1. **Daily staggered per-shop reconcile:** Fleet backstop — one shop window per day, staggered across the day (ADR-048). Polling remains gap reconciliation, not primary freshness (Speed layer owns that).
2. **Dual budgets (locked):**
   - **Partner API budget** — rate limits, call caps per credential+endpoint; scheduler respects backoff and daily quotas.
   - **Postgres I/O budget** — throttle bronze append volume and silver promotion batch size to protect Supabase Postgres.
3. **Same gold writes:** Batch jobs use Shared Compute Orchestrator stages — no separate batch-only serving table or KPI formula fork.
4. **Cold-start checkpoints (when needed):** Bronze append for backfill/reconcile pages with `ops.*` cursors; full cold-start fleet engine remains **3.5-C C2** (ADR-050) — A2 implements checkpoint pattern and scheduler hooks, not self-serve OAuth fleet.
5. **Partition-resumable jobs:** Reuse 2.9 partition patterns (ADR-029) for analytics backfill windows where batch reconcile requires historical pages.
6. **Orthogonal to Speed:** Batch heals gaps Speed misses; does not replace webhook-first policy.

**Mock mode:** Fujiwa may participate in staggered schedule for prove-out; Sign-in disabled.

## User Stories

1. As a **platform operator**, I want **daily staggered per-shop reconcile** so that multi-shop gap healing does not require global hourly full polls.
2. As a **platform operator**, I want each shop's reconcile window assigned deterministically across the day, so that Partner API load is spread evenly.
3. As a **platform operator**, I want batch reconcile jobs to write the **same** `gold.kpi_envelopes` as speed jobs, so that Analytics never reads two competing serving sources.
4. As a **platform operator**, I want **Partner API budget** enforcement on batch schedulers, so that fleet reconcile cannot exhaust TikTok rate limits.
5. As a **platform operator**, I want **Postgres I/O budget** guards on bronze append and silver promotion, so that batch throughput does not overwhelm Supabase.
6. As a **platform operator**, I want batch jobs resumable from `ops.*` checkpoints, so that partial failures do not restart entire shop histories.
7. As a **platform operator**, I want reconcile bronze snapshots append-only, so that batch ingest preserves audit trail per ADR-046.
8. As a **prospective seller**, I want Demo Analytics to heal stale KPIs overnight when webhooks missed, so that the reference shop does not show multi-day lag (when batch runs for that shop).
9. As a **backend engineer**, I want batch and speed jobs to share the Shared Compute Orchestrator interface, so that KPI precompute logic is not duplicated.
10. As a **backend engineer**, I want partition cursors in `ops.*`, so that 2.9 backfill patterns extend cleanly into batch reconcile.
11. As a **backend engineer**, I want scheduler assignment logic unit-tested without live Partner calls, so that stagger math is CI-stable.
12. As a **backend engineer**, I want budget exhaustion to defer jobs with logged reason codes, so that on-call can distinguish API vs I/O throttling.
13. As a **data platform owner**, I want cold-start bronze pages gated behind explicit gap detection, so that A2 does not pull full 3.5-C fleet scope prematurely.
14. As a **data platform owner**, I want read-replica isolation documented as Phase 3 / 3.5-C follow-up, so that A2 exit is not blocked on replica infra.
15. As a **product owner**, I want **3.5-B Decisions** unblocked by **A1 Speed only**, so that batch fleet work does not delay Decision wire.
16. As a **product owner**, I want batch layer explicitly OLAP-shaped, so that speed path stays event-driven and low-latency.
17. As a **QA engineer**, I want tests proving batch scheduler assigns shops without collision and respects budget caps, so that fleet regressions are caught in CI.
18. As a **QA engineer**, I want integration tests that batch orchestrator writes gold envelopes with same `payload.kpis` shape as speed path, so that serving contract stays unified.
19. As a **security reviewer**, I want batch jobs service-role only on bronze/silver/ops, so that scheduled work does not widen client exposure.
20. As an **on-call engineer**, I want batch job completion and budget drop metrics logged, so that stale envelope incidents trace to speed vs batch path.
21. As a **future multi-tenant engineer**, I want staggered reconcile designed for ~100 shops, so that Phase 3 Sign-in reuses the same backstop.
22. As a **Meta/release gate owner**, I want scheduler deploy changes release-evidence when they affect public Demo freshness SLAs.
23. As a **platform operator**, I want batch reconcile to skip shops with active speed compute mutex, so that speed and batch do not corrupt the same shop concurrently.
24. As a **backend engineer**, I want finance unsettled/statements and video list analytics sequenced as batch-friendly P1 fetches where speed path deferred them.
25. As a **visitor on Mock Demo**, I want Fake Refresh to still not trigger batch or speed recompute, so that public traffic cannot force fleet jobs.
26. As a **product owner**, I want no columnar warehouse required for A2 exit, so that Postgres medallion remains the batch compute store.
27. As a **platform operator**, I want hourly Fujiwa exception to remain in **A1 Speed**, so that A2 does not duplicate single-tenant hourly poll.
28. As a **data platform owner**, I want `analytics_backfill_partitions` in `ops.*`, so that partition state migrates off legacy `public` over time.
29. As a **backend engineer**, I want batch fetch plans broader than targeted speed plans but still bounded, so that reconcile closes gaps without full poll stacks.
30. As a **QA engineer**, I want negative tests when Partner budget exhausted — job deferred, last-good gold served — so that degradation matches speed path behavior.

## Implementation Decisions

- **Phase boundary:** A2 = Batch layer only ([ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md)); depends on **A0**; parallel **A1** after A0 OK.
- **Architecture:** Batch on medallion ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md)); staggered reconcile policy ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)); partition patterns ([ADR-029](docs/adr/029-phase-2.9-analytics-historical-backfill.md)).
- **Lambda layer:** Batch (OLAP-shaped) writes **Serving layer** `gold.kpi_envelopes` — same as Speed; no warehouse.
- **Dual budgets:** Partner API (calls/rate) + Postgres I/O (write/read pressure) — both must be configurable and observable.
- **Scheduler:** Daily stagger assigns shop_id → window; no global hourly full poll at fleet scale.
- **Concurrency:** Shop-scoped mutex with speed jobs; batch defers if speed compute active.
- **Cold-start:** Checkpoint bronze + ops cursors in A2 when gap requires; full self-serve cold-start engine = 3.5-C C2.
- **Isolation:** Read replica for batch read pressure = Phase 3 / 3.5-C — document, do not require for A2 exit.
- **Credential model:** Mock production_read Fujiwa; OAuth out of scope.

## Testing Decisions

- Scheduler assignment logic (stagger, no collision); budget cap enforcement (Partner + I/O); partition resume from ops checkpoint.
- Integration: batch job → orchestrator → gold envelope same shape as speed fixture path.
- Prior art: analytics backfill partition tests, reconcile scheduler stubs from 2.9/2.10 intent.
- CI: no live Partner in PR-safe lane; optional merge_group smoke for Fujiwa batch subset.
- Negative: budget exhaustion defers job; mutex defers batch when speed active.

## Out of Scope

- **A0 Foundation** (prerequisite — #598)
- **A1 Speed** — material webhook handoff, targeted fetch, five KPI speed precompute, hourly Fujiwa
- **3.5-B Decisions ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** — blocked on A1, not A2
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))**
- OAuth, Sign-in, seller_connect, self-serve cold-start fleet (3.5-C C2)
- Read-replica isolation as A2 exit gate
- ClickHouse / columnar warehouse
- Separate batch serving tables or KPI formula fork
- Global hourly full poll for every tenant
- Bestselling as Demo KPI

## Further Notes

- **Parallelism:** A2 may implement while A1 ships speed path — disjoint modules (scheduler vs webhook dispatcher) after A0 merges.
- **Rollout:** Enable staggered scheduler behind config flag; start with Fujiwa + N stub shops; verify budget metrics before fleet expansion.
- **Observability:** Batch job id, shop_id, budget drops, partition cursor, gold write latency; never log tokens/PII.
- **Risks:** Over-aggressive batch fetch may still stress Partner API — dual budgets are exit gates; Track B #600 does not depend on A2.
