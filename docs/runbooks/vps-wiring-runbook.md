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
| Repo checkout | `~/Juli-AI-v2` (single monorepo — backend at repo root, frontend in `apps/dashboard/`) |
| Firewall | Inbound **80/tcp** and **443/tcp** open to the VPS |

Record the VPS public IP as `VPS_IP` for the steps below. **Do not commit** the IP or
any credentials to git.

---

## Step 1 — DNS A records and Cloudflare proxy (registrar + Cloudflare dashboard / HITL)

**Cloudflare-proxied topology:** DNS A records point to Cloudflare edge IPs, not the VPS directly.
Cloudflare's edge proxy (orange-cloud in the dashboard) terminates TLS at the edge, then
proxies clean HTTP to the origin VPS. This provides WAF, DDoS protection, and rate limiting.
Direct connections to the VPS IP bypass Cloudflare entirely — they are blocked by the
origin-lockdown firewall rules (applied in Step 5 below) to force all traffic through Cloudflare.

In your Cloudflare dashboard:

| Hostname | Type | Value | Proxy Status | TTL |
|----------|------|-------|--------------|-----|
| `app-juli.com` | A | Cloudflare edge IP (auto) | Proxied (orange cloud) | Auto |
| `www.app-juli.com` | A | Cloudflare edge IP (auto) | Proxied (orange cloud) | Auto (optional; certbot may request it) |
| `api.app-juli.com` | A | Cloudflare edge IP (auto) | Proxied (orange cloud) | Auto |

Cloudflare will provide the origin IP to proxy to — you configure it as the origin server
in the Cloudflare dashboard under DNS settings. Let's Encrypt (certbot) reaches the origin
**through** Cloudflare on port 80 (HTTP-01 ACME challenge), not directly.

Confirm propagation from your workstation (you will see Cloudflare edge IPs, not `VPS_IP`):

```bash
dig +short app-juli.com A
dig +short api.app-juli.com A
# Both must return Cloudflare edge IPs (104.21.x.x, 172.67.x.x range) before continuing.
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
cd ~/Juli-AI-v2
sudo ./infra/scripts/provision-nginx.sh
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

## Step 5 — Origin lockdown: restrict inbound 80/443 to Cloudflare ranges only

**Why:** Direct connections to the VPS IP bypass Cloudflare entirely (no WAF, no rate limiting,
no DDoS protection). Restricting 80/443 at the firewall to Cloudflare's published IP ranges
closes this bypass. Requests must flow through Cloudflare edge → origin.

**How certbot HTTP-01 still works:** Let's Encrypt reaches the origin **through** Cloudflare's
proxy on port 80, so renewal continues to succeed. If a hostname is ever grey-clouded
(unproxied) or a new DNS record is added without Cloudflare proxy, renewal will silently
fail — monitor `certbot renew --dry-run` output in your deploy logs.

On the VPS, install and enable the automatic refresh:

```bash
sudo systemctl enable --now juli-cloudflare-ip-refresh.timer
```

The timer runs hourly to refresh firewall rules from Cloudflare's current IP ranges. Check
that the service is enabled and has run successfully:

```bash
sudo systemctl status juli-cloudflare-ip-refresh.timer
sudo journalctl -u juli-cloudflare-ip-refresh.service --no-pager
# Look for "cloudflare-origin-lockdown complete" in the logs.
```

**Reboot persistence — important:** iptables rules do NOT survive a reboot. Between boot and
the first timer firing (~1 hour), the origin is exposed without protection. Choose one approach:

1. **Boot-time activation** — add a second systemd service for immediate protection on boot:
   ```bash
   sudo systemctl enable --now juli-cloudflare-ip-refresh.service  # run once at boot
   # Create /etc/systemd/system/juli-cloudflare-ip-refresh-boot.service with
   # Before=multi-user.target to activate before multi-user services start
   ```

2. **Persist rules** — install `iptables-persistent` to restore rules after reboot:
   ```bash
   sudo apt-get install -y iptables-persistent
   # After this script runs successfully, persist the rules:
   sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null
   sudo ip6tables-save | sudo tee /etc/iptables/rules.v6 > /dev/null
   ```

This implementation documents the gap explicitly rather than hiding it. The systemd timer is
configured with `Persistent=true`, but acknowledge the reboot window in your runbook and ops docs.

**Failed rule application behavior — availability over lockout:** If the script fails while
applying rules (e.g., Cloudflare ranges unreachable, iptables permission issue), it rolls back
immediately:
- Flushes the firewall chain (removes all rules added so far)
- Removes the INPUT jump rule
- **Result: the origin becomes OPEN and unprotected until the next timer run**

This is the correct fail-safe choice — better exposed than locked out — but it is a real tradeoff:
a transient fetch or permission failure silently drops protection for ~1 hour until the next
hourly timer run. **Monitor script exit status** in journalctl logs:
```bash
sudo journalctl -u juli-cloudflare-ip-refresh.service --no-pager | tail -20
# Look for "cloudflare-origin-lockdown complete" (success) or "FAIL:" (rollback)
```
Alert on repeated failures; they indicate the lockdown was unable to apply.

### Verify the lockdown is working

The rules refuse direct connections (non-Cloudflare source) on ports 80/443, but allow
Cloudflare-proxied traffic:

```bash
# From the VPS itself, confirm SSH (port 22) is still reachable and unchanged:
ssh -v localhost
# Should connect without asking for credentials (or prompt if key auth required).

