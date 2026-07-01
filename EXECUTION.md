# EXECUTION.md — Single Source of Truth

> **This file is law.** Phases, slices, gates, and scope live here only.  
> **Technical detail lives in Tier 1 component docs; rationale lives in Tier 2 ADRs.**  
> Start every task here, then open **one** component doc from the routing table below.  
> Full index: [`docs/README.md`](docs/README.md)

**Owner:** Product lead · **Last reset:** Phase 2.5 Deployment Architecture (2026-06-29)

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

> Layer KPI mapping: [`visual_layer.md`](docs/visual_layer.md) · [`ml_layer.md`](docs/ml_layer.md) · [`execution_layer.md`](docs/execution_layer.md)  
> Ecosystem layout: [`architecture/migration-plan.md`](docs/architecture/migration-plan.md) · [`architecture/map.md`](docs/architecture/map.md)

---

## Documentation routing

Read **down** the hierarchy — never load peer Tier 1 files unless the task spans domains.

| Tier | When to read | File |
|------|--------------|------|
| **0** | Always | `EXECUTION.md` (this file) |
| **1a** | Subsystem envelopes, ML thresholds, pipeline stages | [`system-design.md`](docs/system-design.md) |
| **1b** | Which data sources are allowed in which phase | [`data-sources.md`](docs/architecture/data-sources.md) |
| **1c** | Which modules/paths exist in the repo | [`map.md`](docs/architecture/map.md) |
| **1d** | Phase 2 pipeline validation — stack, schedule | [`phase-2-mvp.md`](docs/phases/phase-2-mvp.md) |
| **1e** | Phase 2.5 restructure, domains, deploy targets | [`phase-2.5-deployment.md`](docs/phases/phase-2.5-deployment.md) |
| **1f** | Entity schemas, feature definitions | [`data-models/`](docs/data-models/README.md) |
| **1g** | TikTok API ingestion field maps | [`tiktok_api/endpoints.md`](docs/tiktok_api/endpoints.md) |
| **2** | Why a constraint exists | One ADR from [`decisions/`](docs/decisions/README.md) |

**Historical pre-MVP:** [`phase-1-completed.md`](docs/phases/phase-1-completed.md)  
**Phase 3 forward:** [`phase-3-landing-demo.md`](docs/phases/phase-3-landing-demo.md)

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

**Active phase:** Phase 2.5 — Deployment Architecture (docs + scaffold; runtime code moves deferred).

### Architecture evolution (by phase)

| Phase | Stack / product additions |
|-------|---------------------------|
| **2** | FastAPI · Postgres · Redis · Scheduler · **rules-based signal engine** · **rules-based copy** · Celery executors |
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
| **A — Live data pipeline** | TikTok poll → ETL → Postgres → feature aggregates | Pending API approval |
| **B — Rules engine + execution** | Rules-based signals → recommendations → rules copy → Celery executors | Pending API approval |

### Milestone A slices

- [ ] **P2-A1** TikTok API polling live — VP/AHR dual-read gate.
- [ ] **P2-A2** ETL → Postgres reliable; canonical entity persistence.
- [ ] **P2-A3** Feature aggregate build (SQL/Python aggregates — not ML feature matrices for training).

### Milestone B slices

- [ ] **P2-B1** Daily batch rules pipeline (aggregates → rules-based signals → recommendations).
- [ ] **P2-B2** Rules-based copy layer — deterministic templates from rule signals (no cloud LLM).
- [ ] **P2-B3** Swap mock → live rules-based signals + policy alerts.
- [ ] **P2-B4** Celery-backed task execution behind approval (never inline in HTTP handler).
- [ ] **P2-B5** Outcome tracking instrumentation.
- [ ] **P2-B6** Listing approval queue + Products API publish.
- [ ] **P2-B7** Leakage live executors.
- [ ] **P2-B8** Live operations pipeline wiring (rules-based classify → health → rank).
- [ ] **P2-B9** Scoped inventory collection.
- [ ] **P2-B10** Deferred workflow executors.

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

Detail: [`phase-2-mvp.md`](docs/phases/phase-2-mvp.md)

---

## Phase 2.5 — Deployment Architecture (active)

**Goal:** Prepare production deployment architecture before exposing Juli publicly.

Focus: repository restructuring · frontend/backend separation · monorepo organization ·
deployment pipelines · shared packages · real domains · CI/CD · production environment setup.

**Scope of current work:** docs + scaffold only. Runtime code remains in `src/`, `web/`,
and `ios/` until a later migration PR.

**Naming collision:** `src/apps/` is backend entrypoint composition (legacy Python layout).
Top-level `apps/` holds product deployables (landing, demo, dashboard, mobile). See
[`architecture/migration-plan.md`](docs/architecture/migration-plan.md).

### Exit gate → Phase 3

- [x] Target folder structure scaffolded (`apps/`, `packages/`, `backend/`, `infra/`) _(2.5-a)_
- [x] Canonical docs aligned to ecosystem roadmap _(2.5-a)_
- [ ] Frontend and backend independently deployable on intended domains _(2.5-d / 2.5-e)_
- [x] Shared package boundaries documented _(2.5-a)_

Detail: [`phase-2.5-deployment.md`](docs/phases/phase-2.5-deployment.md) ·
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

Detail: [`phase-3-landing-demo.md`](docs/phases/phase-3-landing-demo.md)

---

## Phase 3.5 — Full Mobile-Optimized Web Application (brief)

**Goal:** Transform the demo into the first production web application.

Focus: authentication · connected shops · real backend integration · responsive web app ·
complete product functionality. Replaces the demo while preserving the overall product
experience (`dashboard.app-juli.com`).

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

Detail: [`phase-4.5-realtime.md`](docs/phases/phase-4.5-realtime.md) (supersedes old
[`phase-3-vision.md`](docs/phases/phase-3-vision.md))

---

## Phase 5 — Full Launch (brief)

**Goal:** Production-grade platform.

Focus: security · scalability · monitoring · reliability · billing · production automation ·
operational excellence.

---

## In scope (Phase 2)

TikTok polling · daily batch pipeline · **rules-based signal engine** · rules-based copy ·
Celery workers for tool execution · operations pipeline on live data · outcome tracking ·
Postgres · Redis.

Public frontend, landing page, production deployment, and **trained ML models** are
**not required** in Phase 2.

## Explicitly out (Phase 2)

Trained ML models · backtest inference · model artifact promotion · T1–T8 sklearn training
pipelines · Public users · Landing Page · production deployment · Kafka · WebSockets ·
Webhook ingestion (deferred to 4.5) · Cloud LLM (Haiku / Claude) · Creator matching ·
ClickHouse/S3/SQS · vendor scrapers · Seller Center scraping · buyer PII · unofficial
livestream websockets.

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
