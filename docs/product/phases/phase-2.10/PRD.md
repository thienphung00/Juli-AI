# PRD: Phase 2.10 — Demo Dual-Layer Real Data

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) Phase 2.10 brief ·
> [ADR-037](../../../adr/037-phase-2.10-demo-real-data-no-auth.md) ·
> [ADR-038](../../../adr/038-phase-2.10-dual-layer-pipeline.md) ·
> [`MODULES.md`](../../../architecture/MODULES.md) ·
> [`CONTEXT.md`](../../../../CONTEXT.md) ·
> [`webhooks.md`](../../../integrations/tiktok_api/webhooks.md) ·
> [`execution_layer.md`](../../execution_layer.md) ·
> [`visual_layer.md`](../../../ml/visual_layer.md).
>
> **Parent issue:** [#524](https://github.com/thienphung00/Juli-AI/issues/524) — filed via
> `to-prd` from grill-with-docs (2026-07-27).
>
> **Child slices (`to-issues` 2.10-A only):**
> [#525](https://github.com/thienphung00/Juli-AI/issues/525) schema ·
> [#526](https://github.com/thienphung00/Juli-AI/issues/526) GMV precompute ·
> [#527](https://github.com/thienphung00/Juli-AI/issues/527) product/LIVE ·
> [#528](https://github.com/thienphung00/Juli-AI/issues/528) unavailable contract ·
> [#529](https://github.com/thienphung00/Juli-AI/issues/529) Redis cache ·
> [#530](https://github.com/thienphung00/Juli-AI/issues/530) masking ·
> [#531](https://github.com/thienphung00/Juli-AI/issues/531) public Analytics API ·
> [#532](https://github.com/thienphung00/Juli-AI/issues/532) material webhooks ·
> [#533](https://github.com/thienphung00/Juli-AI/issues/533) hourly Mock ·
> [#534](https://github.com/thienphung00/Juli-AI/issues/534) Demo wire + Fake Refresh ·
> [#535](https://github.com/thienphung00/Juli-AI/issues/535) HITL prod smoke.
> **2.10-B** Decision slices not filed yet.

## Assumptions

- Grill handoff is authoritative; no re-interview.
- Deep modules listed below match Architect intent; default tests cover Precompute, Cache, Material webhook dispatcher, Public Demo read API, Masking, Emission budget, Dry-run execution, and Demo Analytics/Decisions clients.
- Redis URL/credentials will be supplied by ops for required read-through cache.
- Reference shop remains Fujiwa / `production_read`.
- Phase 2.9 backfill history is warm enough for GMV/product/LIVE charts (gaps stay truthful).

## Problem Statement

The public Demo’s Analytics visual layer is still mock-driven and vague, even though Phase 2.9 has loaded real Partner Analytics history into shared Postgres. Visitors cannot see truthful shop performance, and Decisions are not yet driven by the same live intelligence. We need a production-shaped path—ingest → compute → Analytics and Decisions—that scales toward many shops, keeps the Demo usable without login, protects the reference merchant from public-driven recompute storms and accidental live TikTok writes, and still creates a healthy cadence of Decisions (not too few, not too many).

## Solution

Ship **Phase 2.10** as two sequential slices on one spine:

**TikTok events → material webhooks + API fetch → raw Postgres → transform/compute → precomputed Postgres + required Redis cache → Analytics Layer | Decision Layer**

- **2.10-A — Analytics Layer:** Materialize masked KPI envelopes for the reference shop; serve public Demo Analytics (GMV/product/LIVE must-haves; honest `unavailable` for Ads/Shop Status/T1 overlays).
- **2.10-B — Decision Layer:** Reuse the Phase 2 rules scoring pipeline on the same precompute; surface Action Cards under a Decision emission budget; Demo Approve/execute is **dry-run only** (no merchant OAuth Partner writes).

**Mock mode (2.10 default):** many visitors share one snapshot; compute via material webhooks + hourly reconciliation; **Fake Demo Refresh** (re-read only); Home/Settings stay mock; Sign-in stub stays disabled.

**Login/Sign-in (Phase 3+):** out of this PRD—hybrid real refresh + credentialed execution.

## Deep modules (expected)

| Module | Responsibility | Public interface (words) |
|--------|----------------|--------------------------|
| KPI Precompute | Transform analytics + aggregates into durable shop-scoped KPI envelopes | Build/upsert envelopes; mark availability per KPI |
| Envelope Cache | Required Redis read-through of Analytics/Decision envelopes | Get/set/invalidate by shop; never SoT |
| Material Compute Dispatcher | After curated webhooks, enqueue shop compute; debounce #68 | Classify material vs ingest-only; coalesce; per-shop mutex |
| Hourly Mock Reconciler | Narrow scheduler for reference-shop recompute | Run once/hour for configured Mock shop |
| Identity Masking | Alias shop/SKU/ids; keep real magnitudes | Mask envelopes for public responses |
| Public Demo Read API | Unauthenticated GETs for server-bound reference shop | Analytics + Decision list reads; no visitor `shop_id` |
| Rules Scoring Wire | Existing aggregates → signals → recs → copy → Action Cards on compute | Same pipeline callable; triggered by material/hourly jobs |
| Decision Emission Budget | Cap surfaced Decisions | Active-set / cooldown / weekly novelty gates |
| Demo Dry-run Execution | Simulate Approve→execute without Partner writes | Local execution records only |
| Demo Analytics/Decisions UI | Swap mock fixtures for live envelopes; Fake Refresh | Read APIs; dry-run Decision UX |

## User Stories

1. As a visitor, I want Demo Analytics to show real GMV trends for the demo shop, so that I trust Juli diagnoses real performance—not invented charts.
2. As a visitor, I want product funnel and LIVE charts when data exists, so that I see more than a single headline number.
3. As a visitor, I want Ads, Shop Status, and forecast overlays marked unavailable when sources are missing, so that Juli never fabricates metrics.
4. As a visitor, I want Net Revenue never silently replaced by GMV, so that money metrics stay honest (GMV labeled as TikTok GMV).
5. As a visitor, I want shop name and product titles aliased, so that the real merchant is not obvious on a public site.
6. As a visitor, I want real magnitude trends preserved under masking, so that the Demo still feels like a live business.
7. As a visitor, I want to open Demo without signing in, so that I can explore immediately.
8. As a visitor, I want Demo Refresh to update what I see from cache/DB, so that the control still feels responsive—even if it does not recompute.
9. As a visitor, I want Home and Settings to keep working as today (mock), so that 2.10 does not break the four-destination shell.
10. As a visitor, I want Decisions to show real recommendations from the same intelligence as Analytics, so that advice matches the charts.
11. As a visitor, I want only a small set of active Decisions, so that I am not overwhelmed.
12. As a visitor, I want Decisions not to churn every few minutes, so that optimizations have time to matter and I still have a reason to return.
13. As a visitor, I want Approve/execute on Demo to complete a guided flow without changing the real TikTok shop, so that the story is safe on a public site.
14. As a seller (future Login mode), I want the same spine to support real refresh and real execution later, so that 2.10 investment is not throwaway.
15. As a platform operator, I want Postgres to remain system of record for raw and precomputed rows, so that cache loss is recoverable.
16. As a platform operator, I want Redis required for envelope reads, so that public Demo traffic does not hammer expensive DB assemblies.
17. As a platform operator, I want only curated material webhooks to enqueue compute, so that Partner rate limits and compute cost stay controlled.
18. As a platform operator, I want inventory-changed webhooks coalesced to one compute per shop per 15 minutes, so that the firehose does not stampede jobs.
19. As a platform operator, I want an hourly Mock reconciliation for the reference shop, so that gaps without material events still refresh diagnosis.
20. As a platform operator, I want public force-recompute disabled or strictly rate-limited, so that many Demo visitors cannot DoS the pipeline.
21. As a platform operator, I want the public API bound to one configured shop server-side, so that visitors cannot pivot to other tenants.
22. As a backend engineer, I want compute to reuse the existing rules scoring pipeline, so that 2.10-B does not invent a parallel KPI/Decision formula path.
23. As a backend engineer, I want tunable threshold config for signals, so that we can balance Decision volume without code rewrites.
24. As a backend engineer, I want Decision emission defaults (max 5 active, 7-day per-workflow cooldown, soft weekly novelty 3), so that psychology starts from an agreed baseline.
25. As a backend engineer, I want Analytics KPIs able to update more often than Decisions are surfaced, so that diagnosis stays fresh without Decision spam.
26. As a backend engineer, I want material events to include order, reverse, product status, return, inventory status, activity, refund success, and debounced inventory changed, so that shop-performance changes drive compute.
27. As a backend engineer, I want package/address/FBT-detail/account-lifecycle webhooks to ingest without enqueueing KPI compute, so that monitors stay cheap.
28. As a frontend engineer, I want shared contract shapes for KPI and Decision envelopes, so that Mock→live is a data-source swap.
29. As a frontend engineer, I want Sign-in to remain a disabled stub, so that 2.10 does not imply OAuth is live.
30. As a QA engineer, I want exit criteria that prove Analytics live, Fake Refresh, material/hourly compute, Decisions + dry-run, and no real Partner writes, so that we can sign off 2.10.
31. As a product owner, I want Landing deploy and Sign-in OAuth deferred to Phase 3, so that this week ships Demo value without LP blockers.
32. As a product owner, I want the design to assume ~100 shops later (shop-scoped jobs, cache keys, idempotent upserts), so that 2.10 is not a Demo-only dead end.
33. As a security reviewer, I want Demo never to use the reference merchant’s credentials for write APIs, so that public exploration cannot mutate Fujiwa.
34. As a security reviewer, I want buyer PII to remain forbidden, so that masking identity is not confused with relaxing PII rules.
35. As an analytics consumer, I want Inventory/Ops/CSAT live only when aggregates already compute them, so that 2.10-A does not invent new ETL science.
36. As an on-call engineer, I want compute failures to leave last-good cached envelopes readable, so that Demo degrades gracefully.
37. As a Demo visitor, I want charts and Decision copy in the existing Demo IA, so that real data does not require a redesign.
38. As a future Decision Layer owner, I want one Analytics KPI read model shared by both layers, so that charts and recommendations cannot drift.

## Implementation Decisions

- **Phase boundary:** Insert Phase 2.10 before Phase 3; no visitor OAuth; Landing not required (ADR-037).
- **Architecture:** Dual-layer Product Intelligence over shared precompute; Postgres SoT; Redis required read-through (ADR-038).
- **Slices:** 2.10-A Analytics then 2.10-B Decisions; Home/Settings remain mock.
- **Mock vs Login:** Mock = material webhooks + hourly + Fake Demo Refresh + dry-run; Login hybrid deferred to Phase 3.
- **KPI must-haves:** GMV (TikTok) + A-36 traffic where present; A-34; A-28/A-29 as data allows; never alias GMV as Net Revenue; Ads/SPS/AHR/VP/T1 overlays unavailable.
- **Masking:** Identity mask, real magnitudes.
- **Public API:** Unauthenticated GET; server-configured reference shop only.
- **Material webhooks:** #1, #2, #5, #12, #27, #39, #67; #68 coalesced 15 min/shop; light per-shop mutex.
- **Decision intelligence:** Reuse Phase 2 rules pipeline; add threshold config + emission budget; no new ML trainers in 2.10.
- **Emission defaults (tunable):** max 5 active Decisions; 7-day cooldown per workflow after terminal action; soft weekly novelty cap of 3.
- **Schema:** Additive precompute/KPI envelope tables as needed (schema-only Alembic); Action Cards remain Postgres.
- **Interactions:** Webhook ACK → ingest; material types enqueue compute after fetch success; hourly job for Mock shop; public Refresh re-reads only; Decision Approve on Demo writes dry-run execution records only.

## Testing Decisions

- Prefer behavioral tests: envelope contents, availability flags, mask aliases, cache hit/miss after compute, webhook classify/debounce, emission gates, Fake Refresh does not enqueue compute, dry-run never calls Partner writes.
- Prior art: webhook catalog tests, scoring pipeline tests, action-cards refresh tests, Demo Analytics/Manual Refresh frontend tests, analytics backfill partition tests.
- Default modules under test: Precompute, Cache, Material dispatcher (#68 coalesce), Public read API, Masking, Emission budget, Dry-run execution, Demo Analytics + Decisions clients.
- Integration: one reference-shop happy path from fixture/raw rows → precompute → cached GET → Demo render; negative path for unavailable KPIs.

## Out of Scope

- Landing Page deploy / Phase 2.7 completion as a 2.10 exit gate
- Enabling Sign-in/OAuth or Login-mode real refresh/execution
- Real TikTok Partner write calls from public Demo (any “execute” path)
- Trained T1–T8 product inference / forecast overlays as required
- Ads ETL (ROAS/CAC/CTR) and Shop Status Partner fields
- Home and Settings real-data wiring
- Multi-tenant / per-visitor shop connect (Phase 3.5)
- Redis as system of record
- Numeric noise/scale-factor masking
- Celery beat as primary freshness for every shop (only narrow Mock hourly for reference shop)
- PostHog as 2.10 exit requirement

## Further Notes

- **Rollout:** Deploy behind existing `demo.app-juli.com`; keep Sign-in stub; verify public release evidence expectations if Demo deploy changes runtime config.
- **Observability:** Log compute enqueue reason (webhook type vs hourly vs rejected); cache hit ratio; emission budget drops; never log tokens/PII.
- **Risks:** Shared Mock snapshot means all visitors see the same shop; hourly+webhook lag vs “realtime” expectations—document Fake Refresh; #68 debounce may delay inventory KPIs up to 15 minutes.
- **Follow-ups:** Phase 3 Sign-in/Login hybrid; Landing; threshold tuning from live psychology; optional Home teasers reading the same envelopes.
- **Exit gate (EXECUTION):** Precompute + Redis; Analytics masked live; material+#68 coalesce + hourly; Fake Refresh; Decisions + dry-run; Home/Settings mock; no OAuth; no real Partner writes.
