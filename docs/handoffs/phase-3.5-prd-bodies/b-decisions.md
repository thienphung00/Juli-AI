## Assumptions

- Grill handoff ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md), demo-ui-fix grill two-track section, CONTEXT Continuous CDP spine / Decision emission budget) is authoritative; no re-interview.
- **Blocked on A1 Speed ([#601](https://github.com/thienphung00/Juli-AI/issues/601))** — not on A0 alone, and **not** on A2 Batch ([#602](https://github.com/thienphung00/Juli-AI/issues/602)). Continuous Analytics path (material webhook → ETL → targeted fetch → KPI envelope → Demo Analytics) must advance `computed_at` for B′ five KPIs on Fujiwa Mock before this PRD starts.
- Indirect prerequisite: A0 ([#598](https://github.com/thienphung00/Juli-AI/issues/598)) medallion + serving gold shape (required by A1).
- **Fujiwa Mock Demo reference shop only** for 3.5-B prove-out; multi-tenant OAuth not in scope.
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))** may ship UX contracts in parallel; **Decision feed freshness** depends on this Backend wire.
- Rules-based scoring only in 3.5-B; **rules → ML promotion** is Phase 4+ — do not block on trained models.
- Deep modules below match Architect intent; default tests cover Rules scoring wire, Decision emission budget, Action Card persistence on compute, Demo dry-run execution, and Public Demo Decision read API.

## Problem Statement

Phase 2.10 scoped Decisions on the same precompute spine as Analytics, but the **continuous** path — material shop events driving fresh KPI envelopes **and** fresh Decision candidates — is sequenced **after** Analytics-first delivery (ADR-048). Today Demo Decisions may still lag poll/manual refresh patterns or fixtures while Analytics moves toward webhook-first freshness via **A1 Speed**.

Sellers evaluating the Demo need recommendations that **match the same intelligence** as Analytics charts, surfaced at a **healthy cadence** (not spam on every webhook, not stale for weeks), with **safe dry-run execution** on the public site. Without wiring the existing Phase 2 rules pipeline to the **same compute trigger** as KPI precompute — plus an explicit **Decision emission budget** — the Decision loop does not prove the continuous CDP story product/GTM needs.

## Solution

Ship **Phase 3.5-B** as the **Decisions-next continuous CDP slice** on the shared spine **A1 Speed** establishes:

**Same compute trigger (material webhook / hourly Mock reconcile; daily staggered reconcile when A2 exists) → KPI precompute + rules scoring → Action Card candidates → emission budget (surfacing) → Demo Decisions read API → Demo dry-run approve/execute**

Key delivery themes:
1. **Shared compute trigger:** When shop-scoped fetch-then-precompute runs after material events or reconcile jobs, invoke **both** KPI envelope build **and** rules scoring — no parallel KPI formula path for Decisions; no Decision-only ingest pipeline.
2. **Rules scoring wire:** Reuse Phase 2 aggregates → signals → recommendations → rules copy → **persisted Action Cards**; triggered by continuous compute jobs — not only manual `POST /v1/action-cards/refresh`.
3. **Decision emission budget:** Cap **surfaced** Decisions separately from KPI freshness and from candidate recomputation — daily active-set cap, per-workflow cooldown after approve/dismiss/execute, soft weekly novelty quota (ADR-038 defaults).
4. **Demo dry-run execution:** Public Mock Demo Approve/execute persists local/demo execution records only — **no** reference merchant Partner writes; **must not** call `/v1/executions`, `enqueue_approved_tool`, or `run_tool_async`.
5. **Demo Decisions read API:** Unauthenticated GET for server-bound reference shop returns ranked, emission-gated Decision envelopes for Track B UI.

**Mock mode only:** Sign-in disabled; Fake Demo Refresh re-reads envelopes; real credentialed execution remains future Phase 3 Sign-in.

### Deep modules (by responsibility)

| Module | Responsibility | Public interface (words) |
|--------|----------------|--------------------------|
| **Shared Compute Orchestrator (Decision branch)** | After targeted fetch + transform, run KPI precompute **and** rules scoring in one shop job; inherit shop mutex / #68 coalesce from A1 | Single enqueue entry; shared inputs; independent freshness vs surfacing cadences |
| **Rules Scoring Wire** | Existing aggregates → signals → recs → copy → Action Card **candidates** on compute | Callable from continuous jobs; same formulas as manual refresh |
| **Decision Emission Budget** | Throttle which candidates **surface** to Demo active set | Active cap, per-workflow cooldown, weekly novelty gate; tunable config |
| **Action Card Persistence on Compute** | Upsert ranked candidates after scoring | Shop-scoped upsert by workflow_key; candidate vs surfaced states |
| **Demo Dry-run Execution** | Simulate Approve→execute without Partner writes | Isolated module; CI guard against Partner write clients |
| **Public Demo Decisions Read API** | Unauthenticated GET for emission-gated Decision list/detail | Server-bound reference shop; masked fields; no visitor shop_id |
| **Decision Feed Freshness Metadata** | Expose `computed_at` / promotion (`surfaced_at`) timestamps for UI trust copy | Align with Analytics envelope freshness semantics |

### Emission persistence design (Must — Executor must not invent)

Dual cadence requires **candidate recomputation ≠ surfacing**:

- Persist **candidates** after scoring even when budget suppresses surfacing (user story 11).
- Surfacing state must be queryable separately from “all scored rows” — e.g. status values `candidate` / `surfaced` / `suppressed` **or** equivalent columns (`surfaced_at`, `suppressed_reason`) on `action_cards` (or a thin `gold.decision_envelopes` serving projection). Pick one model in implementation; document in MODULE.md.
- Store weekly novelty counter / window state server-side (config + durable counter), not only in Redis.
- **Cooldown / indexes:** efficient cooldown lookup on terminal actions — e.g. composite index supporting `(shop_id, workflow_key)` + terminal timestamps (`approved_at` / `executed_at` / dismiss). Cap active surfaced set at config default **5**.

**Emission defaults (tunable, not immutable law):** max **5** active surfaced; **7-day** per-workflow cooldown after terminal action; soft weekly novelty **3**.

### Redis vs Postgres SoT (Must — same discipline as Envelope Cache)

- **Postgres is SoT** for Action Card **candidates**, emission/cooldown/novelty state, and dry-run execution records.
- **Redis is read-through only** for the **public emission-gated Decision list envelope** (optional performance layer) — **never SoT**.
- Do **not** treat Redis as the source of candidate or emission truth (ADR-038 / ADR-021 discipline: cache is never SoT).
- Last-good degradation: serve last-good **Postgres** (or last-good cached copy of gated GET) on scoring failure — cache miss must not invent empty “truth.”

### Shop compute mutex (Must)

Inherit A1 / ADR-038 shop-scoped mutex + #68 15-min coalesce for the **shared** KPI+scoring job. Scoring must **not** create a second Decision-only enqueue path that bypasses the mutex. Webhook bursts must not stampede scoring.

### Dry-run isolation (Must)

Public Demo approve/execute **must not** call `/v1/executions`, `enqueue_approved_tool`, or `run_tool_async`. Separate demo dry-run module; CI test proves no Partner write client import/call on that path.

### Public Demo Decision envelope contract (for #600 swap)

Emission-gated list: max active count, order, `computed_at`, per-card `surfaced_at` (or equivalent), masked fields, server-bound shop. Fixtures in #600 must match this shape so live swap needs no IA redesign.

## User Stories

1. As a **prospective seller (visitor)**, I want Demo Decisions to reflect the **same live shop intelligence** as Analytics charts, so that recommendations feel connected to what I just saw in KPIs.
2. As a **prospective seller**, I want Decisions to update after material shop events (orders, returns, inventory changes), so that advice responds to real commerce — not a static fixture list.
3. As a **prospective seller**, I want only a **bounded number of active Decisions** visible at once, so that I am not overwhelmed by optimization noise.
4. As a **prospective seller**, I want Decisions **not to churn** every few minutes when webhooks fire, so that I have time to act and Juli’s suggestions feel deliberate (emission budget).
5. As a **prospective seller**, I want to **approve** a Decision on the Demo without changing the real TikTok shop, so that the public Demo stays safe (dry-run).
6. As a **prospective seller**, I want post-approve execution to show **Juli handles the work** (progress narrative), so that the product story matches an execution platform — UI detail in Track B, freshness here.
7. As a **product / GTM lead**, I want the **Decision loop** provable on Fujiwa continuous spine, so that sales demos show Data → Decision → Approval → (dry-run) Execution.
8. As a **platform operator**, I want KPI envelope compute and rules scoring triggered by the **same shop jobs** as A1 Speed, so that we do not maintain duplicate ingest/compute paths.
9. As a **platform operator**, I want **KPI freshness** able to move faster than **Decision surfacing**, so that Analytics stays current without Decision spam (dual cadence — ADR-038).
10. As a **platform operator**, I want emission defaults (max **5** active Decisions, **7-day** per-workflow cooldown after terminal action, soft weekly novelty **3**) as tunable starting config, so that psychology has an agreed baseline.
11. As a **platform operator**, I want candidate Action Cards recomputed even when emission budget suppresses surfacing, so that promotion logic can catch up on next eligible window.
12. As a **backend engineer**, I want the rules scoring pipeline invoked from continuous compute without forking KPI math, so that charts and cards cannot drift.
13. As a **backend engineer**, I want threshold config for signals tunable without code deploy where practical, so that Decision volume can be balanced during prove-out.
14. As a **backend engineer**, I want Action Card upserts idempotent on `workflow_key` per shop, so that webhook bursts do not duplicate cards.
15. As a **backend engineer**, I want dry-run execution paths isolated from Partner write clients, so that public Demo never uses Fujiwa credentials for mutations.
16. As a **Demo UI implementer (Track B)**, I want Decision list/detail read API with stable envelope shapes and freshness metadata, so that UX polish can ship against live feed when this wire lands.
17. As a **Demo UI implementer**, I want emission-gated active set reflected in list ordering/count, so that UI does not show suppressed candidates as active.
18. As a **QA engineer**, I want tests proving compute enqueue → scoring → persisted candidates → emission filter → public GET, so that continuous Decisions are CI-verifiable with fixtures.
19. As a **QA engineer**, I want tests that emission budget blocks surfacing but allows recomputation, so that dual cadence regressions are caught.
20. As a **QA engineer**, I want tests that Demo approve/execute never calls Partner write endpoints or `/v1/executions`, so that dry-run safety is enforced.
21. As a **security reviewer**, I want public Decision reads bound to one server-configured reference shop, so that visitors cannot enumerate other tenants’ cards.
22. As a **security reviewer**, I want rules copy and card payloads free of raw financial PII beyond masked Demo contract, so that public responses stay safe.
23. As an **on-call engineer**, I want logs for scoring duration, emission drops (reason codes), and dry-run execution starts, so that Decision lag is diagnosable.
24. As an **on-call engineer**, I want last-good Decision envelopes readable when scoring fails, so that Demo degrades gracefully (Postgres SoT; Redis optional cache).
25. As a **product owner**, I want **rules-only** scoring in 3.5-B with a documented path to **ML promotion in Phase 4**, so that we do not delay continuous wire for model training.
26. As a **product owner**, I want Sign-in/OAuth and real credentialed execution explicitly deferred to Phase 3, so that scope stays Mock dry-run.
27. As a **future ML engineer**, I want scoring wire to accept promoted T2/T6/T8 techniques later without replacing continuous enqueue, so that ML is a swap-in behind the same trigger.
28. As a **Meta/release gate owner**, I want Demo Decision API changes covered by release-evidence when public surfaces change, so that deploy verification includes Decision feed smoke.
29. As a **visitor**, I want Decision copy in seller language (Track B contract) sourced from rules copy layer, so that cards read like Juli advice — not backend jargon.
30. As a **platform operator**, I want hourly Mock reconcile (A1) and — **when A2 exists** — daily staggered reconcile to refresh Decision **candidates** the same way as KPI envelopes, so that gap reconciliation heals Decision staleness too. **A2 is not a #599 exit gate.**

## Implementation Decisions

- **Phase boundary:** Phase 3.5-B is the **Decisions-next continuous CDP** Backend track — **blocked on A1 Speed (#601)** per [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md); distinct from Track B Demo UI (#600) and from EXECUTION “Phase 3.5 Full Web Application.”
- **Architecture:** Reuse dual-layer shared precompute ([ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md)); Analytics-first then Decisions sequencing ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)); manual refresh pipeline callables reused on continuous trigger ([ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md)); Demo no-auth + dry-run ([ADR-037](docs/adr/037-phase-2.10-demo-real-data-no-auth.md)).
- **Compute coupling:** Extend **A1** shop jobs to call rules scoring after KPI precompute (same targeted fetch inputs); no second parallel fetch cycle for Decisions-only; inherit shop mutex.
- **Emission budget:** Separate **surfacing** from **recomputation**; persistence model + indexes required (see above); defaults per ADR-038 §6 — config tunable.
- **SoT:** Postgres for candidates + emission state; Redis read-through for public gated GET only.
- **Execution:** Demo dry-run module only — isolated from Partner write workers; real execution deferred to Phase 3 Sign-in / 3.5-D.
- **Credential model:** Mock **production_read** Fujiwa only; Sign-in disabled ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)).
- **ML path:** Phase 2 rules + copy only; ML promotion gates remain Phase 4.
- **UI boundary:** Track B owns suggestion glow, no confidence UI, editable inputs, Juli-handles-all confirm, progress cards, `/decisions` load fixes — this PRD delivers **feed freshness + backend contracts** only.
- **Interactions:** Material webhook / A1 hourly reconcile (/ A2 stagger when present) → shared compute → KPI envelopes + scoring → candidate upsert → emission filter → **optional Redis read-through** → public Demo Decisions GET; Approve on Demo → dry-run module only.

