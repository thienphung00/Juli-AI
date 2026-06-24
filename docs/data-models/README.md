# Data Models

> **Tier 1 — schemas.** Read [`EXECUTION.md`](../EXECUTION.md) first.  
> **Owns:** canonical entity JSON, feature definitions, synthetic generator spec.  
> **Does not own:** TikTok field maps (`tiktok_api/endpoints.md`), data phase gates (`data-sources.md`), ADR rationale.

**Authority:** `EXECUTION.md` > `system-design.md` > **this folder** > `tiktok_api/endpoints.md` (ingestion only).

## Documents

| Document | Owns |
|----------|------|
| [canonical-entities.md](canonical-entities.md) | Shop, Product, Order, Return, workflow entities |
| [feature-store-schema.md](feature-store-schema.md) | ML features, formulas, inference signatures |
| [mock-data-generator.md](mock-data-generator.md) | Synthetic / backtest parquet pseudocode |

## Data flow

```
tiktok_api/endpoints.md (ingestion)
        → ETL → canonical entities (this folder)
        → backtest parquet (Milestone A) | Postgres (Milestone B) → inference
```

## UNKNOWN fields

Do not fabricate `vp_score`, `ahr_score`, Ads API fields, or unverified cancel fields until P2-B1 verification. See `canonical-entities.md`.
