## Assumptions

- **A0 Foundation ([#598](https://github.com/thienphung00/Juli-AI/issues/598)) must exit first** — medallion schemas, serving gold contract, first domain cutover live.
- Architect split locked in [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md): this PRD is the **Speed layer** — **single-shop, event-driven freshness (OLTP-shaped)**. It is **not** the fleet throughput / cost-optimization layer (that is **A2 Batch [#602](https://github.com/thienphung00/Juli-AI/issues/602)**).
- Grill handoff ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md), [ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md), [ADR-046](docs/adr/046-cdp-medallion-physical-model.md)) authoritative; no re-interview.
- **Fujiwa Mock reference shop only**; OAuth / multi-tenant out of scope.
- **3.5-B Decisions ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** blocked on **this A1 exit**, not A2 Batch.
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))** may parallel with fixtures until A1 `payload.kpis` keys land.
- Default tests: Material compute dispatcher, Targeted fetch planner, Shared Compute Orchestrator speed path, KPI precompute (five Demo KPIs), Envelope cache, Hourly Mock reconciler.

## Problem Statement

The public Demo is wired to CDP envelopes in principle, but the **production-deployed** path stops short of continuous Analytics freshness. Material TikTok shop events reach ETL on the deployed API mount, yet they do **not** reliably enqueue shop-scoped fetch-then-precompute — so Demo KPIs advance mainly from poll/backfill, not the webhook-first **Speed layer** the product locked (ADR-038, ADR-048).

After A0 establishes medallion schemas and serving gold, sellers still need the **Demo Main KPI set** — **exactly five KPIs:** GMV, AOV, CTOR, LIVE hours, cancellation rate — to reflect **event-driven**, Partner-grounded freshness via deployed material handoff → targeted fetch → Shared Compute → `gold.kpi_envelopes`.

## Solution

Ship **Phase 3.5-A1 Speed** — the **Speed layer** (OLTP-shaped **freshness**) on medallion foundation:

**Material shop update → ETL → enqueue → targeted Partner fetch → Shared Compute (bronze→silver→gold) → Redis read-through → Demo Analytics**

Key themes:
1. **Deployed material handoff (P0):** After ETL success for curated material webhook types, enqueue shop-scoped fetch-then-precompute on the **deployed** route — not only test factory.
2. **Targeted fetch (P0) — forbid full poll:** Post-webhook jobs fetch only implicated Partner resources. **Out of AC / fail review:** reusing `_FUJIWA_POLL_STEPS`, `run_fujiwa_poll_cycle` full stack, or unbounded `sync_analytics` A-31–A-39 fan-out on the material path because “it already works.” That shortcut is exactly the anti-pattern 3.5-A was written to prevent.
3. **Shared Compute Orchestrator (P0):** One shop-scoped job per material trigger: bronze append → silver upsert → gold envelope write (ADR-046 Q4).
4. **Five Demo Main KPIs (P0):** Precompute locked `payload.kpis` keys (below). **No Bestselling (A-38/A-39)** as Demo KPI.
5. **Speed-path ingest hygiene:** A-7 cancellations poll + webhook #11 reconcile; A-38/A-39 persist-or-stop (ops only); A-31/A-33 fan-out guard.
6. **Hourly Fujiwa reconciler:** Narrow Mock reference-shop exception only (ADR-048) — fleet daily staggered reconcile is **A2 Batch**.
7. **Public Demo Analytics read API:** Masked `gold.kpi_envelopes` for server-bound reference shop.
8. **Envelope Cache:** Redis is **read-through only** — Postgres `gold.kpi_envelopes` remains SoT (ADR-038). Cache is never SoT.

**Mock mode only:** Fake Refresh; no OAuth; no Partner writes from public Demo.

### Locked catalogs (Executor must not invent)

