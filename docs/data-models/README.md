# Data Models

Platform-agnostic canonical schemas for Juli-AI. **Authority for ML training,
feature engineering, mock data, and inference** — not for raw API ingestion.

> **Authority order (entity schemas):**  
> `EXECUTION.md` > `system-design.md` > **`docs/data-models/`** > `tiktok_api/endpoints.md` (ingestion only)

## Documents

| Document | Role | Primary consumers |
|----------|------|-------------------|
| [canonical-entities.md](canonical-entities.md) | Platform entities (Shop, Product, Order, …) plus **workflow entities** (ProductDraft, Distributor, Opportunity) for New Seller listing — JSON types, lineage, refresh rules | ETL, mock fixtures, Postgres design, `focus` |
| [feature-store-schema.md](feature-store-schema.md) | Derived ML features — formulas, dependencies, null policy, inference signatures | P1.5 training, P2 daily feature build, model artifacts |
| [mock-data-generator.md](mock-data-generator.md) | Synthetic dataset pseudocode for P1 fixtures and P1.5 backtest parquet | P1-1, P1.5-1 |

## Data flow

```
TikTok API (endpoints.md — ingestion layer)
        │
        ▼
Raw API responses / events
        │  ETL: vendor field map, enum derivation, buyer_id masking
        ▼
Canonical entities (this folder)
        │
        ├──► Mock JSON (Phase 1)
        ├──► Backtest parquet (Phase 1.5)
        ├──► Postgres OLTP (Phase 2)
        └──► Feature store → ML training → inference
```

## Related docs

- [`docs/tiktok_api/endpoints.md`](../tiktok_api/endpoints.md) — vendor → Juli ingestion map (unchanged role)
- [`docs/system-design.md`](../system-design.md) § Data pipeline, § Return schema contract (cross-phase index)
- [`docs/architecture/data-sources.md`](../architecture/data-sources.md) — phase-aligned source matrix
- [ADR-011](../decisions/011-buyer-behavior-anomaly-scope.md) — anomaly ML scope (`item_swap`, `empty_return`)
- [ADR-012](../decisions/012-entity-centric-data-model.md) — entity-centric architecture decision

## Phase alignment

| Phase | Usage |
|-------|--------|
| **P1** | Mock fixtures generated from `mock-data-generator.md` patterns |
| **P1.5** | Backtest parquet + feature store schemas for model training |
| **P2** | ETL persists canonical entities; daily feature build reads Postgres |

## UNKNOWN fields — do not fabricate

`vp_score`, `ahr_score`, `withholding_active`, `violation_events`, Ads API fields,
and unverified Order cancel fields remain `null` in all synthetic data until P2-1
API verification. See `canonical-entities.md` §Unknown fields.
