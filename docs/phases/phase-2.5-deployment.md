# Phase 2.5 — App Review Deployment

> **Tier 1 — restructure & deploy scope.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** product monorepo layout, domain routing, package boundaries, deploy targets.  
> **Does not own:** pipeline mechanics (`phase-2-mvp.md`), subsystem envelopes (`system-design.md`).

**Goal:** Provide a public, HTTPS-accessible Juli deployment for TikTok App Review without
launching production functionality.

**Active scope (first migration):** documentation alignment + folder scaffold only.  
Runtime code stays in legacy paths until a follow-up PR moves it.

**Active App Review slice:** deploy the existing `web/` Next.js frontend and FastAPI API from
legacy paths on a VPS-backed domain so TikTok reviewers can load the UI, reach the backend,
exercise reviewer login, and verify the TikTok OAuth callback.

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
[`smoke-test.sh`](../../infra/deploy/smoke-test.sh) checklist covers DNS, TLS,
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
| [`provision-nginx.sh`](../../infra/deploy/provision-nginx.sh) | Copy vhosts + reload Nginx on VPS |
| `smoke-test.sh --dns-tls-only` | Validate DNS + TLS before apps are deployed |

Issue index: [`docs/features/app_review_deployment/issues.md`](../features/app_review_deployment/issues.md).

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

- [ ] `https://app-juli.com/` resolves and loads the frontend.
- [ ] `https://api.app-juli.com/health` returns a 2xx JSON response.
- [ ] `https://api.app-juli.com/v1/auth/tiktok/callback` exists and handles missing/invalid
      OAuth params with a controlled response, not a server crash.
- [ ] Reviewer login uses UI-only entry (no phone OTP / Supabase SMS).
- [ ] CORS allows `https://app-juli.com`.
- [ ] No production user traffic is invited or routed to this deployment.
- [ ] No persistent business data is required to complete App Review.

Implementation planning lives in [`../features/app_review_deployment/PRD.md`](../features/app_review_deployment/PRD.md)
and [`../features/app_review_deployment/issues.md`](../features/app_review_deployment/issues.md).

---

## Exit gate → Phase 3

- [x] Target folders scaffolded with ownership READMEs _(2.5-a)_
- [x] Canonical docs aligned (`EXECUTION.md`, `map.md`, phase docs) _(2.5-a)_
- [x] Workspace tooling (`pnpm` + Turborepo) without moving runtime apps _(2.5-b)_
- [ ] Public App Review domain routes to the frontend over HTTPS _(2.5-review)_
- [ ] Backend health and OAuth callback routes respond over HTTPS _(2.5-review)_
- [ ] Reviewer login works without production users or production traffic _(2.5-review)_
- [x] CI/deploy notes capture the temporary VPS/Nginx topology _(2.5-d)_

---

## Explicitly out (Phase 2.5)

Real users · production traffic · persistent business data · Landing Page implementation ·
Demo UI implementation · shared package extraction with live imports · mobile app scaffold beyond
README · Redis/Cron/workers/ML/polling/webhooks/HA unless required by the review login or OAuth
callback path.
