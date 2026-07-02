# VPS Wiring Runbook — Issue #256 (P2.5-review-a)

> **Type:** HITL — execute on the review VPS and at your DNS registrar.  
> **Parent:** [#249](https://github.com/thienphung00/Juli-AI/issues/249) · **Blocked by:** [#253](https://github.com/thienphung00/Juli-AI/issues/253) (deploy config — merged)  
> **Next:** [#257](https://github.com/thienphung00/Juli-AI/issues/257) / [#258](https://github.com/thienphung00/Juli-AI/issues/258) (deploy frontend/backend) → [#254](https://github.com/thienphung00/Juli-AI/issues/254) (E2E verification)

Wire the single review **VPS** so `app-juli.com` and `api.app-juli.com` resolve publicly
over **HTTPS** via **Nginx**. This slice covers DNS, reverse-proxy routing, and TLS only —
application deploy and OAuth/login verification follow in later issues.

**Out of scope for #256:** Redis, webhook upstream, HA/multi-worker tuning, demo/dashboard
subdomains, production traffic.

---

## Prerequisites

| Item | Notes |
|------|-------|
| Review VPS | Ubuntu 22.04+ or Debian 12+ with a **static public IPv4** |
| SSH access | `sudo` for package install and Nginx reload |
| DNS registrar | Ability to create **A records** for `app-juli.com` and `api.app-juli.com` |
| Repo checkout | `/opt/juli` (or any path — scripts use `$REPO_ROOT`) |
| Firewall | Inbound **80/tcp** and **443/tcp** open to the VPS |

Record the VPS public IP as `VPS_IP` for the steps below. **Do not commit** the IP or
any credentials to git.

---

## Step 1 — DNS A records (registrar / HITL)

Create **A records** pointing both hostnames at the review VPS:

| Hostname | Type | Value | TTL |
|----------|------|-------|-----|
| `app-juli.com` | A | `VPS_IP` | 300–3600 |
| `www.app-juli.com` | A | `VPS_IP` | 300–3600 (optional; certbot may request it) |
| `api.app-juli.com` | A | `VPS_IP` | 300–3600 |

Wait for propagation, then confirm from your workstation:

```bash
dig +short app-juli.com A
dig +short api.app-juli.com A
# Both must return VPS_IP before continuing.
```

---

## Step 2 — Base packages (VPS)

On the VPS:

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo mkdir -p /var/www/certbot
sudo systemctl enable --now nginx
```

Ensure ports 80 and 443 are reachable (cloud security group + `ufw` if enabled).

---

## Step 3 — Install Nginx vhosts (repo script)

From the repo checkout on the VPS:

```bash
cd /opt/juli   # adjust if your checkout lives elsewhere
sudo ./infra/deploy/provision-nginx.sh
```

The script:

- Copies [`nginx/app-juli.com.conf`](nginx/app-juli.com.conf) and
  [`nginx/api.app-juli.com.conf`](nginx/api.app-juli.com.conf) into
  `/etc/nginx/sites-available/`
- Enables both sites under `sites-enabled/`
- Runs `nginx -t` and reloads Nginx

At this stage upstreams (`127.0.0.1:3000`, `127.0.0.1:8000`) may be down — that is
expected until [#257](https://github.com/thienphung00/Juli-AI/issues/257) /
[#258](https://github.com/thienphung00/Juli-AI/issues/258) deploy the apps.

---

## Step 4 — HTTPS certificates (Certbot / HITL)

**Requires Step 1 DNS to resolve to the VPS.**

```bash
# Frontend domain (includes www for ACME redirect compatibility)
sudo certbot --nginx -d app-juli.com -d www.app-juli.com

# Backend API domain
sudo certbot --nginx -d api.app-juli.com
```

Certbot installs certificates at the paths referenced in the Nginx configs and configures
HTTP→HTTPS redirects. Confirm auto-renewal:

```bash
sudo certbot renew --dry-run
```

The `certbot` package installs a systemd timer for renewal — no extra cron required.

---

## Step 5 — Validate DNS + TLS (#256 acceptance)

Run the **DNS/TLS-only** smoke subset (no upstream apps required):

```bash
./infra/deploy/smoke-test.sh --dns-tls-only
```

Expected: DNS resolves for both domains and TLS handshakes succeed. Frontend `/health`
checks are intentionally skipped until apps are deployed.

Manual spot-check:

```bash
curl -sI "https://app-juli.com/" | head -1    # 502/503 OK until juli-web is up
curl -sI "https://api.app-juli.com/health" | head -1
```

A **502 Bad Gateway** from Nginx means TLS routing works but the upstream is not running
yet — acceptable for #256.

---

## Step 6 — HITL sign-off checklist

- [x] `app-juli.com` A record → review VPS
- [x] `api.app-juli.com` A record → review VPS
- [x] Nginx routes frontend → `127.0.0.1:3000` and API → `127.0.0.1:8000` separately
- [x] HTTPS certificates issued for both domains
- [x] `certbot renew --dry-run` succeeds (automatic renewal enabled)
- [x] Frontend accessible over HTTPS
- [x] Backend `/health` accessible over HTTPS
- [x] No Redis, webhook, or HA tuning in Nginx config
- [x] Single-process deployment (appropriate for App Review MVP)
- [x] `./infra/deploy/smoke-test.sh --dns-tls-only` passes (or full smoke after app deploy)
- [x] Phone OTP disabled — reviewers use UI-only login (`PHONE_OTP_ENABLED=false`, `NEXT_PUBLIC_UI_ONLY=1`)

Document provider-specific DNS steps and any non-git secrets in your ops notes — **not**
in this repository.

---

## What comes next

| Issue | Work |
|-------|------|
| [#257](https://github.com/thienphung00/Juli-AI/issues/257) | Deploy Next.js frontend (`juli-web`) |
| [#258](https://github.com/thienphung00/Juli-AI/issues/258) | Deploy FastAPI backend (`juli-api`) |
| [#259](https://github.com/thienphung00/Juli-AI/issues/259) | TikTok OAuth callback handler |
| [#260](https://github.com/thienphung00/Juli-AI/issues/260) | Reviewer login path |
| [#254](https://github.com/thienphung00/Juli-AI/issues/254) | End-to-end App Review verification |

Full deploy steps (systemd units, env files, independent restarts):
[`app-review-runbook.md`](app-review-runbook.md).
