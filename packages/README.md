# packages/

Shared libraries consumed by `apps/*`. No app-specific routing or pages.

| Package | Purpose | Status |
|---------|---------|--------|
| [`ui/`](ui/) | Shared React components | Scaffold only |
| [`theme/`](theme/) | Design tokens, Tailwind preset | Scaffold only |
| [`icons/`](icons/) | Icon components | Scaffold only |
| [`illustrations/`](illustrations/) | Marketing/demo illustrations | Scaffold only |
| [`api-client/`](api-client/) | Typed HTTP client for `api.app-juli.com` | Scaffold only |
| [`types/`](types/) | Shared TypeScript types | Scaffold only |
| [`utils/`](utils/) | Formatting, date, currency helpers | Scaffold only |

Workspace tooling (`pnpm` workspaces or Turborepo) will be introduced in a follow-up PR.
Until then, shared code remains in `web/src/lib/`.

See [`docs/phases/phase-2.5-deployment.md`](../docs/phases/phase-2.5-deployment.md).
