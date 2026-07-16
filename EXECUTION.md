# EXECUTION.md — Single Source of Truth

> **This file is law.** Phases, slices, gates, and scope live here only.  
> **Technical detail lives in Tier 1 component docs; rationale lives in Tier 2 ADRs.**  
> Start every task here, then open **one** component doc from the routing table below.  
> Full index: [`docs/README.md`](docs/README.md)

**Owner:** Product lead · **Last reset:** Phase 2.5 complete → Phase 2 active (2026-07-04)

---

## North star (summary)

**Juli is an execution platform, not an analytics product with recommendations.**

The moat is increasingly automated execution. The critical architecture evolution is not
Dashboard → Analytics → Forecast, but:

```
Data → Decision → Approval → Execution → Outcome
```

**Seller money, not creator matching.** Juli AI is a **Decision Copilot** for TikTok Shop
sellers — ingest shop data, generate signals and recommendations, collect explicit
approval, execute via tools, and measure outcomes. Creator ↔ shop matching is deferred
beyond early user-testing phases.

**Product shape:** Juli AI is an **ecosystem of deployable products**, not a single app.
Shared design system, API client, types, and utilities live in `packages/`; products live
in `apps/`; backend services live in `backend/`.

> Layer KPI mapping: [`visual_layer.md`](docs/ml/visual_layer.md) · [`ml_layer.md`](docs/ml/ml_layer.md) · [`execution_layer.md`](docs/product/execution_layer.md)  
> Ecosystem layout: [`architecture/migration-plan.md`](docs/architecture/migration-plan.md) · [`architecture/map.md`](docs/architecture/map.md)

---

## Documentation routing

Read **down** the hierarchy — never load peer Tier 1 files unless the task spans domains.

| Tier | When to read | File |
|------|--------------|------|
| **0** | Always | `EXECUTION.md` (this file) |
| **1a** | Subsystem envelopes, ML thresholds, pipeline stages | [`system-design.md`](docs/architecture/system-design.md) |
| **1b** | Which data sources are allowed in which phase | [`data-sources.md`](docs/architecture/data-sources.md) |
| **1c** | Which modules/paths exist in the repo | [`map.md`](docs/architecture/map.md) |
| **1d** | Phase 2 pipeline validation — stack, schedule | [`phase-2-mvp.md`](docs/product/phases/phase-2-mvp.md) |
| **1e** | Phase 2.5 restructure, domains, deploy targets | [`phase-2.5-deployment.md`](docs/product/phases/phase-2.5-deployment.md) |
| **1f** | Entity schemas, feature definitions | [`data-models/`](docs/api/data-models/README.md) |
| **1g** | TikTok API ingestion field maps | [`tiktok_api/endpoints.md`](docs/integrations/tiktok_api/endpoints.md) |
| **2** | Why a constraint exists | One ADR from [`decisions/`](docs/adr/README.md) |

**Historical pre-MVP:** [`phase-1-completed.md`](docs/product/phases/phase-1-completed.md)  
**Phase 2.6 — Demo frontend (mock):** [`phase-2.6/PRD.md`](docs/product/phases/phase-2.6/PRD.md)  
**Phase 2.7 — Landing frontend (mock):** [`phase-2.7/PRD.md`](docs/product/phases/phase-2.7/PRD.md)  
**Phase 3 forward:** [`phase-3-landing-demo.md`](docs/product/phases/phase-3-landing-demo.md)

---

## Phase overview

