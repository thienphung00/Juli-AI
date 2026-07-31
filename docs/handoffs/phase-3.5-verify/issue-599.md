# Issue #599: Phase 3.5-B: Continuous CDP Decisions on shared compute
State: OPEN
Labels: enhancement, PRD

## Assumptions

- Grill handoff ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md), demo-ui-fix grill two-track section, CONTEXT Continuous CDP spine / Decision emission budget) is authoritative; no re-interview.
- **Phase 3.5-A must exit first** — this PRD is **blocked** until the Analytics-first continuous path (material webhook → ETL → targeted fetch → KPI envelope → Demo Analytics) is working on the deployed spine for Fujiwa Mock reference shop.
- **Fujiwa Mock Demo reference shop only** for 3.5-B prove-out; multi-tenant OAuth not in scope.
- **Track B Demo UI fix** (Decision automation UX, no confidence UI, Juli-handles-all confirm, progress cards, `/decisions` load) may ship UX contracts in parallel but **Decision feed freshness** depends on this Backend wire.
- Rules-based scoring only in 3.5-B; **rules → ML promotion** is Phase 4+ — do not block on trained models.
- Deep modules below match Architect intent; default tests cover Rules scoring wire, Decision emission budget, Action Card persistence on compute, Demo dry-run execution, and Public Demo Decision read API.

## Problem Statement

Phase 2.10 scoped Decisions on the same precompute spine as Analytics, but the **continuous** path — material shop events driving fresh KPI envelopes **and** fresh Decision candidates — is sequenced **after** Analytics-first delivery (ADR-048). Today Demo Decisions may still lag poll/manual refresh patterns or fixtures while Analytics moves toward webhook-first freshness in Phase 3.5-A.

Sellers evaluating the Demo need recommendations that **match the same intelligence** as Analytics charts, surfaced at a **healthy cadence** (not spam on every webhook, not stale for weeks), with **safe dry-run execution** on the public site. Without wiring the existing Phase 2 rules pipeline to the **same compute trigger** as KPI precompute — plus an explicit **Decision emission budget** — the Decision loop does not prove the continuous CDP story product/GTM needs for Phase 2.10 exit and sales demos.

## Solution

Ship **Phase 3.5-B** as the **Decisions-next continuous CDP slice** on the shared spine Phase 3.5-A establishes:

**Same compute trigger (material webhook / hourly Mock reconcile / staggered daily reconcile) → KPI precompute + rules scoring → Action Cards → emission budget → Demo Decisions read API → Demo dry-run approve/execute**

Key delivery themes:
1. **Shared compute trigger:** When shop-scoped fetch-then-precompute runs after material events or reconcile jobs, invoke **both** KPI envelope build **and** rules scoring pipeline — no parallel KPI formula path for Decisions.
2. **Rules scoring wire:** Reuse Phase 2 aggregates → signals → recommendations → rules copy → **persisted Action Cards** callable; triggered by continuous compute jobs — not only manual `POST /v1/action-cards/refresh`.
3. **Decision emission budget:** Cap **surfaced** Decisions separately from KPI freshness — daily active-set cap, per-workflow cooldown after approve/dismiss/execute, soft weekly novelty quota (ADR-038 defaults as starting config).
4. **Demo dry-run execution:** Public Mock Demo Approve/execute persists local/demo execution records only — **no** reference merchant Partner writes.
5. **Demo Decisions read API:** Unauthenticated GET for server-bound reference shop returns ranked, emission-gated Decision envelopes for Track B UI.

**Mock mode only:** Sign-in disabled; Fake Demo Refresh re-reads envelopes; real credentialed execution remains future Phase 3 Sign-in.

## Deep modules (by responsibility)

| Module | Responsibility | Public interface (words) |
|--------|----------------|--------------------------|
| **Shared Compute Orchestrator** | After targeted fetch + transform, run KPI precompute **and** rules scoring in one shop job | Single enqueue entry; shared inputs; independent freshness vs surfacing cadences |
| **Rules Scoring Wire** | Existing aggregates → signals → recs → copy → Action Card rows on compute | Callable from continuous jobs; same formulas as manual refresh |
| **Decision Emission Budget** | Throttle which Action Cards surface to Demo active set | Active cap, per-workflow cooldown, weekly novelty gate; tunable config |
| **Action Card Persistence on Compute** | Upsert ranked candidates after scoring | Shop-scoped upsert by workflow_key; status transitions preserved |
| **Demo Dry-run Execution** | Simulate Approve→execute without Partner writes | Local execution records; progress narrative for UI |
| **Public Demo Decisions Read API** | Unauthenticated GET for emission-gated Decision list/detail | Server-bound reference shop; masked fields; no visitor shop_id |
| **Decision Feed Freshness Metadata** | Expose `computed_at` / promotion timestamps for UI trust copy | Align with Analytics envelope freshness semantics |

## User Stories

