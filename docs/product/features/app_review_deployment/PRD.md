# PRD: App Review Deployment (Phase 2.5-review)

> **Parent:** [#249](https://github.com/thienphung00/Juli-AI/issues/249) ·
> **Phase doc:** [`docs/product/phases/phase-2.5-deployment.md`](../../product/phases/phase-2.5-deployment.md) ·
> **Issue index:** [`issues.md`](issues.md)

---

## Problem Statement

TikTok App Review needs a public domain where reviewers can open Juli, verify that the
frontend loads, confirm the backend is reachable, exercise a reviewer-safe login path,
and inspect the TikTok OAuth callback. Juli does not need production functionality yet.

Phase 2.5 also established the product monorepo scaffold (`apps/`, `packages/`,
`backend/`, `infra/`) and workspace tooling so later Phase 3+ work has clear deploy
boundaries. The active goal is a **minimal public App Review deployment**, not a
production launch.

---

## Goal

Ship a reviewer-accessible deployment:

| Requirement | Target |
|-------------|--------|
| Frontend | `https://app-juli.com/` resolves over HTTPS and loads the existing `web/` Next.js app |
| Backend | `https://api.app-juli.com/` resolves over HTTPS and serves FastAPI health/auth/OAuth routes |
| OAuth callback | `https://api.app-juli.com/v1/auth/tiktok/callback` exists with controlled error handling |
| Reviewer login | One-click demo entry (`NEXT_PUBLIC_UI_ONLY=1`) — no production users |
| CORS | `CORS_ALLOW_ORIGINS` includes `https://app-juli.com` so the frontend can call the API |

**Non-goals:** no real users, no production traffic, no persistent business data beyond
minimum auth/session state for reviewer access.

---

## Keep (Phase 2.5)

- VPS, Nginx, HTTPS
- Next.js (`web/`), FastAPI
- Supabase project (free tier) — database and optional OTP auth
- TikTok OAuth, CORS

## Skip for now (Phase 3+)

- Redis (unless startup requires it)
- Alembic migrations (unless reviewer login/OAuth persistence requires schema state)
- Cron jobs, background workers, ML batch jobs, polling services
- Webhook service (unless OAuth review explicitly requires it)
- HA tuning, multiple workers, scaling

---

## Smoke-test checklist (#261)

The repeatable sign-off proving App Review readiness lives in
[`docs/runbooks/smoke-checklist-runbook.md`](../../../docs/runbooks/smoke-checklist-runbook.md).
Operator quick reference: [`summary.md`](summary.md).

### CI validation (no live domain)

```bash
python -m pytest tests/unit/test_phase_2_5_deploy_config.py \
  tests/unit/test_phase_2_5_smoke_checklist.py -q
```

### Live smoke test (HITL, on the review VPS)

Prerequisites: [#256](https://github.com/thienphung00/Juli-AI/issues/256) DNS/TLS,
[#257](https://github.com/thienphung00/Juli-AI/issues/257) frontend,
[#258](https://github.com/thienphung00/Juli-AI/issues/258) backend,
[#260](https://github.com/thienphung00/Juli-AI/issues/260) reviewer login.

```bash
cd ~/Juli-AI-v2
grep CORS_ALLOW_ORIGINS=https://app-juli.com .env
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
```

`smoke-test.sh` covers DNS, TLS, frontend load, `/health`, OAuth callback, reviewer
login demo markers, home route chunks, and CORS preflight for `https://app-juli.com`.

### Review-only confirmation

Before sign-off, the operator explicitly confirms:

- [ ] No production users are onboarded to this deployment.
- [ ] No production traffic is routed to this deployment.
- [ ] No persistent business data (seller orders, returns, ads) is required to complete
      App Review.

---

## Exit gate → Phase 3

- [x] Target folders scaffolded, canonical docs aligned, workspace tooling in place
- [ ] Public domain works; frontend loads; backend responds; OAuth callback exists;
      reviewers can log in
- [ ] CORS allows the frontend origin; smoke checklist signed off
- [ ] No production users, production traffic, or persistent business data required

---

## Out of Scope

- Landing page / demo implementation (Phase 3)
- Production traffic and real-user onboarding
- Redis/workers/cron/ML/polling/webhooks/HA unless review path cannot start without them
- Backend `src/` → `backend/` migration (#252) before App Review exit
