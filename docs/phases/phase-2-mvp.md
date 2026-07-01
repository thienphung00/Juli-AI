# Phase 2 — Pipeline Validation

> **Tier 1 — backend pipeline scope.** Read [`EXECUTION.md`](../../EXECUTION.md) first for slices.  
> **Owns:** pipeline architecture diagram, daily UTC schedule, data/cache roles, account-health contract.  
> **Does not own:** deployment (`phase-2.5-deployment.md`), subsystem envelopes (`system-design.md`), module paths (`map.md`).

**Goal:** Validate the backend pipeline end-to-end with **no public users**, **no landing page**,
**no production deployment**, and **no trained ML**.

**Signal layer:** Rules-based only. Policy rules, thresholds, and heuristics replace trained
models in Phase 2. Trained ML (T1–T8) begins in Phase 4.

---

## Architecture overview

```mermaid
flowchart TB
    subgraph internal [InternalValidationOnly]
        CLI[InternalCLIAndTests]
        Scripts[PipelineScripts]
    end

    subgraph app [ApplicationServer FastAPI]
        BizLogic[BusinessLogic MultiTenant]
        ToolCall[ToolCalling ReadWrite]
        RulesEngine[RulesBasedSignalEngine]
        RulesCopy[RulesBasedCopyLayer]
    end

    subgraph storage [StorageLayer]
        Redis[(Redis Cache Sessions)]
        subgraph pg [Supabase PostgreSQL]
            OLTP[OLTP Accounts Transactions]
            OLAP[OLAP KPIs FeatureAggregates]
        end
    end

    subgraph batch [ScheduledBatch]
        FeatAgg[FeatureAggregates SQLPython]
        RulesBatch[RulesBasedScoring]
        ActionGen[ActionCardGenerator RulesTemplates]
    end

    subgraph side [SideComponents]
        TikTok[TikTokShopAPI Ingestion ETL]
        Celery[Celery Workers Execution]
    end

    CLI --> app
    Scripts --> app
    app --> Redis
    app --> pg
    TikTok --> pg
    pg --> FeatAgg
    FeatAgg --> RulesBatch
    RulesBatch --> ActionGen
    ActionGen --> Redis
    ActionGen --> OLTP
    app --> RulesEngine
    app --> RulesCopy
    app --> Celery
```

**Transactional path:** Business logic → OLTP.  
**Analytics + rules path:** OLAP → feature aggregates → rules-based signals → action cards → Redis + OLTP.

Public web clients (`web/`, `ios/`) exist for internal dogfooding but are **not required**
for Phase 2 exit. Production deployment moves to Phase 2.5.

---

## Daily schedule (UTC)

| Time | Job | Notes |
|------|-----|-------|
| Overnight | TikTok API poll | Orders, Products, Affiliate, Promotion API |
| 06:00–07:00 | Feature aggregates | Postgres → KPI aggregates (not ML training features) |
| 08:00 | Rules-based scoring | Deterministic rules → signals → recommendations |
| After scoring | Rules-based copy layer | Deterministic templates from rule signals |
| On approval | Celery executor | Tool calls never block HTTP handler |

---

## Data & cache

| Store | Role |
|-------|------|
| **Postgres OLTP** | Accounts, transactions, action-card writes |
| **Postgres OLAP** | Materialized views, KPI aggregates, feature aggregate tables |
| **Redis** | Action cards (≤6/seller), SQL view cache, session tokens |

Feature aggregates stay in Python/SQL (ADR-010); no trained model artifacts loaded in Phase 2.

---

## Signal layer (rules-based)

| Technique type | Phase 2 implementation | Phase 4 (ML) |
|----------------|------------------------|--------------|
| Shop profile routing | Deterministic rules (`NEW_SHOP` / `MID_LARGE_SHOP`) | T8 router classifier |
| Policy / VP / AHR | Platform policy rules (ADR-005–010) | Same + ML enrichment |
| Anomaly detection | Threshold / EWMA rules | T4 / T6 trained detectors |
| Ads ranking | ROAS threshold rules | T2 ads regressor |
| Forecasting | Naive / moving-average display | T1 ETS forecaster |

See [`ml_layer.md`](../ml_layer.md) for the full T1–T8 catalog — **Phase 4 only**.

---

## Copy layer

**Rules-based only** in Phase 2 — deterministic templates from rule signals. No cloud LLM.

Cloud LLM (Claude Haiku) is deferred to Phase 4 per [`EXECUTION.md`](../../EXECUTION.md).

---

## Deployment

**Not in scope for Phase 2.** Local and CI validation only.

Production deployment architecture is Phase 2.5:
[`phase-2.5-deployment.md`](phase-2.5-deployment.md).

---

## Account health contract

```
health_data_source: api | proxy | unavailable
```

Partner API field exposure gated at P2-A1. Dual-read VP/AHR May–July 2026 (ADR-005, ADR-006).

---

## Anomaly scope (Phase 2)

Buyer-behavior signals use **policy rules and thresholds** only — not trained anomaly models.
Trained `item_swap` / `empty_return` detectors deferred to Phase 4 (ADR-008).
