# ADR 017: Product monorepo deployment architecture (Phase 2.5)

## Status

Accepted

## Context

Juli is evolving from a single legacy layout (`src/`, `web/`, `ios/`) into an ecosystem
of independently deployable products. Phase 3+ requires landing, demo, dashboard, mobile,
and API targets on distinct domains without mixing backend internals, shared packages,
and product apps.

A naming collision exists: legacy `src/apps/` holds backend entrypoint composition while
top-level `apps/` will hold product deployables.

## Decision

- **Target layout:** `apps/` (product deployables), `packages/` (shared UI/types/client),
  `backend/` (API, workers, integrations, database), `infra/` (CI/CD and deploy config),
  with `docs/` unchanged as canonical documentation.

- **Phase 2.5-a scope:** documentation alignment and ownership README scaffold only.
  Runtime code remains in legacy paths until follow-up migration PRs (2.5-b through 2.5-e).

- **Import boundaries (future):** apps import packages; apps never import sibling apps;
  backend never imports apps or packages; apps reach backend only via HTTP API client.

- **Domain map:** `app-juli.com` (landing), `demo.app-juli.com` (demo),
  `dashboard.app-juli.com` (dashboard), `api.app-juli.com` (backend API).

## Rationale

Separates deploy concerns before public Phase 3 landing/demo work. Scaffold-first migration
reduces risk: docs and folder ownership land without import rewrites or broken builds.

## Consequences

- Tier 1 docs: [`phase-2.5-deployment.md`](../phases/phase-2.5-deployment.md),
  [`migration-plan.md`](../architecture/migration-plan.md), updated [`map.md`](../architecture/map.md).
- Migration PR sequence 2.5-a…2.5-e tracked in migration plan.
- Legacy `web/` dashboard keeps ADR-014 IA until Phase 3.5 `apps/dashboard` migration.
