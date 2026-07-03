# App Review Deployment Runbook (Phase 2.5-d)

> **Scope:** Public, HTTPS-accessible Juli deployment for **TikTok App Review only**.
> Not production: no real users, no production traffic, no persistent business data.
> **Authority:** [`EXECUTION.md`](../../EXECUTION.md) ·
> [`docs/phases/phase-2.5-deployment.md`](../../docs/phases/phase-2.5-deployment.md)

This runbook splits the **frontend** and **backend** deploy paths so each is
independently restartable on a single review **VPS** fronted by **Nginx** with
**HTTPS**. Live DNS/TLS/VPS wiring is **HITL** (issue #256) — follow
[`vps-wiring-runbook.md`](vps-wiring-runbook.md). This slice ships the documentation
and config samples that make that wiring repeatable.

---

## Topology

```
                         Internet
                            │  HTTPS (443)
                    ┌───────▼────────┐
                    │     Nginx      │  TLS termination + routing
                    └───┬────────┬───┘
        app-juli.com    │        │   api.app-juli.com
                        │        │
             ┌──────────▼─┐   ┌──▼───────────┐
             │ juli-web   │   │ juli-api      │
             │ Next.js    │   │ FastAPI       │
             │ 127.0.0.1: │   │ 127.0.0.1:    │
             │   3000     │   │   8000        │
             └────────────┘   └───────────────┘
```

| Component | Value |
|-----------|-------|
| Host | Single review **VPS** (no HA, no autoscaling) |
| Reverse proxy | **Nginx**, terminates **HTTPS** for both domains |
| Frontend upstream | `juli-web` → `127.0.0.1:3000` (Next.js) |
| Backend upstream | `juli-api` → `127.0.0.1:8000` (FastAPI/uvicorn) |
| Frontend domain | `app-juli.com` |
| Backend domain | `api.app-juli.com` |
| OAuth callback | `https://api.app-juli.com/v1/auth/tiktok/callback` |
| TLS | Let's Encrypt via certbot (renewable) |
| VPS checkout | `~/Juli-AI-v2` — single monorepo (`web/` = frontend, repo root = backend) |

### Config files in this directory

| Path | Purpose |
|------|---------|
| [`nginx/app-juli.com.conf`](nginx/app-juli.com.conf) | Frontend vhost → `127.0.0.1:3000` |
| [`nginx/api.app-juli.com.conf`](nginx/api.app-juli.com.conf) | Backend vhost → `127.0.0.1:8000`, health + OAuth callback |
| [`systemd/juli-web.service`](systemd/juli-web.service) | Frontend service unit |
| [`systemd/juli-api.service`](systemd/juli-api.service) | Backend service unit |
| [`env/web.env.example`](env/web.env.example) | Frontend env template (placeholders) |
| [`env/api.env.example`](env/api.env.example) | Backend env template (placeholders) |
| [`vps-wiring-runbook.md`](vps-wiring-runbook.md) | HITL DNS + Nginx + Certbot (#256) |
| [`frontend-deploy-runbook.md`](frontend-deploy-runbook.md) | Deploy Next.js frontend on VPS (#257) |
| [`provision-nginx.sh`](provision-nginx.sh) | Install Nginx vhosts on the VPS (#256) |
| [`provision-frontend.sh`](provision-frontend.sh) | Install `juli-web` + production build (#257) |
| [`build-frontend-review.sh`](build-frontend-review.sh) | `npm ci && npm run build` with UI-only login |
| [`smoke-test.sh`](smoke-test.sh) | DNS/TLS/frontend/health/OAuth checklist |

---

## Environment variables (no secrets in git)

Real values are set **only on the VPS** env files (`~/Juli-AI-v2/.env`,
`~/Juli-AI-v2/web/.env.production`) or a secret manager. **Do not commit** real
credentials — the templates in `env/` hold placeholders **outside** any
functional value.

**Backend (`api.app-juli.com`)** — see [`env/api.env.example`](env/api.env.example):

| Var | Required | Notes |
|-----|----------|-------|
| `DATABASE_URL` | Yes | Opened at startup (FastAPI lifespan). Supabase Postgres for review. |
| `SUPABASE_JWT_SECRET` | Protected routes | Secret — VPS only (optional when frontend uses UI-only demo login). |
| `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` | OAuth | Partner Center review app. Secret — VPS only. |
| `CORS_ALLOW_ORIGINS` | Yes | Set to `https://app-juli.com`. |

**Frontend (`app-juli.com`)** — see [`env/web.env.example`](env/web.env.example):

| Var | Required | Notes |
|-----|----------|-------|
| `NEXT_PUBLIC_API_URL` | Yes | `https://api.app-juli.com` (baked at build time). |
| `NEXT_PUBLIC_UI_ONLY` | App Review | Set to `1` — one-click demo login and mock data. |

App Review **skips** `REDIS_URL`, cron, workers, ML batch, polling, and webhook
services. If a required startup path forces one of these, stop and split it into a
separate issue (PRD rollback rule).

---

## Deploy — frontend and backend are independent

The two services are deployed and restarted independently. A frontend rebuild
never restarts the backend and vice versa.

### Frontend (`juli-web`)

`NEXT_PUBLIC_UI_ONLY` is **baked at build time**. Restarting `juli-web` without
rebuilding cannot switch login behavior.

```bash
cd ~/Juli-AI-v2
git pull

# Ensure env exists (copy once from infra/deploy/env/web.env.example)
grep NEXT_PUBLIC_UI_ONLY=1 web/.env.production

# Clean build with UI-only login enforced
chmod +x infra/deploy/build-frontend-review.sh
./infra/deploy/build-frontend-review.sh

sudo systemctl restart juli-web
sudo systemctl status juli-web --no-pager

# Must show UI-only login checks (not just 7 DNS/TLS/health checks)
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/deploy/smoke-test.sh
```

### Backend (`juli-api`)

```bash
cd ~/Juli-AI-v2
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart juli-api
sudo systemctl status juli-api --no-pager
```

### One-time install

```bash
cd ~/Juli-AI-v2

# systemd units
sudo cp infra/deploy/systemd/juli-web.service /etc/systemd/system/
sudo cp infra/deploy/systemd/juli-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now juli-web juli-api

# nginx vhosts
sudo cp infra/deploy/nginx/app-juli.com.conf     /etc/nginx/sites-available/
sudo cp infra/deploy/nginx/api.app-juli.com.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/app-juli.com.conf     /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/api.app-juli.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS certificates (HITL — requires DNS pointing at the VPS first)
sudo certbot --nginx -d app-juli.com -d www.app-juli.com
sudo certbot --nginx -d api.app-juli.com
```

---

## Validation

### CI (automated, no live domain required)

CI validates the config contracts without touching the VPS:

```bash
python -m pytest tests/unit/test_phase_2_5_deploy_config.py -q
```

These tests assert the topology docs, split frontend/backend units, secret-free
env templates, and smoke-test coverage stay in sync with this runbook.

### Live smoke test (HITL, after DNS + TLS are wired on the VPS)

Full domain wiring (DNS records, TLS issuance) stays **HITL / manual** on the VPS
per issue #256. Once wired, run the checklist from the repo root:

```bash
cd ~/Juli-AI-v2
./infra/deploy/smoke-test.sh
# or point at other hostnames:
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/deploy/smoke-test.sh
```

`smoke-test.sh` covers DNS resolution, TLS handshake, frontend load,
`GET /health`, and the OAuth callback route (asserts no 5xx on missing params).

---

## Reviewer acceptance checklist

- [ ] `https://app-juli.com/` resolves over HTTPS and loads the frontend.
- [ ] `https://api.app-juli.com/health` returns a 2xx JSON response.
- [ ] `https://api.app-juli.com/v1/auth/tiktok/callback` exists and handles
      missing/invalid OAuth params without a 5xx crash.
- [ ] Reviewer login uses one-click demo entry (`NEXT_PUBLIC_UI_ONLY=1`).
- [ ] CORS allows `https://app-juli.com`.
- [ ] No production users, production traffic, or persistent business data are
      required to complete App Review.

---

## Troubleshooting

### Blank homepage after login (or smoke test: home chunk returned 400)

Next.js returns **400** (not 404) when HTML references JS chunk hashes that the
running `juli-web` process cannot serve. A **partial** rebuild can leave `/login`
working while `/` (Home) chunks 400 — the app shows a blank page after demo login.

```bash
cd ~/Juli-AI-v2
git pull
./infra/deploy/build-frontend-review.sh   # rm -rf .next && npm run build
sudo systemctl restart juli-web
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/deploy/smoke-test.sh
```

Quick check on the VPS:

```bash
home_chunk="$(curl -sS https://app-juli.com/ | grep -oE '/_next/static/chunks/app/page-[^"]+\.js' | head -1)"
curl -s -o /dev/null -w '%{http_code}\n' "https://app-juli.com${home_chunk}"
# Expect 200 — 400 means stale build.
```

Confirm `juli-web` runs `npm run start` (production), not `npm run dev`. The tmux
`web` session must not override systemd with a dev server on port 3000.

### Smoke test: login chunk missing demo markers

`NEXT_PUBLIC_UI_ONLY` is baked at build time. If the smoke test fails on demo
markers, the running build predates the one-click reviewer login or was built
without `./infra/deploy/build-frontend-review.sh` (which forces `NEXT_PUBLIC_UI_ONLY=1`).

```bash
grep NEXT_PUBLIC_UI_ONLY=1 web/.env.production
./infra/deploy/build-frontend-review.sh
sudo systemctl restart juli-web
```

Frontend deploy steps: [`frontend-deploy-runbook.md`](frontend-deploy-runbook.md) (#257).

---

## Rollback / stop condition

If the review path starts requiring production-only services (Redis, workers,
cron, ML batch, polling, webhooks, HA tuning), **stop** and split the dependency
into a new issue. Phase 2.5 stays reviewer-accessible and minimal; production
hardening moves to Phase 3+ / Phase 5.