| Phase | Theme | Users | Exit gate |
|-------|-------|-------|-----------|
| **2 — Pipeline Validation** | End-to-end backend machine | 0 (internal) | Pipeline reliable; execution >95%; outcome tracking works |
| **2.5 — Deployment Architecture** | Monorepo restructure, independent deploys | 0 (internal) | Frontend and backend independently deployable on intended domains |
| **2.6 — Demo Frontend (mock)** | `apps/demo` build-out, ADR-023 IA, mock data, public Demo deployment | Public (mock Demo; no auth) | Home + Decisions complete for web + mobile-web and publicly reachable over HTTPS at `demo.app-juli.com`; Mock/Sign-in toggle present (Sign-in non-interactive stub); Analytics (#404) and Settings (#405) non-blocking stretch ([ADR-026](docs/adr/026-phase-2.6-analytics-optional-exit-gate.md)) |
| **2.7 — Landing Frontend (mock)** | `apps/landing` build-out, mock/static content | 0 (internal) | Landing frontend complete for web + mobile-web |
| **3 — Landing + Demo real data** | Wire real backend, deploy Landing, prove e2e pipeline | Public (Demo Sign-in adds OAuth) | LP deployed; Demo upgraded in place with working backend on real data; e2e pipeline proven for both |
| **3.5 — Full Web Application** | Auth, connected shops, real backend | Early adopters | Demo replaced by production web app |
| **4 — ML + LLM + Cross-Platform** | Intelligence, personalization, sync | Growing base | Production ML pipeline; LLM copy; Web ↔ Mobile sync |
| **4.5 — Real-Time Infrastructure** | Latency reduction at scale | Growing base | Real-time updates justified by product scale |
| **5 — Full Launch** | Production-grade platform | Public | Security, billing, monitoring, operational excellence |

**Active phase:** Phase 2 — Pipeline Validation (App Review deploy live on `app-juli.com`; backend runtime in `backend/`).

### Architecture evolution (by phase)

| Phase | Stack / product additions |
|-------|---------------------------|
| **2** | FastAPI · Postgres (sole mandatory store) · **rules-based signal engine** · **rules-based copy** · Celery executors · manual-refresh trigger (no scheduler — [ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md)) |
| **2.5** | Product monorepo (`apps/`, `packages/`, `backend/`, `infra/`) · domain routing · CI/CD |
| **2.6** | `apps/demo` (ADR-023 IA, mock data) · `packages/ui` + `packages/theme` + `packages/contracts` · element→composition UI build order · Mock/Sign-in toggle (Sign-in non-interactive stub) · public HTTPS deployment at `demo.app-juli.com` · Analytics + Settings full depth optional ([ADR-026](docs/adr/026-phase-2.6-analytics-optional-exit-gate.md)) |
| **2.7** | `apps/landing` (mock/static content) · consumes `packages/ui` + `packages/theme` |
| **3** | `apps/demo` + `apps/landing` wired to real backend data · Demo Sign-in mode enabled (reference-shop TikTok OAuth) · deploy Landing to `app-juli.com` · upgrade the existing `demo.app-juli.com` deployment · PostHog behavior analytics |
| **3.5** | `apps/dashboard` ADR-023 rebuild · multi-tenant auth · per-seller TikTok connection · real API integration |
| **4** | Production ML · cloud LLM copy · cross-platform tracking |
| **4.5** | Webhooks · event-driven processing · real-time updates (when justified) |
| **5** | Billing · security hardening · production automation |

Cloud LLM (Haiku) is deferred until Phase 4. Webhooks and WebSockets are deferred until
Phase 4.5 unless product scale justifies earlier adoption.

---

## Phase 2 — Pipeline Validation

**Goal:** Validate the entire backend machine end-to-end with no external users, no landing
page, and no production deployment.

```
TikTok Data → Feature Aggregates → Rules-Based Signal Engine → Recommendation → Execution → Outcome Tracking
```

**Signal layer:** Rules-based only in Phase 2. No trained models, no backtest inference,
no model artifact promotion. Deterministic policy rules, thresholds, and heuristics
produce signals and recommendations. Trained ML (T1–T8) begins in Phase 4.

### Milestones

| Milestone | Focus | Status |
|-----------|-------|--------|
| **A — Live data pipeline** | TikTok poll → ETL → Postgres → feature aggregates | Complete |
| **B — Rules engine + execution** | Rules-based signals → recommendations → rules copy → Celery executors | Complete (FBS; FBT Phase 5) |

**Pre-A1 progress (App Review, 2.5-review):** TikTok OAuth exchange, encrypted credential
persistence (`TikTokCredential` in Postgres), and live API connectivity probe are done.
Scheduled polling, business-entity ETL, and feature aggregates remain pending.

### Milestone A slices

- [x] **P2-A1** TikTok API polling live. _(VP/AHR dual-read gate dropped — not a P2 exit
      gate per `phase-2-mvp.md`; scheduled-poll requirement superseded by manual refresh,
      [ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md).)_
- [x] **P2-A2** ETL → Postgres reliable; canonical entity persistence. _(#299, includes
      webhook catalog ETL handoff, #354.)_
- [x] **P2-A3** Feature aggregate build (SQL/Python aggregates — not ML feature matrices for training). _(#300)_

### Milestone B slices

- [x] **P2-B1** Manual-refresh rules pipeline (aggregates → rules-based signals →
      recommendations → **persisted Action Cards**, [ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md)).
      _(#303 reopened — pipeline logic done, persistence gap.)_
- [x] **P2-B2** Rules-based copy layer — deterministic templates from rule signals (no cloud LLM). _(#304)_
- [x] **P2-B3** Swap mock → live rules-based signals + policy alerts. _(#374 — Ads KPIs
      pending Promotion API, tracked separately; other 10 domains live. Exit gate accepts
      Ads as known gap.)_
- [x] **P2-B4** Celery-backed task execution behind approval (never inline in HTTP handler).
      _(#305 — dispatch infra: routing, idempotency, error taxonomy, sandbox guard contract.)_
- [x] **P2-B5** Outcome tracking instrumentation. _(#306 — realtime envelope shipped;
      daily/weekly/monthly cadence stubs acceptable for Phase 2 exit.)_
- [x] **P2-B6** Listing approval queue + Products API publish. _(#379)_
- [x] **P2-B7** Leakage live executors. _(#380 — inventory/promotion + returns 8a/8b/8c FBS
      + process_order_5; FBT executors deferred Phase 5.)_
- [x] **P2-B8** Live operations pipeline wiring (rules-based classify → health → rank).
      _(folded into the P2-B1 manual-refresh issue, #303 — no separate slice.)_
- [x] **P2-B9** Scoped inventory collection. _(#381; hybrid poll Search Inventory + webhook #68.)_
- [ ] **P2-B10** Deferred workflow executors. _(by design — Affiliate/Livestream/CS/Finance
      prefixes stay ACK-only through Phase 2; no gap, no issue.)_

### Historical ML prep (pre-Phase 2 — not required for exit)

Offline backtest / training work completed during pre-MVP — **out of Phase 2 scope**:

- [x] **P2-ML-1** Backtest dataset assembly (parquet). _(issue: #136)_
- [ ] **P2-ML-2** Router classifier — train + backtest. _(issue: #138 — deferred to Phase 4)_
- [ ] **P2-ML-3** Return-fraud detector — buyer behavior only. _(issue: #139 — deferred to Phase 4)_
- [x] **P2-ML-4** Ads regressor — train + backtest. _(issue: #140 — deferred to Phase 4)_
- [ ] **P2-ML-5** Feature specs + inference signatures. _(issue: #142 — deferred to Phase 4)_
- [x] **P2-ML-6** Serialize models + metadata. _(issue: #141 — deferred to Phase 4)_

### Exit gate → Phase 2.5

- [x] **Data** — TikTok → Postgres reliable _(manual-refresh poll + ETL + inventory;
      ADR-021)_
- [x] **Signals** — Rule-based signal generation stable _(Action Cards persisted;
      Ads KPIs known gap)_
- [x] **Execution** — Tool execution succeeds >95% _(FBS listing/inventory/promotion/
      returns/fulfillment registered + contract-tested; FBT deferred Phase 5)_
- [x] **Tracking** — Outcome measurement works _(realtime envelope; cadence stubs OK)_

Detail: [`phase-2-mvp.md`](docs/product/phases/phase-2-mvp.md) ·
[`phase-2-exit-gate-report.html`](docs/product/phases/phase-2-exit-gate-report.html)

---

## Phase 2.5 — Deployment Architecture (complete)

**Goal:** Prepare production deployment architecture before exposing Juli publicly.

Focus: repository restructuring · frontend/backend separation · monorepo organization ·
deployment pipelines · shared packages · real domains · CI/CD · production environment setup.

**Completed (2026-07-03):** App Review deploy live at `app-juli.com` + `api.app-juli.com`;
backend runtime in `backend/`; legacy `web/` serves review frontend until Phase 3.
Sign-off: [`docs/runbooks/smoke-checklist-runbook.md`](docs/runbooks/smoke-checklist-runbook.md).

**Naming collision:** Top-level `apps/` holds product deployables (landing, demo, dashboard,
mobile). Backend entrypoints live under `backend/api/` and `backend/workers/` — not top-level
`apps/`. See [`architecture/migration-plan.md`](docs/architecture/migration-plan.md).

### Exit gate → Phase 3

- [x] Target folder structure scaffolded (`apps/`, `packages/`, `backend/`, `infra/`) _(2.5-a)_
- [x] Canonical docs aligned to ecosystem roadmap _(2.5-a)_
- [x] Frontend and backend independently deployable on intended domains _(2.5-review, sign-off 2026-07-03)_
- [x] Shared package boundaries documented _(2.5-a)_

Detail: [`phase-2.5-deployment.md`](docs/product/phases/phase-2.5-deployment.md) ·
[`architecture/migration-plan.md`](docs/architecture/migration-plan.md)

---

## Phase 2.6 — Demo Frontend, Mock Data (brief)

**Goal:** Build the Interactive Demo's frontend end-to-end on mock data and deploy it
publicly at `demo.app-juli.com`, before any backend wiring or authentication.

Focus: new `apps/demo` · ADR-023 four-destination IA (Home, Decisions, Analytics,
Settings) — **not** the retired two-screen Home+Actions IA · one responsive Next.js
codebase covering web + mobile-web breakpoints (`design.md`: mobile-web below `42rem`,
web at/above `56rem`) · Mock/Sign-in mode toggle with Sign-in as a **non-interactive,
always-visible "coming soon" stub** · `packages/ui` + `packages/theme` +
`packages/contracts` built element→composition-first before consuming screens ·
independent public deployment with DNS + HTTPS at `demo.app-juli.com`
([ADR-024](docs/adr/024-phase-2.6-2.7-frontend-resequencing.md),
[ADR-026](docs/adr/026-phase-2.6-analytics-optional-exit-gate.md)).

Out of scope: real backend calls and real TikTok OAuth (Phase 3); login/onboarding and
Affiliate/Seller mode switching (`Flows/home/login.md`, `Flows/home/onboarding.md`).

### Exit gate

- [ ] `apps/demo` implements Home and Decisions (all nine workflows) per
      `docs/product/design/` on mock data; four-destination shell keeps Analytics and
      Settings discoverable with truthful placeholders if full depth has not shipped
- [ ] Mock mode fully interactive with no auth required; Sign-in mode present as a
      non-interactive, always-visible "coming soon" stub (no route/OAuth/backend call)
- [ ] Workflow 1 is the default Priority Card; Workflows 2–9 remain visible below it in
      stable specification order; global Manual Refresh resets mock state and returns to
      Decisions → Recommendations
- [ ] Verified responsive on web (`56rem`+) and mobile-web (below `42rem`) breakpoints
      via Playwright for the mandatory Decisions journey
- [ ] `packages/ui` + `packages/theme` + `packages/contracts` populated and consumed by
      `apps/demo` (exit checks the subset of primitives actually used by shipped screens)
- [ ] `https://demo.app-juli.com` publicly resolves, serves `apps/demo` over valid HTTPS,
      and passes desktop + mobile-web smoke checks on the Decisions route without
      requests to `backend/`, TikTok, or OAuth endpoints

**Non-blocking stretch goals** (truthful placeholder sufficient; do not block sign-off):

- Full editable Settings templates/thresholds (#405)
- Full six-KPI Analytics experience (#404,
  [ADR-026](docs/adr/026-phase-2.6-analytics-optional-exit-gate.md))

Detail: [`phase-2.6/PRD.md`](docs/product/phases/phase-2.6/PRD.md)

---

## Phase 2.7 — Landing Frontend, Mock Data (brief)

**Goal:** Build the marketing Landing Page's frontend end-to-end on mock/static content,
before public deployment.

Focus: new `apps/landing` · own IA (not part of `docs/product/design`'s four-destination
scope) defined in the Phase 2.7 PRD · reuses `docs/product/design` visual tokens and
brand voice (`design.md`, `soul.md`, `colors_and_type.css`) for consistency only · one
responsive Next.js codebase covering web + mobile-web breakpoints · consumes
`packages/ui` + `packages/theme` from Phase 2.6.

Out of scope: real backend calls, public deployment (Phase 3).

### Exit gate

- [ ] `apps/landing` sections built (hero, product story, CTA → Demo) on mock/static
      content
- [ ] Verified responsive on web and mobile-web breakpoints
- [ ] Visual tokens/voice consistent with `docs/product/design`

Detail: [`phase-2.7/PRD.md`](docs/product/phases/phase-2.7/PRD.md)

---

## Phase 3 — Landing Page + Demo, Real Data (brief)

**Goal:** Wire the already-built (Phase 2.6/2.7) frontends to a working backend using
real data, deploy the Landing Page, upgrade the existing public Demo deployment, and
prove the end-to-end pipeline for both surfaces.

Focus: deploy `apps/landing` to `app-juli.com` (replacing the temporary App Review
placeholder) · upgrade the Phase 2.6 `apps/demo` deployment at `demo.app-juli.com` ·
enable `apps/demo`'s Sign-in mode
(real TikTok OAuth connect + real backend data for one pre-connected reference shop,
per [ADR-024](docs/adr/024-phase-2.6-2.7-frontend-resequencing.md)) · Mock mode remains
available · behavior analytics (PostHog).

Per-visitor/self-serve TikTok connection and multi-tenant account management remain
Phase 3.5 scope — Phase 3's Sign-in mode uses one reference shop only.

### Exit gate

- [ ] `apps/landing` deployed and publicly reachable at `app-juli.com`; the existing
      `demo.app-juli.com` deployment remains healthy through the real-data upgrade
- [ ] `apps/demo` Sign-in mode shows real backend data (Phase 2 pipeline output) for the
      reference shop end-to-end
- [ ] End-to-end pipeline (poll/ETL → aggregates → signals → recommendations → Action
      Cards) proven live for the Demo; Landing Page CTA flow to Demo verified
- [ ] Engagement and messaging metrics collected via PostHog

Detail: [`phase-3-landing-demo.md`](docs/product/phases/phase-3-landing-demo.md)

---

## Phase 3.5 — Full Mobile-Optimized Web Application (brief)

**Goal:** Transform the demo into the first production web application.

Focus: authentication · connected shops · real backend integration · responsive web app ·
complete product functionality. Replaces the demo while preserving the overall product
experience (`dashboard.app-juli.com`).

Legacy `web/` dashboard retains **3-tab Decision Copilot IA** ([ADR-014](docs/adr/014-decision-copilot-app-structure-and-journey.md))
until migration to `apps/dashboard`.

---

## Phase 4 — ML Pipeline + LLM + Cross-Platform Tracking (brief)

**Goal:** Increase intelligence rather than adding more dashboards.

Focus: production ML pipeline · LLM-generated recommendations · personalized recommendation
copy · cross-platform analytics · user behavior tracking · Web ↔ Mobile synchronization.

---

## Phase 4.5 — Real-Time Infrastructure (brief)

**Goal:** Reduce latency throughout the product when justified by scale.

Potential additions: webhooks · event-driven processing · real-time updates · live execution
tracking · streaming architecture. Implement only when product scale justifies cost.

Detail: [`phase-4.5-realtime.md`](docs/product/phases/phase-4.5-realtime.md) (supersedes old
[`phase-3-vision.md`](docs/product/phases/phase-3-vision.md))

---

## Phase 5 — Full Launch (brief)

**Goal:** Production-grade platform.

Focus: security · scalability · monitoring · reliability · billing · production automation ·
operational excellence.

---

## In scope (Phase 2)

TikTok polling · webhook ingestion (catalog #354, converges through the same ETL as
polling) · manual-refresh rules pipeline (no scheduler — [ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md))
· **rules-based signal engine** · rules-based copy · Postgres-persisted Action Cards ·
Celery workers for tool execution · operations pipeline on live data · outcome tracking ·
Postgres (sole mandatory store).

Public frontend, landing page, production deployment, and **trained ML models** are
**not required** in Phase 2. Redis is **optional** (future read-through cache only, never
system of record — [ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md)).

## Explicitly out (Phase 2)

Trained ML models · backtest inference · model artifact promotion · T1–T8 sklearn training
pipelines · Public users · Landing Page · production deployment · Kafka · WebSockets ·
**Cron / Celery Beat / any scheduler** (manual refresh only — [ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md))
· Cloud LLM (Haiku / Claude) · Creator matching · ClickHouse/S3/SQS · vendor scrapers ·
Seller Center scraping · buyer PII · unofficial livestream websockets.

> **Correction (2026-07-13):** webhook ingestion was previously listed here as "deferred to
> 4.5." That was stale — the Phase 2 webhook catalog (#354) shipped, is tested, and the
> signal/execution architecture depends on it. See [ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md).

---

## Governance

| Change | Update | Owner |
|--------|--------|-------|
| Code ships | Link PR to EXECUTION slice | Eng lead |
| Slice completes | Checkbox `[x]` here | Eng + Product |
| Phase gate passed | Advance phase | Product lead |
| Data source added | `data-sources.md` only | Eng lead |
| Entity schema change | `data-models/` only | Eng lead |
| Subsystem envelope change | `system-design.md` only | Eng lead |
| New/changed module | `map.md` only | Eng lead |
| Architecture decision | New ADR + index row | Eng lead |
| Repo layout / migration | `migration-plan.md` only | Eng lead |

### Conflict resolution

```
Code  >  EXECUTION.md  >  Tier 1 component doc  >  ADR
```

Historical phase docs (`phase-3-vision.md`, `phase-4-beta-launch.md`, `phase-5-public-launch.md`)
are **not authoritative** — retained for traceability only.