**Material webhook types that enqueue compute** (catalog IDs from #532 / ADR-048): `#1`, `#2`, `#5`, `#12`, `#27`, `#39`, `#67`, and `#68` with **15-minute per-shop coalesce**. Non-material types: ingest only — no fetch-then-precompute enqueue.

**Initial `payload.kpis` metric_id keys** (exactly five; ADR-049 / #525):

| metric_id | Seller label | Notes |
|-----------|--------------|-------|
| `gmv_tiktok` | GMV (TikTok) | Default hero; never alias as Net Revenue |
| `aov` | AOV | Derived from GMV ÷ orders |
| `ctor` | CTOR (click→đơn) | GMV-weighted click_order_rate |
| `live_hours` | LIVE hours | A-28; not GMV LIVE / not avg_watch_duration |
| `cancellation_rate` | Cancellation rate | A-7 + webhook #11 |

### Negative AC — Speed/Batch split (Must not violate)

**A1 must not defer, batch, coalesce, or throughput-optimize** Partner fetch, bronze append, silver promotion, or gold writes **beyond the existing #68 15-minute per-shop inventory coalesce** for cost, fleet scale, Postgres I/O, or “scalability” reasons. That work is **A2 Batch (#602)**’s job.

A1’s purpose is **single-shop, low-latency freshness**. Adding fleet-style batching / deferred writes / throughput optimizations into A1 is a **silent violation of the Speed/Batch split** — it will surface later as laggy Analytics with no obvious cause. Fail intent-review if A1 PRs introduce A2-shaped throughput controls.

## User Stories

1. As a **prospective seller**, I want Demo Analytics KPIs to update after real shop events, so that I trust Juli measures live commerce — not yesterday's poll snapshot.
2. As a **prospective seller**, I want **GMV (TikTok)** as the default hero KPI when envelope data exists, so that the primary money metric matches TikTok reporting.
3. As a **prospective seller**, I want **AOV** derived honestly from GMV and order counts, so that average order value is understandable.
4. As a **prospective seller**, I want **CTOR (click→đơn)** as a GMV-weighted click-to-order rate, so that funnel quality is visible in seller language.
5. As a **prospective seller**, I want **LIVE hours** from Partner live analytics, so that streaming effort is visible.
6. As a **prospective seller**, I want **cancellation rate** from returns/cancellations data, so that operational risk is visible.
7. As a **prospective seller**, I want dropped ADR-023 metrics and **Bestselling (A-38/A-39)** absent from Demo selector, so that the Demo does not pretend unsupported KPIs.
8. As a **prospective seller**, I want honest **unavailable** states when fields are missing, so that Juli never fabricates values.
9. As a **platform operator**, I want material webhooks on the **deployed** API to enqueue compute after ETL, so that production matches documented architecture.
10. As a **platform operator**, I want only **curated material webhook types** to trigger compute, so that Partner rate limits stay controlled.
11. As a **platform operator**, I want **targeted fetch** after material events — not a full Fujiwa poll cycle — so that webhook-driven freshness stays OLTP-shaped.
12. As a **platform operator**, I want **A-7 cancellations** polled and reconciled with webhook #11, so that cancellation KPIs are complete.
13. As a **platform operator**, I want **A-38/A-39** to persist rank rows or stop calling, so that Partner quota is not silently wasted — without treating bestselling as Demo KPI.
14. As a **platform operator**, I want **A-31/A-33 detail fan-out** blocked in routine paths, so that list-page scale does not explode Partner calls.
15. As a **platform operator**, I want an **hourly** reconciliation job for Fujiwa Mock shop only, so that gaps without material events still refresh Analytics.
16. As a **platform operator**, I want shop-scoped idempotent speed jobs, so that webhook bursts do not corrupt silver or gold.
17. As a **backend engineer**, I want a **Targeted Fetch Planner** with explicit event→resource mapping, so that new webhook types extend fetch scope surgically.
18. As a **backend engineer**, I want compute to reuse existing transform/compute callables, so that A1 does not fork KPI formulas.
19. As a **backend engineer**, I want the five locked `metric_id` keys in `payload.kpis`, so that Track B #600 consumes a stable contract.
20. As a **integrations engineer**, I want deployed webhook assembly wired like integration tests expect, so that #532-class gaps do not recur on production only.
21. As a **QA engineer**, I want tests proving material webhook → ETL → enqueue → orchestrator → cached Demo GET for at least one B′ KPI, so that continuous Analytics is CI-verifiable with fixtures.
22. As a **QA engineer**, I want tests that targeted fetch plans **exclude** `_FUJIWA_POLL_STEPS` / full poll stacks, so that the anti-pattern cannot regress.
23. As a **QA engineer**, I want intent/review checks that A1 PRs do not add fleet batching / deferred-write / Postgres I/O governors — those belong to A2.
24. As a **security reviewer**, I want Demo reads bound to one server-configured reference shop, so that visitors cannot pivot tenants.
25. As a **security reviewer**, I want production_read isolation preserved, so that OAuth remains future Phase 3 scope.
26. As an **on-call engineer**, I want enqueue reason logged (webhook type vs hourly reconcile), so that freshness lag is diagnosable without PII.
27. As an **on-call engineer**, I want last-good cached envelopes on compute failure, so that Demo degrades gracefully (cache ≠ SoT).
28. As a **Demo UI implementer (Track B)**, I want envelope `computed_at` and per-KPI availability on read API, so that trust copy is honest.
29. As a **product owner**, I want **Decisions deferred to 3.5-B** until A1 exits, so that Analytics speed path proves first (ADR-048).
30. As a **product owner**, I want daily staggered fleet reconcile explicitly in **A2**, so that A1 scope stays OLTP-shaped freshness.
31. As a **Meta/release gate owner**, I want public Demo/API deploy changes covered by release-evidence when speed wiring ships.

## Implementation Decisions

- **Phase boundary:** A1 = Speed / freshness layer only ([ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md)); depends on **A0** medallion foundation.
- **Architecture:** Speed path on medallion ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md)); webhook-first ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)); dual-layer cache ([ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md)); five Demo KPIs ([ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md)).
- **Lambda layer:** Speed (OLTP-shaped) writes **Serving layer** `gold.kpi_envelopes`; Batch reconcile deferred to A2.
- **Forbidden shortcuts (explicit):** Material path must use Targeted Fetch Planner only — **never** `_FUJIWA_POLL_STEPS` / full `run_fujiwa_poll_cycle` / unbounded `sync_analytics` after material webhooks.
- **Negative AC:** No A2-shaped defer/batch/throughput/I/O governors in A1 beyond #68’s 15-min coalesce.
- **P0 sequencing:** (1) deployed material handoff → orchestrator enqueue, (2) targeted fetch planner, (3) A-7 in silver, (4) A-38/A-39 ops guard, (5) fan-out guard, (6) five KPI precompute → gold, (7) hourly Fujiwa reconciler, (8) public Demo Analytics GET.
- **Hourly reconciler:** Celery beat (or equivalent) task; same orchestrator entrypoint; `enqueue_reason=reconcile_hourly`; Fujiwa allowlist only.
- **A-7 ownership:** A0 owns silver schema + upsert contract; A1 owns poll + webhook #11 reconcile logic and `cancellation_rate` KPI population.
- **P1 (after P0):** finance unsettled + statements; video performance list analytics where KPI contracts require.
- **Credential model:** Mock production_read Fujiwa; Sign-in disabled.
- **Interactions:** Webhook ACK → ingest → material types enqueue targeted fetch → orchestrator (bronze→silver→gold) → Redis read-through (not SoT) → Demo GET; hourly job uses same orchestrator with gap fetch plan.

