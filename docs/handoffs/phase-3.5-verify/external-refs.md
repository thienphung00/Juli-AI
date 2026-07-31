# External refs for Phase 3.5 verify

## Evaluation lens (user directive)
Optimize for **performance and scalability**, NOT speed (latency) and cost.
- A1 "Speed layer" is product naming for OLTP freshness — evaluate whether issues correctly separate latency-oriented freshness from fleet-scale performance/scalability (A2 Batch).
- Prefer evidence of dual budgets, mutex, stagger, JSONB index strategy, batch inserts, connection pooling.

## Live Supabase (read 2026-07-30)
- Schemas present: auth, extensions, public, realtime, storage, vault
- Medallion schemas bronze/silver/gold/ops: **ABSENT**
- No gold.kpi_envelopes yet — serving contract not migrated
- Decisions persistence today: public.action_cards (+ recommendations, tool_executions, workflow_outcome_records)
- Ops-ish: public.analytics_backfill_partitions, processed_events, webhook_raw_events
- Analytics: public.analytics_performance_intervals (flat public, not silver/gold)

## Context7 — PostgreSQL JSONB
- Prefer GIN on jsonb for containment (@>); jsonb_path_ops smaller for @> only
- Expression indexes for specific keys; operators must hit indexed expression
- Wide jsonb payloads TOAST — monitor toast size for gold.kpi_envelopes.payload

## Context7 — Celery
- Task rate_limit strings (e.g. 200/m); dynamic rate_limit via control
- Periodic interval changes via scheduler is_due overrides — supports staggered fleet windows

## Context7 — Redis
- Stampede/race: placeholder / lock patterns; TTL caps; invalidation races with dual connections
- Serving layer Redis is read-through cache SoT remains gold — not Redis-as-SoT

## Supabase postgres best practices (plugin)
- JSONB GIN indexing (advanced-jsonb-indexing)
- Batch INSERT / COPY for bronze append volume (data-batch-inserts)
- Connection pooling critical for fleet batch
- RLS performance when gold exposed to clients
