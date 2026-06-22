# ADR 012: Architecture reconciliation — MVP stack vs polyglot target

## Status
Accepted

**Supersedes:** Ollama copy-layer choice (historical).  
**Reaffirms:** [ADR-002](002-supabase-backend-service.md), [ADR-004](004-etl-kafka-consumer.md),
[ADR-010](010-ml-module-tree-and-trainers.md).

## Context

A proposed end-to-end architecture included ClickHouse, S3, SQS, SQL views replacing
the feature store, and Ollama/DSPy copy layer. At MVP scale the product needs batch/daily
data, single Postgres, hosted Haiku, and Railway deployment.

## Decision

- **Data store — single Postgres now; polyglot is Phase 3.** Supabase Postgres remains
  sole OLTP/analytics store for Phase 2 MVP. ClickHouse, S3, SQS are Phase 3 targets.
  Interim raw archive: in-DB `raw_payloads` (`jsonb`) table.

- **SQL Views — plain views for serving, not the feature store.** ML features stay Python
  ([ADR-010](010-ml-module-tree-and-trainers.md)). Materialized views are opt-in per-query
  optimization refreshed by daily batch — not the architecture backbone.

- **LLM copy layer — Claude Haiku 3.5 + rules fallback; defer DSPy.** Hosted Haiku at MVP
  volume is lower-ops than self-hosted Ollama. Rules fallback on timeout/error/budget cap.
  Raw financial PII never sent to LLM.

- **Deployment — Railway for MVP.** FastAPI + cron poller on Railway; Supabase for DB/Auth.

- **Real-time — out of scope for Phase 2 MVP.** No Supabase Realtime or SSE; UI served
  from batch/daily data. Real-time is Phase 3 ([`phase-3-vision.md`](../phases/phase-3-vision.md)).

- **Tenant isolation — service layer is the live boundary.** `ShopScopedRepo` `shop_id`
  filtering; RLS policies are defense-in-depth only.

## Consequences

- Phase 2 MVP architecture documented in [`phase-2-mvp.md`](../phases/phase-2-mvp.md).
- Phase 3 polyglot target in [`phase-3-vision.md`](../phases/phase-3-vision.md).