## Testing Decisions

- External behavior: `payload.kpis` for all **five** locked metric_ids; material webhook classification; targeted fetch plan bounded; A-7 reconcile; fan-out guard; Fake Refresh does not enqueue compute.
- **Negative:** CI/fixture asserts material-path fetch plan does **not** equal full Fujiwa poll step list; no A2 I/O budget module wired into A1 speed jobs.
- Prior art: webhook catalog tests, material webhook compute (#532), Demo Analytics contract tests, Redis cache tests.
- CI: no live Partner in PR-safe lane; integration happy path with fixtures.
- Modules under test: Material Compute Dispatcher, Targeted Fetch Planner, Shared Compute Orchestrator, KPI Precompute (five keys), Envelope Cache, Hourly Mock Reconciler, Cancellations Ingest, Quota Guard.

## Out of Scope

- **A0 Foundation** (prerequisite — #598)
- **A2 Batch** — daily staggered reconcile, dual budgets (Partner **and** Postgres I/O), cold-start fleet engine, fleet throughput optimizations
- **3.5-B Decisions ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** — starts after A1 exit
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))**
- OAuth, Sign-in, seller_connect
- Bestselling as Demo KPI
- Daily staggered fleet reconcile (A2)
- Columnar warehouse
- Poll-heavy spine (full Fujiwa cycle per webhook) — **explicitly rejected; out of AC**
- Trained ML inference as exit requirement

## Further Notes

- **Blocking for B:** 3.5-B ([#599](https://github.com/thienphung00/Juli-AI/issues/599)) unblocks when webhook-driven `computed_at` advances on Demo Analytics for B′ five KPIs.
- **Rollout:** Deploy speed wiring to production API mount; verify Fujiwa Mock freshness; Track B #600 swaps fixtures to live envelopes.
- **Observability:** Log enqueue reason, fetch plan size, cache hit ratio; never log tokens/PII.
- **Risks:** Shared Mock snapshot; #68 debounce up to 15 min inventory lag; P1 finance/video may stay unavailable until landed; Executor deadline pressure to reuse full poll — blocked by negative AC above.
