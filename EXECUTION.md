# EXECUTION.md — Single Source of Truth

> **This file is law.** Phases, slices, gates, and scope live here only.  
> **Technical detail lives in Tier 1 component docs; rationale lives in Tier 2 ADRs.**  
> Start every task here, then open **one** component doc from the routing table below.  
> Full index: [`docs/README.md`](docs/README.md)

**Owner:** Product lead · **Last reset:** Phase 2 MVP (pre-MVP exit gate passed 2026-06-19)

---

## North star (summary)

**Seller money, not creator matching.** Juli AI is a **Decision Copilot** for TikTok Shop
sellers — analyze shop data, recommend workflows with impact estimates, collect explicit
approval, then execute. Creator ↔ shop matching is **Phase 3+**.

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
| **1d** | MVP stack diagram, daily UTC schedule, deployment | [`phase-2-mvp.md`](docs/phases/phase-2-mvp.md) |
| **1e** | Entity schemas, feature definitions | [`data-models/`](docs/data-models/README.md) |
| **1f** | TikTok API ingestion field maps | [`tiktok_api/endpoints.md`](docs/tiktok_api/endpoints.md) |
| **2** | Why a constraint exists | One ADR from [`decisions/`](docs/decisions/README.md) |

**Historical pre-MVP:** [`phase-1-completed.md`](docs/phases/phase-1-completed.md) · **Phase 3 forward:** [`phase-3-vision.md`](docs/phases/phase-3-vision.md)

---

## Phase overview

| Phase | Theme | Exit gate |
|-------|-------|-----------|
| **Phase 2 MVP** | Live TikTok data + daily inference + Haiku copy + approved execution | 50 live sellers, zero critical bugs, 2 weeks stable |
| **Phase 3.0** | Real-time, LIVE API, polyglot data plane | TBD |

**MVP architecture (diagram + schedule):** [`phase-2-mvp.md`](docs/phases/phase-2-mvp.md)

---

## Phase 2 MVP — Active

**Goal:** TikTok API polling → ETL → daily batch inference → Haiku copy → live executors.

### Milestones

| Milestone | Focus | Status |
|-----------|-------|--------|
| **A — Display-grade analytics** | T1–T8 backtest, artifact promotion, feature specs | In progress |
| **B — Live data + execution** | Live poll → inference → Haiku → executors | Pending API approval |

### Milestone A slices

- [x] **P2-A1** Backtest dataset assembly (parquet). _(issue: #136)_
- [ ] **P2-A2** Router classifier — train + backtest. _(issue: #138)_
- [ ] **P2-A3** Return-fraud detector — buyer behavior only. _(issue: #139)_
- [x] **P2-A4** Ads regressor — train + backtest. _(issue: #140)_
- [ ] **P2-A5** Feature specs + inference signatures. _(issue: #142)_
- [x] **P2-A6** Serialize models + metadata. _(issue: #141)_

### Milestone B slices

- [ ] **P2-B1** TikTok API polling live — VP/AHR dual-read gate.
- [ ] **P2-B2** Daily batch inference (08:00 UTC).
- [ ] **P2-B3** Haiku copy layer + rules fallback.
- [ ] **P2-B4** Swap mock → real inferences + policy alerts.
- [ ] **P2-B5** Live task execution behind approval.
- [ ] **P2-B6** Revenue-impact instrumentation.
- [ ] **P2-B7** Listing approval queue + Products API publish.
- [ ] **P2-B8** Leakage live executors.
- [ ] **P2-B9** Live operations pipeline wiring.
- [ ] **P2-B10** Scoped inventory collection.
- [ ] **P2-B11** Deferred workflow executors.

### Exit gate → Phase 3

- [ ] 50 live sellers · zero critical bugs · 2 weeks stable · Haiku + verified rules fallback

---

## Phase 3.0 — Brief

Deferred until Phase 2 exit gate: real-time (SSE/Realtime), TikTok LIVE API, polyglot
(ClickHouse/S3/SQS/Kafka), sentiment/CSAT, Celery workers. Detail: [`phase-3-vision.md`](docs/phases/phase-3-vision.md).

---

## In scope (Phase 2 MVP)

TikTok polling · 08:00 UTC inference · Haiku copy · operations pipeline on live data ·
3-tab IA · scoped inventory signals · Railway + Supabase single store.

## Explicitly out

Celery/Kafka · Creator matching · ClickHouse/S3/SQS · Realtime/SSE · vendor scrapers ·
Seller Center scraping · buyer PII · unofficial livestream websockets · inventory/finance
**management** (signals only for Stockout Prevention).

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