# Confirm that the lockdown rules are in place (check iptables):
sudo iptables -t filter -L CLOUDFLARE_INGRESS -n
# Should show rules accepting only Cloudflare CIDR ranges on ports 80 and 443.
```

---

## Step 6 — Validate DNS + TLS (#256 acceptance)

Run the **DNS/TLS-only** smoke subset (no upstream apps required) from the repo root:

```bash
cd ~/Juli-AI-v2
./infra/scripts/smoke-test.sh --dns-tls-only
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

### Public OAuth callback paths (API vhost)

Nginx for `api.app-juli.com` proxies `/v1/*` to `juli-api`. After the backend is
deployed, these production HTTPS callbacks must be reachable and must **not 5xx**
on missing OAuth query params (full smoke covers this — see
[`smoke-checklist-runbook.md`](smoke-checklist-runbook.md)):

| Kind | Production URL (exact) |
|------|------------------------|
| Shop Partner | `https://api.app-juli.com/v1/auth/tiktok/callback` |
| Business Advertiser | `https://api.app-juli.com/v1/auth/tiktok/business/callback` |
| Business account holder | `https://api.app-juli.com/v1/auth/tiktok/business/account-holder/callback` |

> **High-risk:** renaming a registered TikTok portal redirect URI breaks in-flight
> authorizations. Do not change these paths without a coordinated portal + secrets
> update (ADR-034).

Spot-check (expect non-5xx once `juli-api` is up; 502 is OK during #256-only wiring):

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://api.app-juli.com/v1/auth/tiktok/business/callback"
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://api.app-juli.com/v1/auth/tiktok/business/account-holder/callback"
```

---

## Step 7 — HITL sign-off checklist

- [x] DNS A records point to Cloudflare edge (proxied), not directly to VPS
- [x] Cloudflare dashboard shows all hostnames as proxied (orange cloud)
- [x] Nginx routes frontend → `127.0.0.1:3000` and API → `127.0.0.1:8000` separately
- [x] HTTPS certificates issued for both domains via certbot HTTP-01
- [x] `certbot renew --dry-run` succeeds (automatic renewal enabled)
- [x] Origin lockdown firewall rules installed and enabled (`juli-cloudflare-ip-refresh.timer` running)
- [x] SSH (port 22) remains fully accessible from any source (untouched by lockdown)
- [x] Frontend accessible over HTTPS through Cloudflare proxy
- [x] Backend `/health` accessible over HTTPS through Cloudflare proxy
- [x] Direct connection attempts to VPS IP on ports 80/443 are refused (firewall blocks non-Cloudflare sources)
- [x] No Redis, webhook, or HA tuning in Nginx config
- [x] Single-process deployment (appropriate for App Review MVP)
- [x] `./infra/scripts/smoke-test.sh --dns-tls-only` passes (or full smoke after app deploy)
- [x] Reviewers use UI-only demo login (`NEXT_PUBLIC_UI_ONLY=1`)

Document provider-specific DNS steps and any non-git secrets in your ops notes — **not**
in this repository.

---

## What comes next

| Issue | Work |
|-------|------|
| [#257](https://github.com/thienphung00/Juli-AI/issues/257) | Deploy Next.js frontend (`juli-web`) |
| [#258](https://github.com/thienphung00/Juli-AI/issues/258) | Deploy FastAPI backend (`juli-api`) |
| [#259](https://github.com/thienphung00/Juli-AI/issues/259) | TikTok OAuth callback handler |
| [#260](https://github.com/thienphung00/Juli-AI/issues/260) | Reviewer login path — [`reviewer-login-runbook.md`](reviewer-login-runbook.md) |
| [#254](https://github.com/thienphung00/Juli-AI/issues/254) | End-to-end App Review verification |

Full deploy steps (systemd units, env files, independent restarts):
[`app-review-runbook.md`](app-review-runbook.md).
