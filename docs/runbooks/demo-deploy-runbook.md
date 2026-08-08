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
https://demo.app-juli.com  →  Nginx  →  upstream juli_demo  →  Next.js production build
                                             ↑
                        /etc/nginx/juli/demo-upstream.conf  (the deploy owns this file)
```

**The live upstream definition is the single source of truth for what is serving** (#839).
Nginx does not proxy to a fixed port any more; it proxies to the named upstream `juli_demo`,
whose definition the deploy replaces atomically at cutover and then reloads nginx
gracefully. Ask the server what is live:

```bash
grep 'server 127.0.0.1' /etc/nginx/juli/demo-upstream.conf     # what is serving now
grep 'server 127.0.0.1' /etc/nginx/juli/demo-upstream.conf.prev # the undo
```

The Demo lane alternates between **two** loopback ports, `3001` and `3021`. Whichever the
live definition names is serving; a new release is started and verified on the other one
and then promoted by repointing the definition. Nothing is restarted at cutover, so no
in-flight request is dropped.

| Item | Value |
|------|-------|
| Domain | `demo.app-juli.com` |
| Service | `juli-demo` (systemd) |
| Upstream | `upstream juli_demo` → `/etc/nginx/juli/demo-upstream.conf` (ports 3001/3021) |
| App path | `apps/demo/` (pnpm monorepo) |
| Release symlink | `~/releases/demo-current` |
| Deploy history | `~/releases/demo-deploy-history.log` |
| Nginx vhost | `infra/nginx/demo.app-juli.com.conf` |
| Upstream seed | `infra/nginx/demo-upstream.conf` |
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
| `demo.app-juli.com` | `juli-demo` | 3001 / 3021 (alternating) |

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

Config source: `infra/nginx/demo.app-juli.com.conf` (proxies to `upstream juli_demo`).

### One-time upstream indirection (#839) — required before the first graceful deploy

`demo.app-juli.com.conf` now `include`s `/etc/nginx/juli/demo-upstream.conf`. That include
is an explicit filename, so **if the file is missing nginx refuses to load every site, not
just Demo.** `provision-nginx.sh` seeds it before installing any vhost, and never
overwrites an existing one (the existing one is what is currently serving):

```bash
cd ~/Juli-AI-v2 && git pull
sudo ./infra/scripts/provision-nginx.sh
```

Pass: prints `Seeded /etc/nginx/juli/demo-upstream.conf ...` (or `Kept ...` on a re-run),
then `Nginx reloaded.` Failure: `nginx -t` reports the error and **nothing is reloaded** —
the configuration nginx already loaded keeps serving. `deploy-demo-release.sh` refuses to
run until this file exists; it will not create it, because doing so would hide that nginx
never had it.

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

**On the VPS, `juli-demo` runs from `~/releases/demo-current/apps/demo`, not from the
canonical `~/Juli-AI-v2` checkout.** Building only in `~/Juli-AI-v2` updates HTML on
disk there while the service still serves an older release — smoke tests then fail with
stale `/_next/static/...` 404s. Always deploy with:

```bash
cd ~/Juli-AI-v2
./infra/scripts/deploy-demo-release.sh
```

Local-only rebuild (no systemd path guard):

```bash
DEMO_BUILD_ALLOW_MISMATCH=1 ./infra/scripts/build-demo.sh
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
2. Read `/etc/nginx/juli/demo-upstream.conf` to learn the live port; the candidate takes
   the other member of the pair (3001 ↔ 3021)