1. As a **prospective seller (visitor)**, I want Demo Decisions to reflect the **same live shop intelligence** as Analytics charts, so that recommendations feel connected to what I just saw in KPIs.
2. As a **prospective seller**, I want Decisions to update after material shop events (orders, returns, inventory changes), so that advice responds to real commerce — not a static fixture list.
3. As a **prospective seller**, I want only a **bounded number of active Decisions** visible at once, so that I am not overwhelmed by optimization noise.
4. As a **prospective seller**, I want Decisions **not to churn** every few minutes when webhooks fire, so that I have time to act and Juli’s suggestions feel deliberate (emission budget).
5. As a **prospective seller**, I want to **approve** a Decision on the Demo without changing the real TikTok shop, so that the public Demo stays safe (dry-run).
6. As a **prospective seller**, I want post-approve execution to show **Juli handles the work** (progress narrative), so that the product story matches an execution platform — UI detail in Track B, freshness here.
7. As a **product / GTM lead**, I want the **Decision loop** provable on Fujiwa continuous spine, so that sales demos show Data → Decision → Approval → (dry-run) Execution.
8. As a **platform operator**, I want KPI envelope compute and rules scoring triggered by the **same shop jobs** as Phase 3.5-A, so that we do not maintain duplicate ingest/compute paths.
9. As a **platform operator**, I want **KPI freshness** able to move faster than **Decision surfacing**, so that Analytics stays current without Decision spam (dual cadence — ADR-038).
10. As a **platform operator**, I want emission defaults (max **5** active Decisions, **7-day** per-workflow cooldown after terminal action, soft weekly novelty **3**) as tunable starting config, so that psychology has an agreed baseline.
11. As a **platform operator**, I want candidate Action Cards recomputed even when emission budget suppresses surfacing, so that promotion logic can catch up on next eligible window.
12. As a **backend engineer**, I want the rules scoring pipeline invoked from continuous compute without forking KPI math, so that charts and cards cannot drift.
13. As a **backend engineer**, I want threshold config for signals tunable without code deploy where practical, so that Decision volume can be balanced during prove-out.
14. As a **backend engineer**, I want Action Card upserts idempotent on `workflow_key` per shop, so that webhook bursts do not duplicate cards.
15. As a **backend engineer**, I want dry-run execution paths isolated from Partner write clients, so that public Demo never uses Fujiwa credentials for mutations.
16. As a **Demo UI implementer (Track B)**, I want Decision list/detail read API with stable envelope shapes and freshness metadata, so that UX polish can ship against live feed when this wire lands.
17. As a **Demo UI implementer**, I want emission-gated active set reflected in list ordering/count, so that UI does not show suppressed candidates as active.
18. As a **QA engineer**, I want tests proving compute enqueue → scoring → persisted cards → emission filter → public GET, so that continuous Decisions are CI-verifiable with fixtures.
19. As a **QA engineer**, I want tests that emission budget blocks surfacing but allows recomputation, so that dual cadence regressions are caught.
20. As a **QA engineer**, I want tests that Demo approve/execute never calls Partner write endpoints, so that dry-run safety is enforced.
21. As a **security reviewer**, I want public Decision reads bound to one server-configured reference shop, so that visitors cannot enumerate other tenants’ cards.
22. As a **security reviewer**, I want rules copy and card payloads free of raw financial PII beyond masked Demo contract, so that public responses stay safe.
23. As an **on-call engineer**, I want logs for scoring duration, emission drops (reason codes), and dry-run execution starts, so that Decision lag is diagnosable.
24. As an **on-call engineer**, I want last-good Decision envelopes readable from cache when scoring fails, so that Demo degrades gracefully.
25. As a **product owner**, I want **rules-only** scoring in 3.5-B with a documented path to **ML promotion in Phase 4**, so that we do not delay continuous wire for model training.
26. As a **product owner**, I want Sign-in/OAuth and real credentialed execution explicitly deferred to Phase 3, so that scope stays Mock dry-run.
27. As a **future ML engineer**, I want scoring wire to accept promoted T2/T6/T8 techniques later without replacing continuous enqueue, so that ML is a swap-in behind the same trigger.
28. As a **Meta/release gate owner**, I want Demo Decision API changes covered by release-evidence when public surfaces change, so that deploy verification includes Decision feed smoke.
29. As a **visitor**, I want Decision copy in seller language (Track B contract) sourced from rules copy layer, so that cards read like Juli advice — not backend jargon.
30. As a **platform operator**, I want hourly Mock reconcile and daily staggered reconcile jobs to refresh Decision candidates the same way as KPI envelopes, so that gap reconciliation heals Decision staleness too.

## Implementation Decisions

