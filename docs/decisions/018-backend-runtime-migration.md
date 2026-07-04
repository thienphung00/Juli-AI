# ADR 018: Backend runtime migration to `backend/` (Phase 2.5-c)

## Status

Accepted

## Context

Phase 2.5 scaffolded the target monorepo layout (`apps/`, `packages/`, `backend/`,
`infra/`) while runtime Python code remained under legacy `src/`. TikTok App Review
deploy (#256) went live using `src.apps.api_gateway.api.main:app` on the VPS.

Issue #252 moves the backend modular monolith into `backend/` without changing
reviewer-visible behavior or requiring an immediate deploy-config change.

## Decision

- **Runtime ownership:** `backend/api`, `backend/workers`, `backend/ai`,
  `backend/integrations`, and `backend/database` own the moved Python modules per
  [`migration-plan.md`](../architecture/migration-plan.md).
- **Imports:** New code and tests import `backend.*` only. Legacy `src/` shims were
  removed in pre-Phase 2 cleanup ([ADR 019](019-src-shim-removal.md)).
- **Alembic:** Migration scripts live under `backend/database/migrations/`; root
  `alembic.ini` `script_location` points there.
- **Deploy entrypoints:** `backend.api.api.main:app` (see [ADR 019](019-src-shim-removal.md);
  `src/` shims removed 2026-07-04).

## Rationale

Aligns the repository with the product monorepo boundary before Phase 3 app splits,
while keeping the live App Review host stable via compatibility shims.

## Consequences

- [`map.md`](../architecture/map.md) registry paths reference `backend/*`.
- CI `mypy` and harness routing target `backend/` instead of `src/`.
- Follow-up slice removes `src/` shims after `infra/deploy` entrypoints switch to
  `backend.api.api.main:app`.
