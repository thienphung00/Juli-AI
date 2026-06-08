# EXECUTION.md — Single Source of Truth

> **This file is law.** It is the only execution plan for Juli-AI. It chains to
> GitHub issues (per-slice) and to [`docs/system-design.md`](docs/system-design.md)
> for technical design — nothing else. If any other doc disagrees with this file,
> this file wins (see [Conflict resolution](#conflict-resolution)).

**Owner:** Product lead · **Status updates:** Eng lead per PR · **Last reset:** Phase 1, Week 1

---

## North star

**Seller money, not creator matching.** Juli-AI helps TikTok Shop sellers
**make and keep more money** through three agentic workflows:

1. **New Seller Copilot** — get a new seller to first profitable sales.
2. **Revenue Leakage Detection** — catch buyer-behavior return anomalies (item swaps, empty returns) and policy-driven leakage (refunds, commission disputes).
3. **Growth Copilot** — improve ad ROAS and scale what works.

Rescope rationale: validate that these workflows resonate with real sellers
**before** spending engineering on ML. UX viability first, then models, then live data.

> Creator ↔ Shop matching is **Phase 3+** and explicitly out of the next 13 weeks.
> Its prior design lives in ADR history ([ADR-006](docs/decisions/006-matching-pivot.md),
> [ADR-007](docs/decisions/007-ml-north-star-models.md)) — superseded by this rescope.

---

## Phase overview

| Phase | Weeks | Theme | Data | ML | Exit gate |
|-------|-------|-------|------|----|-----------|
| **Phase 1** | 1–6 | UI for all three workflows | Mock JSON | none | UX validated with 100 test sellers |
| **Phase 1.5** | 6–9 | Train + validate 3 model suites | Backtest (parquet) / synthetic | trained, serialized | precision/recall on backtest meets targets |
| **Phase 1.6** | 9–10 | New Seller listing workflow (executable) | Mock fixtures | none | E2E `list_products` → export |
| **Phase 1.7** | 10–11 | Revenue Leakage workflow (executable) | Mock fixtures | none | E2E leakage task → mock execute |
| **Phase 2** | 11–15 | Real APIs + daily inference + Ollama copy + live execution | TikTok API polling | production inference + Ollama (copy layer) | 50 live sellers, zero critical bugs, 2 weeks stable |

**Parallel track:** TikTok API polling setup proceeds alongside Phase 1 (mock feed
in P1, real data wired in P2).

Phase progression is **gated**: a phase does not start until the prior phase's exit
gate passes. When a gate passes, the Product lead checks the criteria, advances the
phase, and resets the timeline.

---

## Phase 1 — UI + Mock Data (Weeks 1–6)

**Goal:** Ship mockup UI for all three workflows, populated with realistic mock
data. Validate UX with 100 test sellers. No real API calls. No ML.

**Design reference:** [`docs/system-design.md`](docs/system-design.md) → Phase 1 columns.

**Metrics:** UX engagement — task clicks, approval-flow completions.

### Slices

- [ ] **P1-0** Workspace mode — Seller (dark) vs Affiliate (light); Affiliate shows Out of Scope. _(issue: #104)_
- [ ] **P1-1** Mock data schemas — fixtures from [`docs/data-models/canonical-entities.md`](docs/data-models/canonical-entities.md) + [`mock-data-generator.md`](docs/data-models/mock-data-generator.md). _(issue: #103)_
- [x] **P1-2** New Seller Copilot UI (mocked) — onboarding → first-sale task flow. _(issue: #119, PR #130)_
- [x] **P1-3** Revenue Leakage Detection UI (mocked) — return anomalies (item swap, empty return) + policy signals surfacing + recommended fix. _(issue: #120, PR #131)_
- [x] **P1-4** Growth Copilot UI (mocked) — ad performance read + scale/cut suggestions. _(issue: #121)_
- [ ] **P1-5** Executor approval flow (no-op) — task approve/dismiss UX with no backend action. _(issue: #106)_
- [ ] **P1-6** Rules-based seller-stage detection (agent decision tree, mocked input). _(issue: #105)_
- [x] **P1-7** UX instrumentation — task-click + approval analytics for the 100-seller test. _(issue: #122)_

### Exit gate → Phase 1.5

- [ ] Mockup UI live for all three workflows
- [ ] 100 test sellers exercised the flows
- [ ] Workflows confirmed to resonate (engagement threshold met — set by Product lead)

---

## Phase 1.5 — ML Models (Weeks 6–9)

**Goal:** Train three model suites and validate on historical/synthetic data. No
production inference; UX still mocked.

**Design reference:** [`docs/system-design.md`](docs/system-design.md) → Phase 1.5 columns.

**Data source:** Historical TikTok Shop data (backtest set) or synthetic if unavailable.

**Validation:** Backtest on Q4 / Q1 historical orders; measure precision/recall
against ground truth (labeled item_swap / empty_return cases, documented return patterns).

**Outputs:** Serialized models (pickle/joblib), feature specs, inference signatures.

**Metrics:** Model performance — precision/recall on backtest.

### Slices

- [x] **P1.5-1** Backtest dataset assembly (parquet) — canonical entities per [`docs/data-models/`](docs/data-models/README.md); synthetic labels via [`mock-data-generator.md`](docs/data-models/mock-data-generator.md) (`item_swap`, `empty_return`). _(issue: #136, PR #144)_
- [ ] **P1.5-2** Seller stage classifier — train + backtest. _(issue: #138)_
- [ ] **P1.5-3** Anomaly detector — buyer behavior only (`item_swap`, `empty_return`) — train + backtest vs labeled cases. _(issue: #139)_
- [x] **P1.5-4** Ad performance analyzer — train + backtest. _(issue: #140)_
- [ ] **P1.5-5** Feature specs + inference signatures in [`docs/data-models/feature-store-schema.md`](docs/data-models/feature-store-schema.md); cross-linked from `system-design.md`. _(issue: #142)_
- [x] **P1.5-6** Serialize models + metadata (train date, row count, feature schema hash, metrics). _(issue: #141)_
- [x] **P1.5-7** Publish [`docs/architecture/target-v2.md`](docs/architecture/target-v2.md) — Phase 2 target design (real APIs + inference pipeline). _(issue: #143)_

### Exit gate → Phase 1.6

- [ ] All three model suites trained and serialized
- [ ] Precision/recall meets targets on backtest (thresholds recorded in system-design.md)
- [x] `target-v2.md` published

> **Note:** P1.6 shipped on mock fixtures while P1.5-2/3/5 remain open — ML gate does
> not block executable UX phases (P1.6, P1.7). Phase 2 still requires full P1.5 gate.

---

## Phase 1.6 — New Seller Listing Workflow (Weeks 9–10)

**Goal:** First **executable** New Seller Copilot task — approve `list_products` → dual-path
listing workflow → draft review → CSV/JSON export. Mock fixtures + rules-only generation.
No cloud LLM, no Postgres, no TikTok API.

**Design reference:** [`docs/system-design.md`](docs/system-design.md) → Phase 1.6 columns.
**ADR:** [ADR-020](docs/decisions/020-new-seller-listing-workflow-scope.md).

**Metrics:** E2E listing completion rate; Path A vs Path B selection.

### Slices

- [x] **P1.6-1** Mock workflow fixtures — `ProductDraft`, `Distributor`, `Opportunity` catalogs. _(issue: #153, PR #158)_
- [x] **P1.6-2** E2E listing workflow UI — dual-path state machine from approved `list_products`. _(issue: #155, PR #160)_
- [x] **P1.6-3** Rules-based listing generation — extraction, compliance, readiness score. _(issue: #154, PR #159)_
- [x] **P1.6-4** CSV/JSON export — execute step from `ProductDraft`. _(issue: #156, PR #161)_
- [x] **P1.6-5** Mock shop-progress tracking — listing milestone + task card widget. _(issue: #157, PR #162)_

### Exit gate → Phase 1.7

- [x] E2E listing flow: recommend → approve → Path A **or** Path B → forms → execute (export)
- [x] Both paths exercised with deterministic fixtures
- [x] Shop-progress widget updates after export

---

## Phase 1.7 — Revenue Leakage Executable Workflow (Weeks 10–11)

**Goal:** First **executable** Revenue Leakage workflow — approve leakage task → modal
stepper (detail → evidence → root cause → action → mock execute → success). Mock
fixtures only; simulate Phase 2 operational UX. No TikTok API, no ML inference, no Postgres.

**Design reference:** [`docs/system-design.md`](docs/system-design.md) → Phase 1.7 columns.
**ADR:** [ADR-025](docs/decisions/025-revenue-leakage-workflow-scope.md).

**Metrics:** E2E leakage workflow completion per task type; step-transition analytics;
dismiss reasons (global executor).

### Slices

- [x] **P1.7-1** Leakage workflow fixtures + schemas — `LeakageWorkflowTask`, evidence bundles, root cause, execution plan; align `leakage-persona.ts` task types (`buyer_cancellation_cluster`, `return_window_policy`). _(issue: #164)_
- [x] **P1.7-2** Leakage state machine + `useLeakageWorkflow` hook — step graph, session resume, `canAdvance`. _(issue: #165)_
- [ ] **P1.7-3** `LeakageWorkflowPanel` modal UI — four task-type step renderers (mirror `ListingWorkflowPanel`). _(issue: #166)_
- [ ] **P1.7-4** Executor integration — approve opens workflow; **global** skip-with-reason; complete → session disposition. _(issue: #167)_
- [ ] **P1.7-5** Integration tests + UX instrumentation — happy path per type, PII guard, step events. _(issue: #168)_

### Exit gate → Phase 2

- [ ] All four leakage task types completable E2E through success screen
- [ ] Evidence step enforces masked IDs (no PII)
- [ ] Skip-with-reason works on all three workflows
- [ ] Product lead confirms operational UX resonates (same engagement bar as P1)

---

## Phase 2 — Real APIs + Daily Inference (Weeks 11–15)

**Goal:** Wire TikTok API, run daily batch inference, deploy **Ollama** for the
copy layer, swap mock data → real inferences in the UI, enable live task execution.

**Design reference:** [`docs/system-design.md`](docs/system-design.md) → Phase 2 columns,
plus `docs/architecture/target-v2.md` (published end of Phase 1.5).

**APIs:** TikTok Orders, Products, Affiliate, Ads.

**Platform policy (VN):** Seller VP/AHR account health, affiliate enrollment gates,
balance withholding, and creator commission dispute signals — sourced from
[`docs/tiktok_platform/`](docs/tiktok_platform/README.md) implementation hooks.
VP → AHR transition (May–July 2026) overlaps Phase 2; dual-read required until
July 2026 cutover ([ADR-009](docs/decisions/009-dual-read-vp-ahr-transition.md)).

**Inference:** Daily batch — models score live seller data at **08:00 UTC**.

**Copy layer (Ollama):** Local Ollama turns structured ML/rules signals into
seller-facing copy (summarize + localize). Runs after inference, before UI render.
**Rules fallback** on timeout, error, or daily token budget exceeded — API and
task delivery must not block on Ollama availability.

**Metrics:** Revenue impact — recovered refunds, avoided cancellations, improved ROAS.

### Slices

- [ ] **P2-1** TikTok API polling live — Orders, Products, Affiliate, Ads; daily seller
  account health (VP + AHR dual-read during transition, **if exposed**). _(issue: TBD)_
  - **Gate:** Verify VP/AHR/withholding/violation fields via Partner Center API Reference + **API Testing Tool** (login required). If not exposed, implement `health_data_source: api | proxy | unavailable` and degrade explicitly (no Seller Center scraping).
- [ ] **P2-2** Daily batch inference job (08:00 UTC) scoring live seller data. _(issue: TBD)_
- [ ] **P2-3** Ollama copy layer — local inference client, prompt templates from structured signals, Vietnamese localization, rules fallback templates, daily budget cap. _(issue: TBD)_
- [ ] **P2-4** Swap mock → real inferences + Ollama copy in all three workflow UIs;
  surface platform-policy alerts (VP/AHR milestones, balance withholding, commission
  dispute holds, appeal-window expiry). _(issue: TBD)_
- [ ] **P2-5** Live task execution — real triggers behind the approval flow (generic executor). _(issue: TBD)_
- [ ] **P2-6** Revenue-impact instrumentation (recovered refunds, avoided cancellations, ROAS lift). _(issue: TBD)_
- [ ] **P2-7** Listing approval queue — gate `ProductDraft` publish blast radius. _(issue: TBD)_
- [ ] **P2-8** Products API publish executor — live listing from approved drafts. _(issue: TBD)_
- [ ] **P2-9** Leakage approval queue — gate listing-update / settings / support-case executors. _(issue: TBD)_
- [ ] **P2-10** Leakage live executors — Products API listing update, support case draft submit, shop settings. _(issue: TBD)_

### Exit gate → done / next phase

- [ ] 50 live sellers
- [ ] Zero critical bugs
- [ ] 2 weeks stable in production
- [ ] Ollama copy layer live with verified rules fallback (simulate Ollama offline)

---

## In scope (next 15 weeks)

- ✅ Phase 1 (Weeks 1–6): UI for three workflows + mock data
- ✅ Phase 1.5 (Weeks 6–9): Train and validate three ML model suites
- ✅ Phase 1.6 (Weeks 9–10): New Seller listing executable workflow (mock)
- ✅ Phase 1.7 (Weeks 10–11): Revenue Leakage executable workflow (mock)
- ✅ Phase 2 (Weeks 11–15): Real API polling + daily inference + Ollama copy layer + live task execution
- ✅ Parallel: TikTok API polling setup (mock feed in P1, real data in P2)

## Explicitly out

- ❌ Celery / multi-node workers (v2.0)
- ❌ Kafka real-time streams ([ADR-004](docs/decisions/004-etl-kafka-consumer.md), Phase 3+)
- ❌ Creator ↔ Shop matching (Phase 3+)
- ❌ Vendor scraper training (Kalodata / Shoplus / FastMoss, Phase 2.5+)
- ❌ Seller Center scraping, buyer PII, realtime unofficial streams (**permanently forbidden**)
- ❌ Web analytics dashboard, iOS parity, nav redesign
- ❌ Seller OS / CRM as standalone features
- ❌ Folder reshaping of `src/` (deferred to Phase 2.5)

---

## Governance

**EXECUTION.md is law.** Every change links back to a slice here.

| Change | Updates required | Owner |
|--------|------------------|-------|
| Code ships | Link GitHub PR to the relevant EXECUTION.md slice + update status | Eng lead |
| Slice completes | Move checkbox to `[x]` in EXECUTION.md | Eng lead + Product lead |
| Phase gate passed | Check gate criteria, advance phase, reset timeline | Product lead |
| Data source added | Update [`data-sources.md`](docs/architecture/data-sources.md) + [`system-design.md`](docs/system-design.md) + link to the EXECUTION.md phase | Eng lead |
| Canonical entity / feature schema change | Update [`docs/data-models/`](docs/data-models/README.md) + sync `system-design.md` + `data-sources.md` if source rows affected | Eng lead |
| Platform policy change | Update [`docs/tiktok_platform/`](docs/tiktok_platform/README.md) via `platform-docs`, then sync `data-sources.md` operational rules + [`system-design.md`](docs/system-design.md) policy signals | Eng lead |
| Architecture change | Update [`map.md`](docs/architecture/map.md) + cross-reference the EXECUTION.md slice driving it | Eng lead |

### Conflict resolution

Order of authority:

```
Code  >  EXECUTION.md  >  docs/system-design.md  >  docs/architecture/map.md
```

If **code** disagrees with EXECUTION.md, update EXECUTION.md in the next PR — it is
a **contract with the team, not gospel**. If two docs disagree, the higher-authority
file wins and the lower one is corrected in the same PR.

---

## Canonical doc map

| File | Role |
|------|------|
| `EXECUTION.md` (this file) | Single source of truth — phases, slices, gates, governance |
| [`docs/system-design.md`](docs/system-design.md) | Agent decision tree, data pipeline, ML models, executor — mapped to phase gates |
| [`docs/architecture/map.md`](docs/architecture/map.md) | As-built reality — deployed modules, jobs, endpoints |
| [`docs/architecture/data-sources.md`](docs/architecture/data-sources.md) | Single data-status matrix, phase-aligned |
| [`docs/data-models/`](docs/data-models/README.md) | Canonical entity schemas, feature store, mock/synthetic data generator — ML schema authority ([ADR-012](docs/decisions/012-entity-centric-data-model.md)) |
| [`docs/tiktok_platform/`](docs/tiktok_platform/README.md) | Seller/creator feature guides + policy center — implementation hooks for alerts, gates, ETL |
| `docs/architecture/target-v2.md` | Phase 2 target design — **created end of Phase 1.5** |
