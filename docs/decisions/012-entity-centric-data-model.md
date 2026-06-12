# ADR 012: Entity-Centric Canonical Data Model

## Status
Accepted

## Context

Juli's TikTok integration was documented endpoint-first (`docs/tiktok_api/endpoints.md`
mapping vendor responses to Juli types). That worked for Phase 1 UI mock data but
created three problems as Phase 1.5 ML and Phase 2 live polling approached:

1. **Vendor lock-in** — feature engineering and ML training schemas were implicitly
   tied to TikTok response shapes.
2. **Schema drift** — return/anomaly fields lived in `system-design.md` tables while
   mock fixtures, parquet, and Postgres evolved separately.
3. **Multi-platform cost** — Shopee/Lazada (Phase 2.5+) would require rewriting ML
   pipelines unless a platform-agnostic layer existed.

Phase 1.5 requires labeled backtest parquet (`item_swap`, `empty_return`) with
`OrderItem.sku_id` for swap detection ([ADR-011](011-buyer-behavior-anomaly-scope.md)).
An explicit canonical entity layer was needed before P1.5-1 dataset assembly.

## Decision

- **We will:** Introduce `docs/data-models/` as the **canonical schema authority**:
  - [`canonical-entities.md`](../data-models/canonical-entities.md) — eight platform-agnostic
    entities (Shop, Product, Order, OrderItem, Return, Creator, Livestream, Settlement).
  - [`feature-store-schema.md`](../data-models/feature-store-schema.md) — ML feature
    definitions, formulas, and inference signatures.
  - [`mock-data-generator.md`](../data-models/mock-data-generator.md) — synthetic dataset
    generation aligned to canonical schemas.
- **We will:** Keep `docs/tiktok_api/endpoints.md` as the **ingestion layer** — it maps
  TikTok API responses onto canonical entities via ETL; it is not the ML schema authority.
- **We will:** Insert a canonical-entity normalization step in the data pipeline between
  raw API responses and feature build / Postgres persistence.
- **We will not:** Fabricate UNKNOWN platform fields (`vp_score`, `ahr_score`, Ads API
  schemas) in canonical entities or synthetic data until P2-1 API verification.
- **We will not:** Remove the Return schema cross-phase summary from `system-design.md` —
  it becomes a **compatibility index** that defers to `canonical-entities.md` for full schemas.

## Why this architecture

- **Speed:** P1.5 synthetic generator and parquet layout share one schema; P2 ETL maps
  vendor → canonical without rewriting ML feature code.
- **Cost:** One feature store schema serves all three model suites; future marketplace
  adapters reuse the same feature definitions.
- **Scalability:** Entity-centric storage supports daily batch inference and bounded
  30/90-day rolling windows without endpoint-specific joins at inference time.
- **Reliability:** `OrderItem` is a first-class entity — item_swap detection requires
  ordered vs returned SKU comparison; missing line items fail loudly in validation.

## Options considered

- **Option A: Endpoint-centric (status quo)** — extend `endpoints.md` tables for ML.
  Fast for TikTok-only P1 but blocks multi-platform and duplicates field contracts.
  **Rejected.**
- **Option B: Entity-centric canonical layer (chosen)** — ingestion maps vendor →
  canonical; ML reads canonical + feature store only.
- **Option C: Full dimensional warehouse now** — separate staging/ODS/marts layers.
  **Rejected** — over-engineered for Phase 1.5; runner-agnostic jobs + parquet suffice.

## Consequences

- **Positive:** Single source of truth for mock, parquet, Postgres, and inference;
  `focus` can route ML tasks to `docs/data-models/` instead of raw endpoint schemas.
- **Negative:** Two doc layers to maintain (ingestion + canonical); ETL must enforce
  referential integrity (Return → Order → OrderItem).
- **Follow-ups:**
  - P1.5-1: generate parquet from `mock-data-generator.md` patterns.
  - P1.5-5: feature specs in `feature-store-schema.md` cross-linked from `system-design.md`.
  - P2-1: ETL writes canonical entities to Postgres; confirm UNKNOWN Order fields.

## Rollout / Migration plan

1. **Done:** Publish `docs/data-models/*` and cross-link canonical docs (this ADR session).
2. **P1.5-1:** Backtest parquet column names match `canonical-entities.md` field names.
3. **P2-1:** TikTok polling ETL outputs canonical entities; `endpoints.md` unchanged except
   lineage cross-links.
4. **Phase 2.5+:** Add `platform` field to entities when Shopee/Lazada adapters begin.