- **Phase boundary:** Phase 3.5-B is the **Decisions-next continuous CDP** Backend track — **blocked on Phase 3.5-A** Analytics spine exit; distinct from Track B Demo UI fix and from EXECUTION “Phase 3.5 Full Web Application.”
- **Architecture:** Reuse dual-layer shared precompute ([ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md)); Analytics-first then Decisions sequencing ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)); manual refresh pipeline callables reused on continuous trigger ([ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md)); Demo no-auth + dry-run ([ADR-037](docs/adr/037-phase-2.10-demo-real-data-no-auth.md)).
- **Compute coupling:** Extend Phase 3.5-A shop jobs to call rules scoring after KPI precompute (same targeted fetch inputs); no second parallel fetch cycle for Decisions-only.
- **Emission budget:** Separate **surfacing** from **recomputation**; starting defaults per ADR-038 §6 (max 5 active, 7-day workflow cooldown, weekly novelty soft cap 3) — config tunable, not immutable product law.
- **Execution:** Demo dry-run only — local/demo execution records; no Partner writes with reference merchant credentials; real execution deferred to Phase 3 Sign-in.
- **Credential model:** Mock **production_read** Fujiwa only; Sign-in disabled ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)).
- **ML path:** Phase 2 rules + copy only; ML promotion gates remain Phase 4 — document interface stability for future technique swap.
- **UI boundary:** Track B owns suggestion glow, no confidence UI, editable inputs, Juli-handles-all confirm, progress cards, `/decisions` load fixes — this PRD delivers **feed freshness + backend contracts** only.
- **Interactions:** Material webhook / reconcile → shared compute orchestrator → KPI envelopes + scoring → Action Card upsert → emission filter → Redis read-through → public Demo Decisions GET; Approve on Demo → dry-run execution module only.

## Testing Decisions

- Test **external behavior:** Action Card rows after compute jobs; emission budget suppresses active set but allows DB candidates; public GET returns gated list; dry-run never invokes Partner writes; shared trigger runs both KPI and scoring (integration fixture).
- **Prior art:** action-cards refresh tests, scoring pipeline tests, emission budget unit tests (if present from 2.10-B intent), Demo Decisions contract tests, webhook→compute integration patterns from 3.5-A.
- **Default modules under test:** Shared Compute Orchestrator (Decision branch), Rules Scoring Wire, Decision Emission Budget, Action Card persistence on compute, Demo Dry-run Execution, Public Demo Decisions Read API.
- **CI posture:** fixture-driven scoring and emission tests in PR-safe lane; optional live smoke on merge queue after 3.5-A spine green.
- **Negative paths:** scoring failure leaves last-good cards; emission cooldown respects workflow_key terminal actions; approve on Demo does not enqueue real executor tasks with merchant credentials.

## Out of Scope

- **Phase 3.5-A** Analytics continuous spine (prerequisite — separate PRD)
- **Track B Demo UI fix** — trust copy, Decision automation UX polish, `/decisions` hang, contextual assistance format errors (separate PRD/issues; may ship ahead of feed wire)
- TikTok OAuth, Sign-up, Sign-in, enabling Demo Sign-in control
- Real Partner write execution from public Demo (Login-mode credentialed execution — Phase 3+)
- Trained ML inference / T2/T6/T8 promotion as 3.5-B exit requirement (Phase 4)
- Cloud LLM copy (Haiku) — Phase 4
- Multi-tenant per-visitor shop connect
- Landing Page deploy
- Home/Settings real-data wiring
- Unlimited realtime Decision spam on every webhook (explicitly rejected)
- Separate Decision-only ingest pipeline parallel to Analytics spine
- EXECUTION “Phase 3.5 Full Web Application” dashboard rebuild

## Further Notes

- **Blocking dependency:** Do not start 3.5-B implementation until 3.5-A deployed material handoff + KPI envelope continuous path is verified on Fujiwa Mock Demo (webhook-driven `computed_at` advances on Analytics).
- **Rollout:** Enable scoring branch on compute jobs behind config flag if needed; verify Decision feed freshness correlates with Analytics envelope updates; coordinate Track B UI ship when feed stable.
- **Observability:** Log scoring invoke reason, emission drops, active-set size, dry-run execution IDs; never log tokens/PII.
- **Risks:** Shared Mock snapshot — all visitors see same Decision set; emission budget may feel “slow” to internal testers — document as product intent; Track B UI may ship before feed — set seller expectations in Demo copy.
- **Follow-ups:** Phase 4 ML technique promotion behind same scoring wire; Phase 3 Sign-in real execution; Tune emission thresholds from Fujiwa prove-out data.


## Comment 1

## PRD split update (ADR-047)

Analytics CDP **3.5-A** is now three slices: **A0 Foundation ([#598](https://github.com/thienphung00/Juli-AI/issues/598))**, **A1 Speed ([#601](https://github.com/thienphung00/Juli-AI/issues/601))**, **A2 Batch ([#602](https://github.com/thienphung00/Juli-AI/issues/602))**.

### Blocking dependency change

**This issue (#599) is blocked on A1 Speed (#601)** — continuous KPI envelopes from the webhook-first speed path — **not** on A2 Batch (#602) or full A0+A2.

```
A0 (#598) → A1 (#601) → B (#599 this issue)
     └──→ A2 (#602)   [parallel OK; does not block B]
```

Decisions still attach to the **same Shared Compute trigger** after serving gold is stable on the speed path. See [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).
