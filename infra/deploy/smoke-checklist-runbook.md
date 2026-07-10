# App Review Smoke Checklist & Sign-off (Phase 2.5-review-f, #261)

> **Scope:** Repeatable smoke-test checklist proving TikTok App Review readiness.
> **Authority:** [`docs/features/app_review_deployment/PRD.md`](../../docs/features/app_review_deployment/PRD.md) ·
> [`summary.md`](../../docs/features/app_review_deployment/summary.md)
>
> **Review-only:** no production users, no production traffic, no persistent business data.

This runbook finalizes the public App Review smoke path after prerequisite deploy
slices are complete. Live execution is **HITL** on the review VPS.

---

## Prerequisites

Complete these slices before full sign-off:

| Slice | Issue | Runbook |
|-------|-------|---------|
| VPS + Nginx + HTTPS | #256 | [`vps-wiring-runbook.md`](vps-wiring-runbook.md) |
| Frontend deploy | #257 | [`frontend-deploy-runbook.md`](frontend-deploy-runbook.md) |
| Backend deploy | #258 | [`backend-deploy-runbook.md`](backend-deploy-runbook.md) |
| TikTok OAuth callback | #259 | [`backend-deploy-runbook.md`](backend-deploy-runbook.md) |
| Reviewer login | #260 | [`reviewer-login-runbook.md`](reviewer-login-runbook.md) |
| E2E domain wiring | #254 | [`app-review-runbook.md`](app-review-runbook.md) |

---

## CORS configuration

The review frontend at `https://app-juli.com` must be allowed to call the API at
`https://api.app-juli.com`. On the VPS, set in `~/Juli-AI-v2/.env`:

```bash
CORS_ALLOW_ORIGINS=https://app-juli.com
```

Verify before smoke test:

```bash
grep CORS_ALLOW_ORIGINS=https://app-juli.com ~/Juli-AI-v2/.env
sudo systemctl restart juli-api
```

Template reference: [`env/api.env.example`](env/api.env.example).

Manual CORS preflight check:

```bash
curl -sSI -H "Origin: https://app-juli.com" https://api.app-juli.com/health \
  | grep -i '^access-control-allow-origin:'
# Expect: access-control-allow-origin: https://app-juli.com
```

---

## Automated smoke test

From the repo root on the review VPS:

```bash
cd ~/Juli-AI-v2
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
```

`smoke-test.sh` asserts:

| # | Check | What it proves |
|---|-------|----------------|
| 1 | DNS resolves | `app-juli.com` and `api.app-juli.com` A records point at the VPS |
| 2 | TLS handshake | Public HTTPS terminates on both domains |
| 3 | Frontend load | `https://app-juli.com/` returns 2xx |
| 4 | `/health` | Backend returns 2xx JSON |
| 5 | OAuth callback | `GET /v1/auth/tiktok/callback` does not 5xx on missing params |
| 6 | Reviewer login | `/login` chunk contains demo entry markers |
| 7 | Home chunks | `/` route JS chunks return 200 (no stale partial build) |
| 8 | CORS | `Access-Control-Allow-Origin` includes `https://app-juli.com` |

DNS/TLS-only mode (before apps are up, #256):

```bash
./infra/scripts/smoke-test.sh --dns-tls-only
```

---

## HITL sign-off checklist

Operator completes after `smoke-test.sh` passes with zero failures:

### Infrastructure

- [x] DNS: `app-juli.com` A record → review VPS (`5.223.68.27`)
- [x] DNS: `api.app-juli.com` A record → review VPS (`5.223.68.27`)
- [x] TLS: Let's Encrypt certificates valid on both domains
- [x] Nginx: `juli-web` and `juli-api` upstreams reachable

### Application surface

- [x] Frontend: `https://app-juli.com/` loads over HTTPS (200)
- [x] Health: `https://api.app-juli.com/health` returns 2xx JSON (200)
- [x] OAuth: `https://api.app-juli.com/v1/auth/tiktok/callback` handles missing
      params without a 5xx crash (400)
- [x] Reviewer login: `https://app-juli.com/login` shows one-click demo entry
      (see [`reviewer-login-runbook.md`](reviewer-login-runbook.md))
- [x] CORS: `CORS_ALLOW_ORIGINS=https://app-juli.com` on VPS; preflight allows
      the frontend origin

### Review-only confirmation

Explicitly confirm before closing #261:

- [x] **No production users** are onboarded or invited to this deployment
- [x] **No production traffic** is routed to this deployment
- [x] **No persistent business data** (seller orders, returns, ads, payouts) is
      required to complete App Review — mock/UI-only data is sufficient

---

## CI validation (no live domain)

```bash
python -m pytest tests/unit/test_phase_2_5_smoke_checklist.py -q
```

Full Phase 2.5 deploy contract suite:

```bash
python -m pytest tests/unit/test_phase_2_5_deploy_config.py \
  tests/unit/test_phase_2_5_frontend_deploy.py \
  tests/unit/test_phase_2_5_backend_deploy.py \
  tests/unit/test_phase_2_5_reviewer_login.py \
  tests/unit/test_phase_2_5_smoke_checklist.py -q
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| CORS preflight fails | Set `CORS_ALLOW_ORIGINS=https://app-juli.com` in `.env`; restart `juli-api` |
| `/health` returns 502 | `sudo systemctl status juli-api`; check `DATABASE_URL` |
| Login missing demo markers | Rebuild with `./infra/scripts/build-frontend-review.sh`; restart `juli-web` |
| Home chunks return 400 | Stale partial build — run `build-frontend-review.sh` and restart `juli-web` |
| OAuth callback 5xx | Check `juli-api` logs; verify TikTok env vars on VPS |

See also [`app-review-runbook.md`](app-review-runbook.md) troubleshooting section.

---

## Operator sign-off record

Completed sign-off (#261 closed 2026-07-03):

```
App Review smoke sign-off (#261)
Date: 2026-07-03
Operator: root@juli-product-testing
VPS: juli-product-testing (5.223.68.27)
smoke-test.sh result: 11 passed, 0 failed
CORS_ALLOW_ORIGINS verified: yes
Review-only confirmed (no prod users/traffic/data): yes
```

VPS transcript:

```
grep CORS_ALLOW_ORIGINS=https://app-juli.com ~/Juli-AI-v2/.env
→ CORS_ALLOW_ORIGINS=https://app-juli.com

APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
→ 11 passed, 0 failed (DNS, TLS, frontend, /health, OAuth callback, reviewer login, home chunks, CORS)
```