## Testing Decisions

- Test **external behavior:** Action Card candidates after compute jobs; emission budget suppresses active set but allows DB candidates; public GET returns gated list; dry-run never invokes Partner writes or `/v1/executions`; shared trigger runs both KPI and scoring (integration fixture).
- **Prior art:** action-cards refresh tests, scoring pipeline tests, Demo Decisions contract tests, webhook→compute patterns from A1.
- **Default modules under test:** Shared Compute Orchestrator (Decision branch), Rules Scoring Wire, Decision Emission Budget, Action Card persistence on compute, Demo Dry-run Execution, Public Demo Decisions Read API.
- **CI posture:** fixture-driven scoring and emission tests in PR-safe lane; optional live smoke on merge queue after A1 spine green.
- **Negative paths:** scoring failure leaves last-good cards; emission cooldown respects workflow_key terminal actions; approve on Demo does not enqueue real executor tasks with merchant credentials; Redis flush does not wipe candidate/emission SoT.

## Out of Scope

- **A0 Foundation** / **A1 Speed** continuous Analytics spine (prerequisites — [#598](https://github.com/thienphung00/Juli-AI/issues/598), [#601](https://github.com/thienphung00/Juli-AI/issues/601))
- **A2 Batch** fleet reconcile as an exit gate (may refresh candidates later; does **not** block this PRD)
- **Track B Demo UI fix** — trust copy, Decision automation UX polish, `/decisions` hang, contextual assistance format errors ([#600](https://github.com/thienphung00/Juli-AI/issues/600); may ship ahead of feed wire)
- TikTok OAuth, Sign-up, Sign-in, enabling Demo Sign-in control
- Real Partner write execution from public Demo (Login-mode credentialed execution — Phase 3+)
- Trained ML inference / T2/T6/T8 promotion as 3.5-B exit requirement (Phase 4)
- Cloud LLM copy (Haiku) — Phase 4
- Multi-tenant per-visitor shop connect
- Landing Page deploy
- Home/Settings real-data wiring
- Unlimited realtime Decision spam on every webhook (explicitly rejected)
- Separate Decision-only ingest pipeline parallel to Analytics spine
- Treating Redis as emission/candidate SoT (explicitly rejected)
- EXECUTION “Phase 3.5 Full Web Application” dashboard rebuild

## Further Notes

- **Blocking dependency:** Do not start 3.5-B implementation until **A1 Speed (#601)** deployed material handoff + KPI envelope continuous path is verified on Fujiwa Mock Demo (webhook-driven `computed_at` advances on Analytics for five B′ keys).
- **Rollout:** Enable scoring branch on compute jobs behind config flag if needed; verify Decision feed freshness correlates with Analytics envelope updates; coordinate Track B UI ship when feed stable.
- **Observability:** Log scoring invoke reason, emission drops (reason codes), active-set size, dry-run execution IDs; never log tokens/PII.
- **Risks:** Shared Mock snapshot — all visitors see same Decision set; emission budget may feel “slow” to internal testers — document as product intent; Track B UI may ship before feed — set seller expectations in Demo copy.
- **Follow-ups:** Phase 4 ML technique promotion behind same scoring wire; Phase 3 Sign-in real execution; Tune emission thresholds from Fujiwa prove-out data; A2 stagger refreshing candidates post-exit.
