# ADR 006: Entity-centric canonical data model

## Status
Accepted

## Context

Endpoint-first documentation tied ML schemas to TikTok response shapes. Phase 2 MVP
requires a platform-agnostic canonical layer for ETL, feature engineering, and inference.

## Decision

- **We will:** Maintain `docs/data-models/` as the **canonical schema authority**:
  - [`canonical-entities.md`](../data-models/canonical-entities.md) — eight entities
  - [`feature-store-schema.md`](../data-models/feature-store-schema.md) — ML features + inference signatures
  - [`mock-data-generator.md`](../data-models/mock-data-generator.md) — synthetic data aligned to canonical schemas
- **We will:** Keep `docs/tiktok_api/endpoints.md` as the **ingestion layer** mapping
  TikTok API → canonical entities via ETL.
- **We will:** Insert canonical-entity normalization between raw API responses and
  feature build / Postgres persistence.
- **We will not:** Fabricate UNKNOWN platform fields until API verification.

## Consequences

- Single source of truth for mock, parquet, Postgres, and inference.
- Future marketplace adapters (Phase 3+) reuse the same feature definitions.
