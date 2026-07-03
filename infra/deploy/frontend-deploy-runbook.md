# Frontend deploy runbook — App Review (#257)

> **Parent:** [#249](https://github.com/thienphung00/Juli-AI/issues/249) · **Issue:** [#257](https://github.com/thienphung00/Juli-AI/issues/257)  
> **Prerequisite:** [#256](https://github.com/thienphung00/Juli-AI/issues/256) — DNS, Nginx, and HTTPS wired  
> **Next:** [#258](backend-deploy-runbook.md) (backend) → [#254](https://github.com/thienphung00/Juli-AI/issues/254) (E2E)

Deploy the existing `web/` Next.js app behind `https://app-juli.com/` for TikTok
reviewers. Landing page and demo app work remain **deferred to Phase 3** — this
slice serves only the legacy `web/` reviewer UI.

---

## Topology

```
https://app-juli.com  →  Nginx  →  juli-web (127.0.0.1:3000)  →  Next.js production build
```

| Item | Value |
|------|-------|
| Service | `juli-web` (systemd) |
| Upstream | `127.0.0.1:3000` |
| Build env | `~/Juli-AI-v2/web/.env.production` |
| Build script | `./infra/deploy/build-frontend-review.sh` |
| Provision script | `sudo ./infra/deploy/provision-frontend.sh` |

---

## One-time deploy (VPS)

Run on the review VPS after [#256](vps-wiring-runbook.md) sign-off:

```bash
cd ~/Juli-AI-v2
git pull

# 1. Frontend env (placeholders only in git — real file stays on VPS)
cp -n infra/deploy/env/web.env.example web/.env.production
grep NEXT_PUBLIC_API_URL=https://api.app-juli.com web/.env.production

# 2. Install systemd unit, build, and start juli-web
chmod +x infra/deploy/provision-frontend.sh infra/deploy/build-frontend-review.sh
sudo ./infra/deploy/provision-frontend.sh

# 3. Verify frontend + login over public HTTPS
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/deploy/smoke-test.sh
```

`provision-frontend.sh` copies `juli-web.service`, runs `build-frontend-review.sh`
(`npm ci && npm run build` with `NEXT_PUBLIC_API_URL` from env), and enables the
service on `127.0.0.1:3000`.

---

## Build contract

`NEXT_PUBLIC_*` values are **baked at build time**. Always rebuild before restarting
`juli-web` when env changes.

```bash
cd ~/Juli-AI-v2

# Required in web/.env.production:
#   NEXT_PUBLIC_API_URL=https://api.app-juli.com
#   NEXT_PUBLIC_UI_ONLY=1   (reviewer demo login — see fallback below)

./infra/deploy/build-frontend-review.sh   # npm ci && rm -rf .next && npm run build
sudo systemctl restart juli-web
```

Manual equivalent (same contract):

```bash
cd ~/Juli-AI-v2/web
set -a && source .env.production && set +a
export NEXT_PUBLIC_UI_ONLY=1
npm ci && rm -rf .next && npm run build
sudo systemctl restart juli-web
```

---

## UI-only fallback (`NEXT_PUBLIC_UI_ONLY=1`)

When API auth is not ready, reviewers use **one-click demo login** — no phone OTP,
no production users. `build-frontend-review.sh` forces `NEXT_PUBLIC_UI_ONLY=1` at
build time even if `.env.production` omits it.

If login shows phone OTP instead of demo entry:

```bash
grep NEXT_PUBLIC_UI_ONLY=1 web/.env.production
./infra/deploy/build-frontend-review.sh
sudo systemctl restart juli-web
```

Backend deploy ([#258](https://github.com/thienphung00/Juli-AI/issues/258)) is
independent; the frontend can ship first with UI-only mode.

---

## Redeploy (code or env change)

```bash
cd ~/Juli-AI-v2
git pull
./infra/deploy/build-frontend-review.sh
sudo systemctl restart juli-web
sudo systemctl status juli-web --no-pager
```

Do **not** run `npm run dev` on port 3000 — Nginx expects the production server
from `juli-web` (`npm run start -- --port 3000 --hostname 127.0.0.1`).

---

## Sign-off checklist

- [ ] `web/.env.production` sets `NEXT_PUBLIC_API_URL=https://api.app-juli.com`
- [ ] `juli-web` is active (`systemctl is-active juli-web`)
- [ ] `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/` returns 2xx
- [ ] `https://app-juli.com/` loads over HTTPS (no local setup required)
- [ ] `https://app-juli.com/login` loads and shows demo login entry
- [ ] `./infra/deploy/smoke-test.sh` passes frontend + login checks
- [ ] Landing page / `demo.app-juli.com` work **not** started (Phase 3)

---

## Troubleshooting

### Blank homepage after login

A partial rebuild can leave `/login` working while `/` (Home) chunks return **400**.
Rebuild and restart together:

```bash
cd ~/Juli-AI-v2
./infra/deploy/build-frontend-review.sh
sudo systemctl restart juli-web
```

Quick check:

```bash
home_chunk="$(curl -sS https://app-juli.com/ | grep -oE '/_next/static/chunks/app/page-[^"]+\.js' | head -1)"
curl -s -o /dev/null -w '%{http_code}\n' "https://app-juli.com${home_chunk}"
# Expect 200 — 400 means stale build.
```

### 502 from Nginx

`juli-web` is down or not listening on `127.0.0.1:3000`:

```bash
sudo systemctl status juli-web --no-pager
sudo journalctl -u juli-web -n 50 --no-pager
```

Full deploy reference: [`app-review-runbook.md`](app-review-runbook.md).
