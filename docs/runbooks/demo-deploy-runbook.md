# Demo deploy runbook — Phase 2.6 (#406)

> **Parent:** [#395](https://github.com/thienphung00/Juli-AI/issues/395) · **Issue:** [#406](https://github.com/thienphung00/Juli-AI/issues/406)  
> **Prerequisite:** Review VPS with Nginx installed ([#256](vps-wiring-runbook.md))  
> **Scope:** Repo config + contract tests + CI only in this slice (decision **4A** — no live VPS/DNS/TLS in CI)

Deploy `apps/demo` behind `https://demo.app-juli.com/` as an **independent** systemd/Nginx
surface. Mock mode is self-contained — **no backend credentials, DATABASE_URL, Supabase, or
TikTok secrets** are required at build or runtime. Rollback restores the previous healthy
Demo release without affecting app-juli.com or api.app-juli.com.

---

## Topology

```
https://demo.app-juli.com  →  Nginx  →  juli-demo (127.0.0.1:3001)  →  Next.js production build
```

| Item | Value |
|------|-------|
| Domain | `demo.app-juli.com` |
| Service | `juli-demo` (systemd) |
| Upstream | `127.0.0.1:3001` |
| App path | `apps/demo/` (pnpm monorepo) |
| Release symlink | `~/releases/demo-current` |
| Deploy history | `~/releases/demo-deploy-history.log` |
| Nginx vhost | `infra/nginx/demo.app-juli.com.conf` |
| Build script | `./infra/scripts/build-demo.sh` |
| Deploy script | `./infra/scripts/deploy-demo-release.sh` |
| Rollback script | `./infra/scripts/rollback-demo-release.sh` |
| Provision script | `sudo ./infra/scripts/provision-demo.sh` |
| Smoke test | `./infra/scripts/smoke-test-demo.sh` |

**Independent from App Review:**

| Surface | Service | Port |
|---------|---------|------|
| `app-juli.com` | `juli-web` | 3000 |
| `api.app-juli.com` | `juli-api` | 8000 |
| `demo.app-juli.com` | `juli-demo` | 3001 |

Restarting or rolling back Demo **does not** restart `juli-web` or `juli-api`.

---

## DNS (HITL — registrar)

Add an **A record** for the Demo subdomain pointing at the review VPS public IP:

| Hostname | Type | Value | TTL |
|----------|------|-------|-----|
| `demo.app-juli.com` | A | `VPS_IP` | 300–3600 |

Verify propagation:

```bash
dig +short demo.app-juli.com A
# Must return VPS_IP before continuing.
```

**Do not commit** the VPS IP or any credentials to git.

---

## Nginx + TLS (HITL — VPS)

After DNS propagates, install the Demo vhost (alongside existing App Review vhosts):

```bash
cd ~/Juli-AI-v2
git pull
chmod +x infra/scripts/provision-nginx.sh
sudo ./infra/scripts/provision-nginx.sh
# Installs app-juli.com.conf, api.app-juli.com.conf, and demo.app-juli.com.conf
```

Issue the Demo certificate:

```bash
sudo certbot --nginx -d demo.app-juli.com
sudo certbot renew --dry-run   # confirm auto-renew
```

Config source: `infra/nginx/demo.app-juli.com.conf` (proxies to `127.0.0.1:3001`).

---

## One-time Demo provision (HITL — VPS)

```bash
cd ~/Juli-AI-v2
git pull

# 1. Mock-only env (optional — template has no secrets)
cp -n infra/scripts/env/demo.env.example apps/demo/.env.production

# 2. Install systemd unit, build, and start juli-demo
chmod +x infra/scripts/provision-demo.sh infra/scripts/build-demo.sh
sudo ./infra/scripts/provision-demo.sh

# 3. Verify Demo over public HTTPS
./infra/scripts/smoke-test-demo.sh
```

`provision-demo.sh` copies `juli-demo.service`, runs `build-demo.sh`
(`pnpm install --filter @juli/demo... && pnpm build:demo`), and enables the service on
`127.0.0.1:3001`.

---

## Build contract (mock mode)

The Demo uses **hardcoded mock data** inside `apps/demo`. No `NEXT_PUBLIC_API_URL` or
backend env vars are required.

```bash
cd ~/Juli-AI-v2
./infra/scripts/build-demo.sh   # validates home + /decisions routes built
sudo systemctl restart juli-demo
```

Manual equivalent:

```bash
cd ~/Juli-AI-v2
pnpm install --frozen-lockfile --filter @juli/demo...
pnpm build:demo
sudo systemctl restart juli-demo
```

---

## Continuous Demo deploy

From the canonical checkout on the VPS:

```bash
cd ~/Juli-AI-v2
git fetch origin main && git checkout main && git pull
./infra/scripts/deploy-demo-release.sh          # deploy origin/main HEAD
./infra/scripts/deploy-demo-release.sh <sha>    # deploy specific commit
```

What `deploy-demo-release.sh` does:

1. Cut or reuse release worktree at `~/releases/<short-sha>/`
2. Build `apps/demo` via `build-demo.sh` (mock mode)
3. Atomically flip `~/releases/demo-current` symlink
4. `systemctl restart juli-demo` **only**
5. Local health check: `http://127.0.0.1:3001/decisions` must return 2xx
6. Append to `~/releases/demo-deploy-history.log`

---

## Rollback (Demo only)

Restore the previous healthy Demo release **without affecting** App Review services:

```bash
cd ~/Juli-AI-v2
./infra/scripts/rollback-demo-release.sh                # previous Demo release
./infra/scripts/rollback-demo-release.sh <sha-or-short-sha>
```

Rollback re-points `~/releases/demo-current`, restarts `juli-demo` only, and verifies
local `/decisions` health before success.

---

## Secrets hygiene

- **Do not commit** real env values — use `infra/scripts/env/demo.env.example` as the template.
- Demo mock mode requires **no** `DATABASE_URL`, Supabase keys, TikTok secrets, or
  `NEXT_PUBLIC_API_URL`.
- Optional `apps/demo/.env.production` on the VPS stays outside git.

---

## CI validation (no live deploy)

Contract tests run in CI on every PR:

```bash
python -m pytest tests/unit/test_phase_2_6_demo_deploy_config.py tests/unit/test_phase_2_6_demo_deploy.py -q
```

Production Demo build is validated separately via the `demo-frontend` job in
`.github/workflows/pr.yml` (`pnpm check:demo`).

Live VPS wiring (DNS, certbot, `provision-demo.sh`) remains **HITL/manual** (decision 4A).

---

## Smoke test

```bash
# Full check (DNS + TLS + public routes + local upstream when on VPS):
./infra/scripts/smoke-test-demo.sh

# DNS/TLS only (before juli-demo is running):
./infra/scripts/smoke-test-demo.sh --dns-tls-only
```

Mandatory route: `/decisions` (minimum Phase 2.6 exit gate).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `502` on demo.app-juli.com | `sudo systemctl status juli-demo`; rebuild with `build-demo.sh` |
| `/decisions` 404 after deploy | Re-run `build-demo.sh`; confirm `.next/server/app/decisions.html` exists |
| Rollback needed | `./infra/scripts/rollback-demo-release.sh` |
| App Review unaffected | Demo deploy/rollback does not touch juli-web or juli-api units |

---

## Related docs

- [`infra/deploy/README.md`](../../infra/deploy/README.md) — deploy index
- [`vps-wiring-runbook.md`](vps-wiring-runbook.md) — base Nginx + TLS for review VPS
- [`app-review-runbook.md`](app-review-runbook.md) — App Review frontend/backend (separate)
- [`docs/product/phases/phase-2.6/PRD.md`](../product/phases/phase-2.6/PRD.md) — Demo product spec
