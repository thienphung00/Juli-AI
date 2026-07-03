# App Review Deployment — Operator Summary

> Quick reference for TikTok App Review sign-off. Full PRD:
> [`PRD.md`](PRD.md) · Issue index: [`issues.md`](issues.md)

**Review-only:** no production users, no production traffic, no persistent business data.

---

## Domains

| Domain | Role |
|--------|------|
| `app-juli.com` | Next.js frontend (`juli-web` on `127.0.0.1:3000`) |
| `api.app-juli.com` | FastAPI backend (`juli-api` on `127.0.0.1:8000`) |

---

## Required backend env (VPS `~/Juli-AI-v2/.env`)

```bash
DATABASE_URL=postgresql://...          # Supabase Session pooler
CORS_ALLOW_ORIGINS=https://app-juli.com
```

Verify before smoke test:

```bash
grep CORS_ALLOW_ORIGINS=https://app-juli.com ~/Juli-AI-v2/.env
```

---

## Smoke test commands

### CI (no live domain)

```bash
python -m pytest tests/unit/test_phase_2_5_deploy_config.py \
  tests/unit/test_phase_2_5_frontend_deploy.py \
  tests/unit/test_phase_2_5_backend_deploy.py \
  tests/unit/test_phase_2_5_reviewer_login.py \
  tests/unit/test_phase_2_5_smoke_checklist.py -q
```

### DNS + TLS only (before apps are deployed, #256)

```bash
cd ~/Juli-AI-v2
./infra/deploy/smoke-test.sh --dns-tls-only
```

### Full App Review sign-off (#261)

```bash
cd ~/Juli-AI-v2
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/deploy/smoke-test.sh
```

Checks: DNS · TLS · frontend load · `/health` · OAuth callback · reviewer login ·
CORS · home chunks.

### Manual spot checks

```bash
curl -sS https://api.app-juli.com/health
curl -sSI -H "Origin: https://app-juli.com" https://api.app-juli.com/health | grep -i access-control
curl -sS -o /dev/null -w '%{http_code}\n' https://api.app-juli.com/v1/auth/tiktok/callback
```

---

## Sign-off checklist

Full HITL checklist:
[`infra/deploy/smoke-checklist-runbook.md`](../../../infra/deploy/smoke-checklist-runbook.md).

- [ ] DNS: `app-juli.com` and `api.app-juli.com` resolve to the review VPS
- [ ] TLS: HTTPS handshake succeeds on both domains
- [ ] Frontend: `https://app-juli.com/` loads
- [ ] Health: `https://api.app-juli.com/health` returns 2xx JSON
- [ ] OAuth: callback route does not 5xx on missing params
- [ ] Reviewer login: `https://app-juli.com/login` shows one-click demo entry
- [ ] CORS: `CORS_ALLOW_ORIGINS=https://app-juli.com` on VPS; preflight allows frontend origin
- [ ] Review-only: no production users, traffic, or persistent business data

---

## Runbook index

| Slice | Runbook |
|-------|---------|
| VPS + Nginx + HTTPS (#256) | [`vps-wiring-runbook.md`](../../../infra/deploy/vps-wiring-runbook.md) |
| Frontend deploy (#257) | [`frontend-deploy-runbook.md`](../../../infra/deploy/frontend-deploy-runbook.md) |
| Backend deploy (#258) | [`backend-deploy-runbook.md`](../../../infra/deploy/backend-deploy-runbook.md) |
| Reviewer login (#260) | [`reviewer-login-runbook.md`](../../../infra/deploy/reviewer-login-runbook.md) |
| Smoke sign-off (#261) | [`smoke-checklist-runbook.md`](../../../infra/deploy/smoke-checklist-runbook.md) |
