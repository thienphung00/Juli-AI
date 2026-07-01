# App Review Deployment Runbook (Phase 2.5-d)

> **Scope:** Public, HTTPS-accessible Juli deployment for **TikTok App Review only**.
> Not production: no real users, no production traffic, no persistent business data.
> **Authority:** [`EXECUTION.md`](../../EXECUTION.md) ·
> [`docs/phases/phase-2.5-deployment.md`](../../docs/phases/phase-2.5-deployment.md)

This runbook splits the **frontend** and **backend** deploy paths so each is
independently restartable on a single review **VPS** fronted by **Nginx** with
**HTTPS**. Live DNS/TLS/VPS wiring is **HITL** (issue #256); this slice ships the
documentation and config samples that make that wiring repeatable.

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

### Config files in this directory

| Path | Purpose |
|------|---------|
| [`nginx/app-juli.com.conf`](nginx/app-juli.com.conf) | Frontend vhost → `127.0.0.1:3000` |
| [`nginx/api.app-juli.com.conf`](nginx/api.app-juli.com.conf) | Backend vhost → `127.0.0.1:8000`, health + OAuth callback |
| [`systemd/juli-web.service`](systemd/juli-web.service) | Frontend service unit |
| [`systemd/juli-api.service`](systemd/juli-api.service) | Backend service unit |
| [`env/web.env.example`](env/web.env.example) | Frontend env template (placeholders) |
| [`env/api.env.example`](env/api.env.example) | Backend env template (placeholders) |
| [`smoke-test.sh`](smoke-test.sh) | DNS/TLS/frontend/health/OAuth checklist |

---

## Environment variables (no secrets in git)

Real values are set **only on the VPS** env files (`/opt/juli/api/.env`,
`/opt/juli/web/.env.production`) or a secret manager. **Do not commit** real
credentials — the templates in `env/` hold placeholders **outside** any
functional value.

**Backend (`api.app-juli.com`)** — see [`env/api.env.example`](env/api.env.example):

| Var | Required | Notes |
|-----|----------|-------|
| `DATABASE_URL` | Yes | Opened at startup (FastAPI lifespan). Supabase Postgres for review. |
| `SUPABASE_URL` | Reviewer login | Supabase free-tier project. |
| `SUPABASE_ANON_KEY` | Reviewer login | Secret — VPS only. |
| `SUPABASE_JWT_SECRET` | Reviewer login | Secret — VPS only. |
| `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` | OAuth | Partner Center review app. Secret — VPS only. |
| `CORS_ALLOW_ORIGINS` | Yes | Set to `https://app-juli.com`. |

**Frontend (`app-juli.com`)** — see [`env/web.env.example`](env/web.env.example):

| Var | Required | Notes |
|-----|----------|-------|
| `NEXT_PUBLIC_API_URL` | Yes | `https://api.app-juli.com` (baked at build time). |

App Review **skips** `REDIS_URL`, cron, workers, ML batch, polling, and webhook
services. If a required startup path forces one of these, stop and split it into a
separate issue (PRD rollback rule).

---

## Deploy — frontend and backend are independent

The two services are deployed and restarted independently. A frontend rebuild
never restarts the backend and vice versa.

### Frontend (`juli-web`)

```bash
cd /opt/juli/web
git pull
npm ci
npm run build
sudo systemctl restart juli-web
sudo systemctl status juli-web --no-pager
```

### Backend (`juli-api`)

```bash
cd /opt/juli/api
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart juli-api
sudo systemctl status juli-api --no-pager
```

### One-time install

```bash
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
per issue #256. Once wired, run the checklist:

```bash
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
- [ ] Reviewer login path (Supabase OTP) or a reviewer-safe UI path works.
- [ ] CORS allows `https://app-juli.com`.
- [ ] No production users, production traffic, or persistent business data are
      required to complete App Review.

---

## Rollback / stop condition

If the review path starts requiring production-only services (Redis, workers,
cron, ML batch, polling, webhooks, HA tuning), **stop** and split the dependency
into a new issue. Phase 2.5 stays reviewer-accessible and minimal; production
hardening moves to Phase 3+ / Phase 5.
