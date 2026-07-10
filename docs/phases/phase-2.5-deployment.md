# Phase 2.5 — App Review Deployment

> **Tier 1 — restructure & deploy scope.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** product monorepo layout, domain routing, package boundaries, deploy targets.  
> **Does not own:** pipeline mechanics (`phase-2-mvp.md`), subsystem envelopes (`system-design.md`).

**Goal:** Provide a public, HTTPS-accessible Juli deployment for TikTok App Review without
launching production functionality.

**Status:** Complete (App Review sign-off 2026-07-03). Backend runtime lives in `backend/`;
legacy `web/` serves `app-juli.com` until Phase 3 landing replaces it.

**Completed App Review slice:** `web/` Next.js frontend and FastAPI API deployed on a
VPS-backed domain so TikTok reviewers can load the UI, reach the backend, exercise reviewer
login, and verify the TikTok OAuth callback.

**Non-goals:** no real users, no production traffic, and no persistent business data beyond the
minimum auth/session state needed for reviewer access.

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
| `app-juli.com` | App Review frontend (temporary legacy `web/` deploy) | 2.5 |
| `demo.app-juli.com` | Interactive Demo (mock storytelling) | 3 |
| `dashboard.app-juli.com` | Full web dashboard | 3.5 |
| `api.app-juli.com` | Backend API + TikTok OAuth callback | 2.5 (review) / 3.5 (production traffic) |

For App Review, `app-juli.com` can temporarily serve the legacy `web/` app. Phase 3 may replace
that surface with the marketing landing page and move demo/dashboard concerns to their intended
subdomains. `api.app-juli.com` must expose health and OAuth callback routes, but it must not be
treated as production traffic infrastructure yet.

TikTok Partner Center review URLs:

| Setting | Value |
|---------|-------|
| OAuth redirect URL | `https://api.app-juli.com/v1/auth/tiktok/callback` |
| Reviewer entry URL | `https://app-juli.com/` |

---

## Legacy path mapping (current → target)

| Current path | Target path | Status |
|--------------|-------------|--------|
| `src/` | `backend/` | **Migrated (2.5-c)** — `src/` shims re-export `backend.*` |
| `src/apps/` | `backend/api/`, `backend/workers/` | **Migrated (2.5-c)** |
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

No shared packages are published until workspace tooling is in place. Phase 2.5-b adds
`pnpm` workspaces and a Turborepo skeleton; scaffold `apps/*` and `packages/*` members
are private placeholders with no exports or cross-imports. Shared code remains in
`web/src/lib/` until package extraction in a later slice.

---

## Workspace tooling (2.5-b)

`pnpm-workspace.yaml` registers `web/`, `apps/*`, and `packages/*`. Legacy `web/` is
unchanged on disk; its existing `npm` workflow still works from `web/`:

```bash
cd web && npm ci && npm run lint && npm run type-check && npm run test
```

Validate the monorepo workspace baseline from the repository root:

```bash
pnpm install
pnpm run workspace:baseline
```

`workspace:baseline` runs `build` first, then `lint`, `type-check`, and `test` for `juli-web` only.
Scaffold apps and packages are private workspace members without publish surfaces or
fake `@juli/*` imports.

---

## Deploy configuration (2.5-d)

Frontend and backend deploy configs are split under [`infra/deploy/`](../../infra/deploy/)
so each service is independently restartable on the single review VPS:

| Concern | Frontend (`app-juli.com`) | Backend (`api.app-juli.com`) |
|---------|---------------------------|------------------------------|
| Service | `systemd/juli-web.service` (Next.js) | `systemd/juli-api.service` (FastAPI) |
| Upstream | `127.0.0.1:3000` | `127.0.0.1:8000` |
| Nginx vhost | `nginx/app-juli.com.conf` | `nginx/api.app-juli.com.conf` |
| Env template | `env/web.env.example` | `env/api.env.example` |

Restart independently:

```bash
sudo systemctl restart juli-web   # frontend only
sudo systemctl restart juli-api   # backend only
```

