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

On the VPS, install the units and enable **both** the timer and the service:

```bash
sudo systemctl enable --now juli-cloudflare-ip-refresh.timer    # hourly range refresh
sudo systemctl enable juli-cloudflare-ip-refresh.service        # runs at every boot
```

Enabling the **service** is what gives reboot persistence — see below. Enabling only the
timer was the #941 defect. Verify both:

```bash
sudo systemctl is-enabled juli-cloudflare-ip-refresh.timer      # -> enabled
sudo systemctl is-enabled juli-cloudflare-ip-refresh.service    # -> enabled
sudo journalctl -u juli-cloudflare-ip-refresh.service --no-pager | tail
# Look for "cloudflare-origin-lockdown complete" in the logs.
```

**Reboot persistence (#941).** iptables rules live only in the running kernel, while ufw
persists `80/tcp ALLOW IN Anywhere` and `443/tcp ALLOW IN Anywhere` across reboots. A reboot
therefore did not merely drop the lockdown — it restored a permissive ruleset and left the
origin fully exposed until the hourly timer next fired, a window of up to ~65 minutes
(`OnCalendar=hourly` + `RandomizedDelaySec=5m`, no `OnBootSec`).

The fix re-runs the lockdown at boot rather than persisting its output. Install the drop-in:

```bash
sudo mkdir -p /etc/systemd/system/juli-cloudflare-ip-refresh.service.d
sudo cp infra/systemd/juli-cloudflare-ip-refresh.service.d/10-boot-persistence.conf \
        /etc/systemd/system/juli-cloudflare-ip-refresh.service.d/
sudo systemctl daemon-reload
sudo systemctl enable juli-cloudflare-ip-refresh.service
```

It orders the unit `After=ufw.service` (so ufw's permissive restore cannot clobber it) and
`Before=nginx.service` (so nginx does not begin serving 80/443 until the lockdown is applied).
`OnBootSec=2min` on the timer is the second net, bounding any residual window at ~2 minutes.

**Do not use `iptables-persistent` on this host.** ufw owns the filter table and performs its
own boot-time restore, which would clobber a ruleset replayed by `netfilter-persistent`.
Re-running the lockdown after ufw is the ordering-correct fix and needs no extra package.

Verify after any reboot:

```bash
sudo iptables -S CLOUDFLARE_INGRESS | wc -l      # non-zero
curl -sS --max-time 5 -o /dev/null -w '%{http_code}\n' http://<origin-ip>/   # expect failure
```

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

**IPv6 `--reject-with tcp-reset` support — pre-flight check:** Some older Ubuntu versions do
not support `--reject-with tcp-reset` for ip6tables; they require `icmp6-adm-prohibited` instead.
If unsupported, the IPv6 REJECT rules fail and the script rolls back, leaving the origin
unprotected. Run this check BEFORE first deployment to detect incompatibility:

```bash
sudo ip6tables -t filter -A TEST_PROBE -p tcp --dport 9999 -j REJECT --reject-with tcp-reset 2>&1
sudo ip6tables -t filter -D TEST_PROBE -p tcp --dport 9999 -j REJECT --reject-with tcp-reset 2>/dev/null
# If the first command fails with "unknown --reject-with type", either:
# 1. Set REJECT_WITH=icmp6-adm-prohibited and re-run the script, or
# 2. Accept IPv4-only lockdown (HTTP/HTTPS cannot reach IPv6 clients on that host)
```

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

## Step 7 — Log retention: journald + Nginx (#906, parent #889 / ADR-061)

**Why this exists.** Neither retention policy was ever recorded anywhere: journald has no
`SystemMaxUse`/`MaxRetentionSec`/`SystemKeepFree` set (pure distro defaults), and
`/etc/logrotate.d/nginx` is the distro-shipped file (`daily`/`rotate 14`, no size bound),
not tracked in this repo. Both are now version-controlled so a distro upgrade cannot
silently revert them, and so the retention window is a deliberate choice instead of
whatever the OS happened to ship.

**Retention chosen: 90 days, bounded absolutely by size as well as age.**
The security-events logging floor (#905/ADR-061 §2c — rejected webhook signatures,
credential-stuffing/auth failures, `shop_access_denied`, limiter 429s) exists specifically
for *retrospective* investigation of activity that is deliberately paced to avoid tripping
a live alert. This is a single-founder operation with no on-call rotation and no
observability platform yet (Phase 2.11/DOCP is still at proposal stage), so the realistic
trigger to go look is a lagging symptom — a customer report, a billing anomaly — not a
dashboard page. 90 days is the same floor PCI DSS sets for security-relevant log
retention, and it is chosen to comfortably outlast that lag; a week or two (the prior
distro default) is not. Both streams are kept to the **same** 90-day window on purpose —
journald has "what happened and to whom", the Nginx access log has "from where and how
often" for the public surfaces (webhook, demo, OAuth callback) that sit in front of the
app, and a shorter window on either one caps what can actually be reconstructed.

**Disk assumption (stated, not measured — no VPS access from this change):** a single
low-cost VPS per the standing single-host decision (PRD #889), in the 40-80GB SSD class
typical of a $12-24/mo droplet. `SystemMaxUse=1G` (journald) plus the Nginx logrotate
worst case of roughly 8.1GB (`maxsize 50M`, `rotate 90`, pessimistic 10% compression —
see `infra/logrotate/nginx` for the arithmetic) together stay well under 10% of even the
smaller end of that range. Realistic usage (normal traffic, logs that actually compress
well) is expected to be well under 1GB combined.

| Stream | Where it lives | Retention | Read it during an incident |
|--------|----------------|-----------|------------------------------|
| Application logs (structured JSON: security events, requests, `request_id`) | systemd journal, unit `juli-api` | 90 days, hard-capped at 1G disk (`SystemMaxUse`), 2G always kept free (`SystemKeepFree`) | `sudo journalctl -u juli-api --since "7 days ago" \| grep webhook_signature_rejected` (swap the unit/grep for `juli-web`, `shop_access_denied`, auth failures, etc.) |
| Nginx access log (real client address for the webhook, demo, and OAuth-callback surfaces) | `/var/log/nginx/access.log` (+ rotated `.1` … `.90.gz`) | 90 days, hard-capped by `maxsize 50M` per generation × 90 rotations | `sudo zgrep "POST /webhooks/tiktok" /var/log/nginx/access.log*` (recent, uncompressed `.log`/`.1`; `.2.gz`+ need `zgrep`) |
| Nginx error log | `/var/log/nginx/error.log` (+ rotated) | Same policy as access log (one `logrotate` stanza covers both) | `sudo tail -n 200 /var/log/nginx/error.log` or `sudo zgrep <pattern> /var/log/nginx/error.log*` |

### Install (VPS, HITL)

Tracked source files: [`infra/systemd/journald.conf.d/10-retention.conf`](../../infra/systemd/journald.conf.d/10-retention.conf)
and [`infra/logrotate/nginx`](../../infra/logrotate/nginx) — both carry the full reasoning
in their headers.

```bash
cd ~/Juli-AI-v2

# journald retention drop-in — a drop-in (not editing journald.conf directly) so a
# distro upgrade cannot silently revert it.
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp infra/systemd/journald.conf.d/10-retention.conf \
        /etc/systemd/journald.conf.d/10-retention.conf
sudo systemctl restart systemd-journald

# Nginx log rotation policy — replaces the untracked distro-shipped file.
sudo cp infra/logrotate/nginx /etc/logrotate.d/nginx
```

### Verify (VPS, HITL) — all read-only / dry-run, safe to run any time

```bash
# journald: confirm the drop-in is actually merged into the effective config.
sudo systemd-analyze cat-config systemd/journald.conf
# Expect to see SystemMaxUse=1G / SystemKeepFree=2G / MaxRetentionSec=90day sourced
# from .../journald.conf.d/10-retention.conf in the merged output.

# journald: confirm current usage is tracked and bounded.
sudo journalctl --disk-usage
# Expect a size well under the 1G SystemMaxUse cap during normal operation.

# Nginx: DRY RUN only — `-d` prints what logrotate WOULD do and changes nothing on
# disk. Do not run logrotate without `-d`/`-v` outside of its normal cron/systemd timer
# invocation; a real run rotates files immediately and is not what you want just to
# check the config.
sudo logrotate -d /etc/logrotate.d/nginx
# Expect: "reading config file /etc/logrotate.d/nginx", the parsed pattern line showing
# "after 1 days ... log files >= 52428800 are rotated earlier, (90 rotations)", and no
# "error:" lines. A log "does not need rotating" result is expected and fine — it means
# the dry run parsed cleanly and nothing is currently due.
```

If `systemd-analyze cat-config` or `journalctl --disk-usage` are unavailable (older
systemd), `cat /etc/systemd/journald.conf.d/10-retention.conf` plus
`du -sh /var/log/journal` are an acceptable substitute — confirms the file is installed
and gives a rough usage figure, just not the merged/effective view.

---

## Step 8 — HITL sign-off checklist

- [x] DNS A records point to Cloudflare edge (proxied), not directly to VPS
- [x] Cloudflare dashboard shows all hostnames as proxied (orange cloud)
- [x] Nginx routes frontend → `127.0.0.1:3000` and API → `127.0.0.1:8000` separately
- [x] HTTPS certificates issued for both domains via certbot HTTP-01
- [x] `certbot renew --dry-run` succeeds (automatic renewal enabled)
- [x] Origin lockdown firewall rules installed and enabled (`juli-cloudflare-ip-refresh.timer` running)
- [x] Reboot persistence: `juli-cloudflare-ip-refresh.service` **enabled** with the
      `10-boot-persistence.conf` drop-in (`After=ufw.service`, `Before=nginx.service`) (#941)
- [x] SSH (port 22) remains fully accessible from any source (untouched by lockdown)
- [x] Frontend accessible over HTTPS through Cloudflare proxy
- [x] Backend `/health` accessible over HTTPS through Cloudflare proxy
- [x] Direct connection attempts to VPS IP on ports 80/443 are refused (firewall blocks non-Cloudflare sources)
- [x] No Redis, webhook, or HA tuning in Nginx config
- [x] Single-process deployment (appropriate for App Review MVP)
- [x] `./infra/scripts/smoke-test.sh --dns-tls-only` passes (or full smoke after app deploy)
- [x] Reviewers use UI-only demo login (`NEXT_PUBLIC_UI_ONLY=1`)
- [ ] Journal retention drop-in installed (`journald.conf.d/10-retention.conf`) and
      `systemd-analyze cat-config systemd/journald.conf` shows it merged (#906)
- [ ] Nginx logrotate policy installed (`/etc/logrotate.d/nginx`) and `logrotate -d`
      dry run parses with no `error:` lines (#906)

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
