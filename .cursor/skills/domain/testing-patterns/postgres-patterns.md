# Purpose

Use when designing Postgres schemas, writing SQL, or reviewing query/migration changes (including Supabase-backed environments).

# Core Principles

- Model the transactional truth in tables; use JSONB selectively.
- Prefer `timestamptz`, `text`, `boolean`, and appropriately-sized numerics.
- Every query must be bounded (pagination/limits); avoid unbounded scans.
- Index for proven access patterns; measure before adding more indexes.
- Keep migrations safe, reversible, and small (one intent per migration).
- Separate OLTP vs analytics workloads (don’t run heavy reports on hot tables).
- Use `EXPLAIN (ANALYZE, BUFFERS)` to validate assumptions.
- Avoid N+1 at the application layer; batch or join intentionally.

# Preferred Patterns

- **Schema**
  - Use explicit foreign keys; index FK columns used for joins.
  - Use `NOT NULL` + defaults where appropriate; enforce invariants in DB when stable.
  - Use generated columns or materialized views for derived/reporting needs when justified.
- **Indexing**
  - B-tree for equality/range; composite indexes with equality columns first, then range.
  - Partial indexes for “active rows” patterns (e.g., `deleted_at IS NULL`).
  - GIN for JSONB containment (`@>`) and full-text; BRIN for large append-only time series.
  - Covering indexes via `INCLUDE` for high-read, narrow-select patterns.
- **Query efficiency**
  - Prefer keyset/cursor pagination over `OFFSET`.
  - Select only needed columns; avoid `SELECT *` on wide tables.
  - Push filtering into SQL; don’t fetch-all-then-filter in Python.
- **JSONB**
  - Store flexible, sparsely-queried attributes in JSONB; keep frequently-queried fields as columns.
  - Add GIN indexes only when JSONB queries are frequent and measured.
- **Migrations**
  - Backfill in batches; avoid long locks on large tables.
  - Prefer additive changes (new columns/tables) + dual-write + cleanup migration.

# Avoid

- Premature indexing (indexes have write/space costs).
- N+1 query patterns via loops in application code.
- Unbounded list endpoints / `ORDER BY` without index support.
- Storing core relational fields exclusively inside JSONB (“everything is JSON”).
- Big-bang migrations that rewrite huge tables in one transaction.
- Overusing triggers for business logic that belongs in the app (unless enforcing invariants).

# Code Review Checklist

- **Correctness**: constraints, FKs, nullability, and defaults match invariants.
- **Bounded results**: queries have `LIMIT`/pagination; no table scans by accident.
- **Indexes**: new indexes match a known query; composite order is justified.
- **Explain**: author checked `EXPLAIN ANALYZE` for hot queries (plan + buffers).
- **Write impact**: indexes/triggers won’t overload write-heavy tables.
- **JSONB**: used intentionally; indexed only for real query patterns.
- **Migrations**: reversible where possible; avoids long locks; backfills are chunked.

# Agent Instructions

- Before adding an index, state the exact query it supports and validate with `EXPLAIN`.
- Default to keyset pagination patterns; avoid `OFFSET` unless dataset is small and stable.
- Don’t add “catch-all” JSONB columns as a shortcut for schema design.
- Keep migrations small and safe; if risky, propose an incremental rollout sequence.
- When reviewing a slow query, start with `EXPLAIN (ANALYZE, BUFFERS)` and remove guesswork.

