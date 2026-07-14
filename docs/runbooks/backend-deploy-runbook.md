# Backend deploy runbook — App Review (#258)

> **Parent:** [#249](https://github.com/thienphung00/Juli-AI/issues/249) · **Issue:** [#258](https://github.com/thienphung00/Juli-AI/issues/258)  
> **Prerequisite:** [#256](https://github.com/thienphung00/Juli-AI/issues/256) — DNS, Nginx, and HTTPS wired  
> **Next:** [#259](https://github.com/thienphung00/Juli-AI/issues/259) (OAuth callback) → [#254](https://github.com/thienphung00/Juli-AI/issues/254) (E2E)

Deploy the existing FastAPI app behind `https://api.app-juli.com/` for TikTok App
Review. This slice serves only the endpoints required for review: `/health`, auth
surface, and (after #259) the TikTok OAuth callback.

> **Update (#381):** `POST /webhooks/tiktok` is now also served by this same
> `juli-api` process (see `backend/src/juli_backend/api/routes/webhook_tiktok.py`).
> No new systemd unit or Nginx location is required — the existing catch-all
> `location /` in `infra/nginx/api.app-juli.com.conf` already proxies it to
> `127.0.0.1:8000`. Partner Center webhook deliveries need `TIKTOK_APP_KEY` /
> `TIKTOK_APP_SECRET` set (already required for OAuth, below); no other new
> service is deployed for webhooks.

---

## Topology

```
https://api.app-juli.com  →  Nginx  →  juli-api (127.0.0.1:8000)  →  FastAPI (uvicorn)
```

| Item | Value |
|------|-------|
| Service | `juli-api` (systemd) |
| Upstream | `127.0.0.1:8000` |
| Env file | `~/Juli-AI-v2/.env` (from `infra/scripts/env/api.env.example`) |
| ASGI entry | `backend.api.api.main:app` |
| Provision script | `sudo ./infra/scripts/provision-backend.sh` |

---

## Required env vars (startup only)

The API opens the database engine at startup via FastAPI lifespan. Set these on the
VPS only — never commit real values.

| Var | Required | Notes |
|-----|----------|-------|
| `DATABASE_URL` | Yes | Supabase Postgres for review |
| `CORS_ALLOW_ORIGINS` | Yes | `https://app-juli.com` |
| `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` | OAuth (#259) | Partner Center review app |
| `TIKTOK_TOKEN_ENCRYPTION_KEY` | OAuth persistence (#259) | Dedicated secret for encrypted token storage |
| `SUPABASE_JWT_SECRET` | Protected routes | Optional when frontend uses UI-only demo login |

See [`env/api.env.example`](env/api.env.example). App Review **does not** require
`REDIS_URL`, cron, workers, ML batch jobs, polling, or a *separate* webhook
service — TikTok webhook ingress (#381) is a route on this same `juli-api`
process, not an additional deploy target. If startup forces one of the former,
stop and split the dependency into a new issue.

---

## Alembic migrations

**Skip** full Alembic migrations for App Review unless a route needs persisted data.

`/health` only needs DB connectivity. **TikTok OAuth callback persistence** and
`GET /debug/tiktok/verify-connection` require the base identity tables from
revision `001`:

```bash
cd ~/Juli-AI-v2
.venv/bin/alembic upgrade 001
sudo systemctl restart juli-api
```

Without `users` / `shops` / `tiktok_credentials`, verify-connection returns
`503` JSON (not plain-text 500) after the hardened handler is deployed.

---

## One-time deploy (VPS)

Run on the review VPS after [#256](vps-wiring-runbook.md) sign-off:

```bash
cd ~/Juli-AI-v2
git pull

# 1. Backend env (placeholders only in git — real file stays on VPS)
cp -n infra/scripts/env/api.env.example .env
grep DATABASE_URL= .env
grep CORS_ALLOW_ORIGINS=https://app-juli.com .env

# 2. Install systemd unit, venv deps, and start juli-api
chmod +x infra/scripts/provision-backend.sh
sudo ./infra/scripts/provision-backend.sh

# 3. Verify backend health over public HTTPS
curl -sS https://api.app-juli.com/health
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
```

`provision-backend.sh` copies `juli-api.service`, ensures `.env` exists from the
template, runs `pip install -r requirements.txt` in `.venv`, and enables the service
on `127.0.0.1:8000` with a **single uvicorn worker**.

---

## Redeploy (code or env change)

```bash
cd ~/Juli-AI-v2
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart juli-api
sudo systemctl status juli-api --no-pager
```

Backend redeploy is **independent** of the frontend — restarting `juli-api` does not
restart `juli-web` and vice versa.

Manual equivalent:

```bash
cd ~/Juli-AI-v2
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp infra/systemd/juli-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart juli-api
```

---

## Sign-off checklist

- [ ] `.env` sets `DATABASE_URL` and `CORS_ALLOW_ORIGINS=https://app-juli.com`
- [ ] `juli-api` is active (`systemctl is-active juli-api`)
- [ ] `curl -sS http://127.0.0.1:8000/health` returns JSON with `"status":"ok"`
- [ ] `https://api.app-juli.com/health` returns 2xx JSON over HTTPS
- [ ] `./infra/scripts/smoke-test.sh` passes backend `/health` check
- [ ] Redis, cron, workers, ML jobs, polling, and a separate webhook service **not** started (webhook ingress runs as a route on `juli-api`, see #381)
- [ ] Alembic migrations **not** run unless OAuth/login persistence requires schema

---

## Troubleshooting

### 502 from Nginx

`juli-api` is down or not listening on `127.0.0.1:8000`:

```bash
sudo systemctl status juli-api --no-pager
sudo journalctl -u juli-api -n 50 --no-pager
```

### Startup fails on DATABASE_URL / Alembic "Connection refused"

Supabase **direct** hosts (`db.<project-ref>.supabase.co`) are **IPv6-only**.
Most VPS hosts are IPv4-only — `getent ahostsv4 db....supabase.co` returns
nothing, and connections to `2600:...` fail with `Connection refused`.

**Fix:** set `DATABASE_URL` in `.env` to the **Session pooler** URI (IPv4):

1. Supabase Dashboard → **Connect** → **Session mode** (port `5432`)
2. Copy the URI — host looks like `aws-0-<region>.pooler.supabase.com`
3. User is `postgres.<project-ref>` (not plain `postgres`)

```bash
# Confirm direct host has no IPv4 (expected on free/paid without IPv4 add-on)
getent ahostsv4 db.YOUR_PROJECT_REF.supabase.co   # empty = use pooler

# After updating .env
set -a && source .env && set +a
.venv/bin/alembic upgrade 001
sudo systemctl restart juli-api
```

Use the **same pooler `DATABASE_URL`** for both Alembic and `juli-api`.

### /health returns non-2xx over HTTPS but works locally

Nginx upstream or TLS may be misconfigured — re-run [#256](vps-wiring-runbook.md)
checks:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
curl -sS https://api.app-juli.com/health
```

Full deploy reference: [`app-review-runbook.md`](app-review-runbook.md).