3. Additive-only migration gate (#834) — **before** any candidate starts
4. Fetch and place the CI release artifact (#837); nothing is compiled on the server
5. Free the candidate port, then start the release there, **loopback-bound and private**
6. Run the #833 verification harness against the candidate — every live mutation below is
   gated on this passing
7. **Graceful cutover (#839):** render the new upstream definition, retain the current one
   as `demo-upstream.conf.prev`, `mv -Tf` the new one into place, `nginx -t`, then
   `systemctl reload nginx`. Nothing is restarted, so in-flight requests complete.
8. Atomically flip `~/releases/demo-current` symlink
9. Refresh `/etc/systemd/system/juli-demo.service` and record the live port in
   `/etc/juli/demo-runtime.env`, so a **reboot** brings the durable unit back on the port
   nginx is pointed at
10. Local health check on the newly live port: `/decisions` must return 2xx
11. Append to `~/releases/demo-deploy-history.log`, then prune (only after success)

**If `nginx -t` rejects the new definition**, nothing is reloaded, the retained definition
is put back, the deploy exits non-zero, and the site keeps serving the configuration nginx
already loaded. `demo-current` is not repointed.

**The previous instance keeps running** on its port after cutover. That is deliberate — it
is what makes the retained definition an instant undo. It is stopped at the start of the
*next* deploy, when its port is needed and it has long since drained.

---

## Rollback (Demo only)

Restore the previous healthy Demo release **without affecting** App Review services:

```bash
cd ~/Juli-AI-v2
./infra/scripts/rollback-demo-release.sh                # previous Demo release
./infra/scripts/rollback-demo-release.sh <sha-or-short-sha>
```

Rollback starts the target release on the free port, waits for it to answer, and only then
repoints the upstream definition and reloads nginx — the same graceful switch a deploy
uses. If the target never becomes healthy, **nothing is switched** and the current release
keeps serving. It never restarts the live process and never prunes a release worktree.

**Fastest undo of the release just cut over** — no restart and no wait, because the
instance the retained definition names is still running:

```bash
cp -p /etc/nginx/juli/demo-upstream.conf.prev /etc/nginx/juli/demo-upstream.conf \
  && nginx -t && systemctl reload nginx
```

Use the rollback script instead when that instance is gone (after a reboot) or to reach an
older release. Automating this undo on a failed post-cutover check is #840.

To restart Demo by hand outside a release — `sudo systemctl restart juli-demo` — note that
the unit binds `DEMO_LIVE_PORT` from `/etc/juli/demo-runtime.env`, so it will collide with
a promoted candidate already on that port. Stop that instance first, or just reload nginx
onto whichever port is healthy.

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

## Release evidence — static assets + rollback (ADR-035 VPS bridge)

Before flipping `~/releases/demo-current` on the VPS, prove the candidate build serves
reachable CSS/JS and renders branded styles in a browser — not only 2xx HTML.

| Gate | Command | Proves |
|------|---------|--------|
| Build integrity | `./infra/scripts/build-demo.sh` | Home + `/decisions` routes built (mock mode) |
| Static asset fetch | `./infra/scripts/verify-demo-static-assets.sh` | Referenced CSS/JS from `/` and `/decisions` return 200 |
| Public smoke | `./infra/scripts/smoke-test-demo.sh` | DNS, TLS, HTTPS routes, local upstream when on VPS |
| Browser styled check | `pnpm --filter @juli/demo test:e2e -- e2e/exit-gate/static-asset-render.spec.ts` | Non-default computed styles + Home → Decisions nav against production build |

Run locally or on the deploy worktree **before** cutover; zero public canary traffic on
this VPS bridge path (ECS candidate verification deferred to #498).

**Rollback (Demo only)** — restore the previous healthy release without touching App Review:

```bash
cd ~/Juli-AI-v2
./infra/scripts/rollback-demo-release.sh                # previous Demo release
./infra/scripts/rollback-demo-release.sh <sha-or-short-sha>
```

Rollback re-points `~/releases/demo-current`, restarts `juli-demo` only, and verifies
local `/decisions` health before success. Contract tests:
`pytest -q tests/unit/test_demo_rollback_evidence.py`.

Release evidence plan: `agent-runtime/artifacts/release-evidence-plan-issue-499.json`.

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
