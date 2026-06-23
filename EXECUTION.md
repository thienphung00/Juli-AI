# EXECUTION.md — Single Source of Truth

> **This file is law.** Phases, slices, gates, and scope live here only.  
> **Technical detail lives in Tier 1 component docs; rationale lives in Tier 2 ADRs.**  
> Start every task here, then open **one** component doc from the routing table below.  
> Full index: [`docs/README.md`](docs/README.md)

**Owner:** Product lead · **Last reset:** Phase 2 Pipeline Validation (pre-MVP exit gate passed 2026-06-19)

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

**Product shape:** Visual layer (Home KPIs) → ML layer (T1–T8 advisory) → Execution layer
(workflow taxonomy). Pipeline spine: classify → health → rank → reason → approve → execute → track.

> Layer KPI mapping: [`visual_layer.md`](docs/visual_layer.md) · [`ml_layer.md`](docs/ml_layer.md) · [`execution_layer.md`](docs/execution_layer.md)  
> Pipeline + IA decisions: ADR-013 · ADR-014 · ADR-011 (see [`decisions/`](docs/decisions/README.md))

---

## Documentation routing

Read **down** the hierarchy — never load peer Tier 1 files unless the task spans domains.

| Tier | When to read | File |
|------|--------------|------|
| **0** | Always | `EXECUTION.md` (this file) |
| **1a** | Subsystem envelopes, ML thresholds, pipeline stages | [`system-design.md`](docs/system-design.md) |
| **1b** | Which data sources are allowed in which phase | [`data-sources.md`](docs/architecture/data-sources.md) |
| **1c** | Which modules/paths exist in the repo | [`map.md`](docs/architecture/map.md) |
| **1d** | Phase 2 stack diagram, daily UTC schedule, deployment | [`phase-2-mvp.md`](docs/phases/phase-2-mvp.md) |
| **1e** | Entity schemas, feature definitions | [`data-models/`](docs/data-models/README.md) |
| **1f** | TikTok API ingestion field maps | [`tiktok_api/endpoints.md`](docs/tiktok_api/endpoints.md) |
| **2** | Why a constraint exists | One ADR from [`decisions/`](docs/decisions/README.md) |

**Historical pre-MVP:** [`phase-1-completed.md`](docs/phases/phase-1-completed.md) · **Phase 3 forward:** [`phase-3-vision.md`](docs/phases/phase-3-vision.md)

---

## Phase overview

| Phase | Theme | Shops | Exit gate |
|-------|-------|-------|-----------|
| **Phase 2 — Pipeline Validation** | End-to-end machine: data → signal → recommendation → execution → outcome | 0 (internal) | Pipeline reliable; execution >95%; outcome tracking works |
| **Phase 3 — First User Testing** | User behavior: trust, approval, execution rate | 10 | Sellers connect, open reports, approve, and execute |

**Phase 2 architecture (diagram + schedule):** [`phase-2-mvp.md`](docs/phases/phase-2-mvp.md)  
**Phase 3 user-testing scope:** [`phase-3-vision.md`](docs/phases/phase-3-vision.md)

### Architecture evolution (by phase)

| Phase | Stack additions |
|-------|-----------------|
| **2** | FastAPI · Postgres · Redis · **Celery** · Scheduler · **rules-based copy** |
| **3** | + Web app · PostHog · rules-based copy (carried forward) |

Celery is introduced in Phase 2 because execution is core — tool calls must never block
`POST /execute`. Cloud LLM (Haiku) is deferred until beta (see forward phase docs under
`docs/phases/`). Webhooks and WebSockets are deferred likewise.

---

## Phase 2 — Pipeline Validation (active)

**Goal:** Validate the entire machine end-to-end with no external users.

```
TikTok Data → Feature Store → Signal Engine → Recommendation → Execution → Outcome Tracking
```

Success means this loop works reliably:

```
Input Data → Generated Action → Executed Action → Outcome Measured
```

### Milestones

| Milestone | Focus | Status |
|-----------|-------|--------|
| **A — Display-grade analytics** | T1–T8 backtest, artifact promotion, feature specs | In progress |
| **B — Live data + execution** | Live poll → inference → rules copy → Celery executors | Pending API approval |

### Milestone A slices

- [x] **P2-A1** Backtest dataset assembly (parquet). _(issue: #136)_
- [ ] **P2-A2** Router classifier — train + backtest. _(issue: #138)_
- [ ] **P2-A3** Return-fraud detector — buyer behavior only. _(issue: #139)_
- [x] **P2-A4** Ads regressor — train + backtest. _(issue: #140)_
- [ ] **P2-A5** Feature specs + inference signatures. _(issue: #142)_
- [x] **P2-A6** Serialize models + metadata. _(issue: #141)_

### Milestone B slices

- [ ] **P2-B1** TikTok API polling live — VP/AHR dual-read gate.
- [ ] **P2-B2** Daily batch inference pipeline (feature build → signals → recommendations).
- [ ] **P2-B3** Rules-based copy layer — deterministic templates from ML signals (no cloud LLM).
- [ ] **P2-B4** Swap mock → real inferences + policy alerts.
- [ ] **P2-B5** Celery-backed task execution behind approval (never inline in HTTP handler).
- [ ] **P2-B6** Outcome tracking instrumentation.
- [ ] **P2-B7** Listing approval queue + Products API publish.
- [ ] **P2-B8** Leakage live executors.
- [ ] **P2-B9** Live operations pipeline wiring.
- [ ] **P2-B10** Scoped inventory collection.
- [ ] **P2-B11** Deferred workflow executors.

### Exit gate → Phase 3

Must prove:

- [ ] **Data** — TikTok → Postgres reliable
- [ ] **ML** — Signal generation stable
- [ ] **Execution** — Tool execution succeeds >95%
- [ ] **Tracking** — Outcome measurement works

---

## Phase 3 — First User Testing (brief)

**Goal:** Validate user behavior — do sellers trust and execute recommendations?

Not "can we generate recommendations?" (solved in Phase 2). Instead: activation,
engagement, trust, and **execution rate** as the core product metric.

Architecture: Web app · REST · Postgres · Redis · Celery · PostHog · rules-based copy.
Still no WebSockets, no Kafka, no cloud LLM. Recommendations refresh 1×/day. Detail:
[`phase-3-vision.md`](docs/phases/phase-3-vision.md).

### Exit gate

- [ ] 10 connected shops
- [ ] Daily report opened (engagement)
- [ ] Recommendations approved (trust)
- [ ] Actions executed (core metric — if viewed but not executed, product failed)

---

## In scope (Phase 2)

TikTok polling · daily batch pipeline (sync → features → recommendations) · rules-based
summarization and recommendation copy from ML outputs · Celery workers for tool execution ·
operations pipeline on live data · outcome tracking · Railway/VPS (app + worker + scheduler) ·
Postgres · Redis.

Public frontend is **not required** in Phase 2 — internal validation only.

## Explicitly out (Phase 2)

Kafka · WebSockets · Webhook ingestion · Cloud LLM (Haiku / Claude) · Creator matching ·
ClickHouse/S3/SQS · vendor scrapers · Seller Center scraping · buyer PII · unofficial
livestream websockets · inventory/finance **management** (signals only for Stockout Prevention).

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

### Conflict resolution

```
Code  >  EXECUTION.md  >  Tier 1 component doc  >  ADR
```
