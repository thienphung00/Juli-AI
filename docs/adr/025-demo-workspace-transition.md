# ADR 025: Isolate the Demo dependency graph during workspace transition

## Status

Accepted

**Builds on:** [ADR-017](017-product-monorepo-deployment-architecture.md) and
[ADR-024](024-phase-2.6-2.7-frontend-resequencing.md).

## Context

Issue #397 introduces the first working `apps/demo` slice and the shared
`packages/theme`, `packages/ui`, and `packages/utils` modules it consumes. The
repository also contains `apps/dashboard`, which remains independently managed
and built with npm during this transition.

The root needs pnpm/Turborepo orchestration for Demo without making the Demo CI
gate depend on installing or migrating every product app at once.

## Decision

- The root pnpm workspace discovers `apps/*` and `packages/*`.
- `apps/demo` and its shared package dependency graph are managed by the pinned
  root pnpm version and orchestrated by Turborepo.
- Demo PR CI uses a filtered pnpm install for `@juli/demo...`, then runs the
  Demo-specific lint, type-check, test, shared formatter test, and production
  build gate.
- `apps/dashboard` retains its existing npm lockfile and independent CI job
  until a dedicated migration explicitly changes its package-manager ownership.
- Import-boundary tests enforce `apps/* → packages/*`, prohibit sibling-app
  imports, and prohibit packages importing apps.

## Rationale

Filtering installation to the Demo dependency graph keeps the first Phase 2.6
slice independently reviewable while allowing shared packages to be exercised
through a real consumer. Preserving dashboard's current build contract avoids an
unrelated package-manager migration in the Demo Home PR.

## Consequences

- The repository temporarily has root pnpm ownership for Demo/shared packages
  and app-local npm ownership for dashboard.
- New root workspace commands must remain filterable by product app.
- A future dashboard package-manager migration must remove the dual-management
  transition deliberately and update CI, locks, and this decision.
- `docs/architecture/map.md` records Demo and the shared packages as as-built
  modules.