The [`app-review-runbook.md`](../../infra/deploy/app-review-runbook.md) documents
the VPS/Nginx/HTTPS topology, required env vars (secrets stay outside git),
install steps, and validation. Validate the deploy config contracts with
`python -m pytest tests/unit/test_phase_2_5_deploy_config.py`; live DNS/TLS wiring
stays HITL on the VPS (issue #256) — see
[`vps-wiring-runbook.md`](../../infra/deploy/vps-wiring-runbook.md). The
[`smoke-test.sh`](../../infra/scripts/smoke-test.sh) checklist covers DNS, TLS,
frontend load, `/health`, and the OAuth callback route (`--dns-tls-only` for #256).

Out of scope for the review deploy: Redis, cron, workers, ML batch, polling,
webhook service, and HA/multi-worker tuning.

---

## VPS wiring (2.5-review-a, issue #256)

HITL slice: point DNS at the review VPS, install Nginx vhosts, and issue HTTPS
certificates. Repo deliverables:

| Path | Purpose |
|------|---------|
| [`vps-wiring-runbook.md`](../../infra/deploy/vps-wiring-runbook.md) | Step-by-step DNS, Certbot, sign-off |
| [`provision-nginx.sh`](../../infra/scripts/provision-nginx.sh) | Copy vhosts + reload Nginx on VPS |
| `smoke-test.sh --dns-tls-only` | Validate DNS + TLS before apps are deployed |

**VPS layout:** one checkout at `~/Juli-AI-v2` — backend `.env` at repo root, frontend
`web/.env.production`, both services restarted independently from the same repo.

Issue index: [`docs/features/app_review_deployment/issues.md`](../features/app_review_deployment/issues.md).

---

## Frontend deploy (2.5-review-b, issue #257)

AFK/HITL slice: build and serve the existing `web/` Next.js app on `juli-web`
(`127.0.0.1:3000`) behind `https://app-juli.com/`. Landing page and demo app
remain deferred to Phase 3.

| Path | Purpose |
|------|---------|
| [`frontend-deploy-runbook.md`](../../infra/deploy/frontend-deploy-runbook.md) | Build, systemd, UI-only fallback, sign-off |
| [`provision-frontend.sh`](../../infra/scripts/provision-frontend.sh) | Install `juli-web` + `npm ci && npm run build` on VPS |
| [`build-frontend-review.sh`](../../infra/scripts/build-frontend-review.sh) | Review build with `NEXT_PUBLIC_API_URL` + UI-only login |

Prerequisite: [#256](vps-wiring-runbook.md) DNS/TLS. Full smoke test frontend checks
require `juli-web` running; backend checks wait for [#258](https://github.com/thienphung00/Juli-AI/issues/258).

---

## Backend deploy (2.5-review-c, issue #258)

AFK/HITL slice: install and serve the existing FastAPI app on `juli-api`
(`127.0.0.1:8000`) behind `https://api.app-juli.com/`. Only `/health`, auth
surface, and (after #259) TikTok OAuth callback are in scope.

| Path | Purpose |
|------|---------|
| [`backend-deploy-runbook.md`](../../infra/deploy/backend-deploy-runbook.md) | Env, systemd, Alembic skip policy, sign-off |
| [`provision-backend.sh`](../../infra/scripts/provision-backend.sh) | Install `juli-api` + `pip install` on VPS |

Prerequisite: [#256](vps-wiring-runbook.md) DNS/TLS. Full smoke test backend checks
require `juli-api` running with `DATABASE_URL` and `CORS_ALLOW_ORIGINS` set on the VPS.

---

## Reviewer login (2.5-review-d, issue #260)

AFK/HITL slice: TikTok reviewers log in via **one-click demo entry**
(`NEXT_PUBLIC_UI_ONLY=1`) without becoming production users or loading real seller
data. Optional Supabase OTP path documented only when TikTok explicitly requires it.

| Path | Purpose |
|------|---------|
| [`reviewer-login-runbook.md`](../../infra/deploy/reviewer-login-runbook.md) | UI-only default, optional Supabase OTP, credentials outside git |
| [`build-frontend-review.sh`](../../infra/scripts/build-frontend-review.sh) | Forces `NEXT_PUBLIC_UI_ONLY=1` at build time |

Prerequisites: [#257](frontend-deploy-runbook.md) frontend deploy, [#258](backend-deploy-runbook.md)
backend deploy. Smoke test login checks require `juli-web` built with the review script.

---

## Smoke checklist & sign-off (2.5-review-f, issue #261)

AFK/HITL slice: finalize the repeatable smoke-test checklist proving App Review
readiness — CORS, DNS, TLS, frontend, `/health`, OAuth callback, reviewer login, and
explicit review-only confirmation (no production users, traffic, or persistent
business data).

| Path | Purpose |
|------|---------|
| [`smoke-checklist-runbook.md`](../../infra/deploy/smoke-checklist-runbook.md) | HITL sign-off checklist + CORS verification |
| [`smoke-test.sh`](../../infra/scripts/smoke-test.sh) | Automated DNS/TLS/frontend/health/OAuth/login/CORS probes |
| [`PRD.md`](../features/app_review_deployment/PRD.md) | Canonical smoke commands and acceptance criteria |
| [`summary.md`](../features/app_review_deployment/summary.md) | Operator quick reference |

Prerequisites: [#254](../features/app_review_deployment/issues.md) E2E domain wiring
and deploy slices #256–#260. Set `CORS_ALLOW_ORIGINS=https://app-juli.com` on the VPS
before full sign-off.

---

## App Review deployment envelope (2.5-review)

Keep these components in Phase 2.5:

| Component | Requirement |
|-----------|-------------|
| VPS | Single host is sufficient for review traffic. |
| Nginx | Terminate HTTPS and route frontend/API upstreams. |
| HTTPS | Public TLS for `app-juli.com` and `api.app-juli.com`. |
| Next.js | Serve the existing `web/` app; UI-only/reviewer-safe behavior is acceptable. |
| FastAPI | Serve `/health`, auth endpoints required by reviewer login, and TikTok OAuth callback. |
| Supabase free tier | Auth/project configuration only; no production business dataset. |
| TikTok OAuth | Callback route exists and returns controlled success/error behavior. |
| CORS | Allow the public frontend origin to call the API. |

Skip until Phase 3 or later unless startup requires it:

| Component | Phase 2.5 stance |
|-----------|------------------|
| Redis | Do not run unless imported startup code requires it. |
| Alembic migrations | Skip unless reviewer login or OAuth persistence requires schema state. |
| Cron jobs | Out of scope. |
| Background workers | Out of scope. |
| ML batch jobs | Out of scope. |
| Polling services | Out of scope. |
| Webhook service | Out of scope unless TikTok OAuth review explicitly requires it. |
| HA tuning / scaling | Out of scope; single-process/single-host is acceptable for review. |

### Reviewer acceptance checklist

- [x] `https://app-juli.com/` resolves and loads the frontend.
- [x] `https://api.app-juli.com/health` returns a 2xx JSON response.
- [x] `https://api.app-juli.com/v1/auth/tiktok/callback` exists and handles missing/invalid
      OAuth params with a controlled response, not a server crash.
- [x] Reviewer login uses UI-only demo entry.
- [x] CORS allows `https://app-juli.com`.
- [x] No production user traffic is invited or routed to this deployment.
- [x] No persistent business data is required to complete App Review.

Implementation planning lives in [`../features/app_review_deployment/PRD.md`](../features/app_review_deployment/PRD.md)
and [`../features/app_review_deployment/issues.md`](../features/app_review_deployment/issues.md).

---

## Exit gate → Phase 3

- [x] Target folders scaffolded with ownership READMEs _(2.5-a)_
- [x] Canonical docs aligned (`EXECUTION.md`, `map.md`, phase docs) _(2.5-a)_
- [x] Workspace tooling (`pnpm` + Turborepo) without moving runtime apps _(2.5-b)_
- [x] Public App Review domain routes to the frontend over HTTPS _(2.5-review, 2026-07-03)_
- [x] Backend health and OAuth callback routes respond over HTTPS _(2.5-review, 2026-07-03)_
- [x] Reviewer login works without production users or production traffic _(2.5-review, 2026-07-03)_
- [x] backend runtime boundary moved to `backend/` _(2.5-c; `src/` shims removed in pre-Phase 2 cleanup)_
- [x] CI/deploy notes capture the temporary VPS/Nginx topology _(2.5-d)_

---

## Explicitly out (Phase 2.5)

Real users · production traffic · persistent business data · Landing Page implementation ·
Demo UI implementation · shared package extraction with live imports · mobile app scaffold beyond
README · Redis/Cron/workers/ML/polling/webhooks/HA unless required by the review login or OAuth
callback path.
