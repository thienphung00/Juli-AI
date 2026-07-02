# Handoff: issue #256 — VPS + Nginx + HTTPS

**Branch:** `feature/issue-256-vps-nginx-https`  
**Type:** HITL — operator sign-off complete on VPS

## Summary

Implemented **#256** with VPS wiring runbook, Nginx provision script, smoke-test
`--dns-tls-only` mode, and **phone OTP disabled** for App Review (UI-only reviewer login).

## HITL sign-off (operator)

- [x] DNS configured
- [x] HTTPS configured
- [x] Automatic certificate renewal enabled
- [x] Frontend accessible over HTTPS
- [x] Backend accessible over HTTPS
- [x] Nginx reverse proxy working
- [x] Backend health endpoint responding
- [x] Redis not installed
- [x] Single-process deployment

## Deliverables

| Path | Purpose |
|------|---------|
| `infra/deploy/vps-wiring-runbook.md` | HITL DNS → Nginx → Certbot → sign-off |
| `infra/deploy/provision-nginx.sh` | Install split vhosts on VPS |
| `infra/deploy/smoke-test.sh --dns-tls-only` | DNS/TLS validation |
| `infra/deploy/env/web.env.example` | `NEXT_PUBLIC_UI_ONLY=1` |
| `infra/deploy/env/api.env.example` | `PHONE_OTP_ENABLED=false` |
| `web/src/components/LoginForm.tsx` | One-click reviewer login (UI-only) |
| `docs/features/app_review_deployment/issues.md` | Slice index |

## VPS redeploy after merge

Single repo checkout at `~/Juli-AI-v2`:

```bash
cd ~/Juli-AI-v2
git pull

# Backend — ~/Juli-AI-v2/.env (PHONE_OTP_ENABLED=false)
source .venv/bin/activate
set -a && source .env && set +a
uvicorn src.apps.api_gateway.api.main:app --host 0.0.0.0 --port 8000

# Frontend — ~/Juli-AI-v2/web/.env.production (NEXT_PUBLIC_UI_ONLY=1)
cd web
npm ci && npm run build
npm run start -- --port 3000 --hostname 0.0.0.0
```

## Next

- **#259** — TikTok OAuth callback handler
- **#254** — E2E App Review verification
