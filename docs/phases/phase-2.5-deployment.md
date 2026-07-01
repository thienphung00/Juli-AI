# Phase 2.5 — Deployment Architecture

> **Tier 1 — restructure & deploy scope.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** product monorepo layout, domain routing, package boundaries, deploy targets.  
> **Does not own:** pipeline mechanics (`phase-2-mvp.md`), subsystem envelopes (`system-design.md`).

**Goal:** Prepare production deployment architecture before exposing Juli publicly.

**Active scope (first migration):** documentation alignment + folder scaffold only.  
Runtime code stays in legacy paths until a follow-up PR moves it.

---

## Target repository structure

```text
juli-ai-v2/
├── apps/
│   ├── landing/          # app-juli.com
│   ├── demo/             # demo.app-juli.com
│   ├── dashboard/        # dashboard.app-juli.com (Phase 3.5+)
│   └── mobile/           # React Native / Expo (Phase 4+)
├── packages/
│   ├── ui/
│   ├── theme/
│   ├── icons/
│   ├── illustrations/
│   ├── api-client/
│   ├── types/
│   └── utils/
├── backend/
│   ├── api/
│   ├── workers/
│   ├── ai/
│   ├── integrations/
│   └── database/
├── docs/
└── infra/
```

---

## Domain strategy

| Domain | Product | Phase |
|--------|---------|-------|
| `app-juli.com` | Landing Page (marketing) | 3 |
| `demo.app-juli.com` | Interactive Demo (mock storytelling) | 3 |
| `dashboard.app-juli.com` | Full web dashboard | 3.5 |
| `api.app-juli.com` | Backend API | 2.5 (deployable) / 3.5 (production traffic) |

The Landing Page is a marketing website. The Demo is a product experience. The Dashboard
eventually replaces the Demo without affecting the Landing Page.

---

## Legacy path mapping (current → target)

| Current path | Target path | Status |
|--------------|-------------|--------|
| `src/` | `backend/` | Legacy — not moved yet |
| `src/apps/` | `backend/api/`, `backend/workers/` | **Naming collision:** `src/apps` = backend entrypoints, not product apps |
| `web/` | `apps/dashboard/` (Phase 3.5) or reference for `apps/demo/` (Phase 3) | Legacy — not moved yet |
| `ios/` | `apps/mobile/` | Legacy — not moved yet |
| `web/src/lib/` | `packages/*` (extracted incrementally) | Planned |
| `.github/workflows/` | `infra/` (deploy config split) | Planned |
| `alembic/`, `requirements.txt` | `backend/database/` | Planned |

Full migration sequence: [`architecture/migration-plan.md`](../architecture/migration-plan.md).

---

## Package boundaries (planned)

| Package | Owns | Must not own |
|---------|------|--------------|
| `packages/ui` | Shared React components | App-specific routing |
| `packages/theme` | Design tokens, Tailwind preset | Page layouts |
| `packages/icons` | Icon components | Business logic |
| `packages/illustrations` | Marketing/demo illustrations | API calls |
| `packages/api-client` | Typed HTTP client for `api.app-juli.com` | Server-side secrets |
| `packages/types` | Shared TypeScript types | Runtime validation |
| `packages/utils` | Formatting, date, currency helpers | UI components |

No shared packages are published until workspace tooling (`pnpm` workspaces or Turborepo)
is introduced in a follow-up PR.

---

## Exit gate → Phase 3

- [x] Target folders scaffolded with ownership READMEs _(2.5-a)_
- [x] Canonical docs aligned (`EXECUTION.md`, `map.md`, phase docs) _(2.5-a)_
- [ ] CI/CD can deploy frontend and backend independently _(2.5-d)_
- [ ] Intended domains route to correct deploy targets (staging minimum) _(2.5-e)_

---

## Explicitly out (Phase 2.5)

Landing Page implementation · Demo UI implementation · auth flows · TikTok connection ·
shared package extraction with live imports · mobile app scaffold beyond README.
