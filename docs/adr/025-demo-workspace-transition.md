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

- The root pnpm workspace discovers `apps/demo` and `packages/*`.
  (Amended 2026-08-06 — originally `apps/*`; see the Amendment below.)
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

## Amendment — 2026-08-06: the workspace names `apps/demo`, not `apps/*`

The original `apps/*` glob made `apps/dashboard` a pnpm workspace member even
though this ADR keeps it npm-owned. `pnpm-lock.yaml` therefore carried an
`apps/dashboard` importer, while Dependabot's npm ecosystem (configured at
`/apps/dashboard`) only ever updates `apps/dashboard/package-lock.json`.

Every dashboard dependency bump consequently desynced the pnpm lock:

```
ERR_PNPM_OUTDATED_LOCKFILE  Cannot install with "frozen-lockfile" because
pnpm-lock.yaml is not up to date with <ROOT>/apps/dashboard/package.json
```

`pnpm install --frozen-lockfile` validates every workspace `package.json`, not
just the `--filter`ed subgraph, so this failed `demo-frontend`, `demo-e2e`,
`dependency-validation` and `deployment-checks` on dashboard-only PRs that never
touched Demo — see #645, #647, #650 and #651.

The workspace now lists `apps/demo` and `packages/*` explicitly. This is **not**
the dashboard package-manager migration anticipated under Consequences: the
dashboard keeps its npm lockfile, its `npm ci` CI job, and its `npm ci` VPS build.
The amendment *narrows* the dual-management surface rather than resolving it —
the dashboard is now purely npm-owned, with no phantom pnpm importer.

Safe only while the dashboard consumes no workspace package. `apps/demo` must be
added to this list explicitly if a second pnpm-managed app appears;
`test_npm_owned_dashboard_is_not_a_pnpm_workspace_member` in
`tests/unit/test_issue_397_demo_workspace_contract.py` pins both halves of the
invariant.

The import-boundary tests are unaffected — they glob the `apps/*` directory on
disk, independently of pnpm workspace membership, so the dashboard is still
covered by the no-sibling-app-imports rule.
