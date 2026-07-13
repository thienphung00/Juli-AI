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
**Phase 3 forward:** [`phase-3-landing-demo.md`](docs/product/phases/phase-3-landing-demo.md)

---

## Phase overview

| Phase | Theme | Users | Exit gate |
|-------|-------|-------|-----------|
| **2 — Pipeline Validation** | End-to-end backend machine | 0 (internal) | Pipeline reliable; execution >95%; outcome tracking works |
| **2.5 — Deployment Architecture** | Monorepo restructure, independent deploys | 0 (internal) | Frontend and backend independently deployable on intended domains |
| **3 — Landing + Interactive Demo** | Qualitative feedback, mock-data storytelling | Public (no login) | Users understand Juli within minutes; complete demo unassisted |
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
| **3** | `apps/landing` · `apps/demo` (mock only) · PostHog behavior analytics |
| **3.5** | `apps/dashboard` · auth · TikTok connection · real API integration |
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
| **A — Live data pipeline** | TikTok poll → ETL → Postgres → feature aggregates | In progress |
| **B — Rules engine + execution** | Rules-based signals → recommendations → rules copy → Celery executors | Pending Milestone A |

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
- [ ] **P2-B3** Swap mock → live rules-based signals + policy alerts. _(#374 — Ads KPIs
      pending Promotion API, tracked separately; other 10 domains live.)_
- [x] **P2-B4** Celery-backed task execution behind approval (never inline in HTTP handler).
      _(#305 — dispatch infra: routing, idempotency, error taxonomy, sandbox guard contract.)_
- [ ] **P2-B5** Outcome tracking instrumentation. _(#306 open — realtime envelope done,
      cadence rollups pending.)_
- [ ] **P2-B6** Listing approval queue + Products API publish. _(#379)_
- [ ] **P2-B7** Leakage live executors. _(#380)_
- [ ] **P2-B8** Live operations pipeline wiring (rules-based classify → health → rank).
      _(folded into the P2-B1 manual-refresh issue, #303 — no separate slice.)_
- [ ] **P2-B9** Scoped inventory collection. _(#381; `sync_inventory` removed from poll cycle.)_
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

- [ ] **Data** — TikTok → Postgres reliable
- [ ] **Signals** — Rule-based signal generation stable
- [ ] **Execution** — Tool execution succeeds >95%
- [ ] **Tracking** — Outcome measurement works

Detail: [`phase-2-mvp.md`](docs/product/phases/phase-2-mvp.md)

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

## Phase 3 — Landing Page + Interactive Demo (brief)

**Goal:** Collect qualitative user feedback with minimal friction.

Focus: Landing Page (`app-juli.com`) · Interactive Demo (`demo.app-juli.com`) · mock data
only · hardcoded demo flows · no login · no account creation · no TikTok connection ·
mobile-first · behavior analytics.

The demo is **storytelling**, not a miniature dashboard. Two primary screens:

| Screen | Purpose |
|--------|---------|
| **Home** | AI Briefing → Analytics (evidence) → Recommendations → Approval → CTA into Actions |
| **Actions** | Pending Approval · Scheduled · In Progress · Completed · Results / Impact |

User journey: Observe → Understand → Recommend → Approve → Execute → Measure.

### Exit gate

- [ ] Users understand Juli within minutes
- [ ] Users complete the demo without assistance

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
