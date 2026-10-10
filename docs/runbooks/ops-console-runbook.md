# Ops console runbook — Juli Ops on ops.app-juli.com (fast track P16)

> **Decisions:** `fasttrack/DECISIONS.md` D25 (1–15) · **Contract:** `fasttrack/contracts/p16-ops.md`
> **Prerequisite:** the VPS from [`vps-wiring-runbook.md`](vps-wiring-runbook.md) (nginx, certbot,
> the Cloudflare origin lockdown timer) and the demo lane deployed with a P16 commit.

Juli Ops is the team's internal console. It is built into the demo app (route group
`/ops`) and served on its own hostname behind **two gates**: Cloudflare Access (Google,
`@app-juli.com` only) and an active `ops_staff` row. The API checks both on every
`/v1/ops/*` call and **fails closed** — until steps 4–5 are done every ops request is a
403, which is the safe state to deploy in.

Everything below is an owner step. No agent changes DNS, Cloudflare or the VPS.

---

## 1. Database (deploy)

Migration `083_ops_console` ships with the release (expand-only: role `juli_ops`, five
`ops_*` tables, `users.staff_access_consent_at`, three SECURITY DEFINER functions). The
normal tagged deploy applies it. Check afterwards (owner connection):

```sql
SELECT version_num FROM alembic_version;                      -- 083_ops_console (or later)
SELECT rolname FROM pg_roles WHERE rolname = 'juli_ops';       -- 1 row
SELECT r.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid
  JOIN pg_roles r ON r.oid = m.member WHERE g.rolname = 'juli_ops';  -- the runtime login role
```

If the last query returns nothing (the runtime login was granted `juli_app` after the
migration ran), grant it once: `GRANT juli_ops TO <runtime login role>;`.

## 2. Cloudflare DNS

Cloudflare dashboard → `app-juli.com` → DNS → Add record:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| A | `ops` | the VPS IPv4 (same as `demo`) | **Proxied** (orange cloud) |

It MUST be proxied: the origin accepts Cloudflare's ranges only
(`juli-cloudflare-ip-refresh.timer` → `infra/scripts/cloudflare-origin-lockdown.sh`), so a
grey-cloud record can neither be reached nor pass the certbot HTTP-01 challenge. No change
to the lockdown script is needed — it is host-independent; confirm it is active:

```bash
sudo systemctl is-enabled juli-cloudflare-ip-refresh.timer   # enabled
sudo iptables -S CLOUDFLARE_INGRESS | head                    # Cloudflare ranges on 80/443
```

## 3. Certificate (expand the demo certificate)

```bash
sudo certbot certonly --nginx --cert-name demo.app-juli.com \
  -d demo.app-juli.com -d ops.app-juli.com --expand
sudo openssl x509 -noout -ext subjectAltName \
  -in /etc/letsencrypt/live/demo.app-juli.com/fullchain.pem    # lists ops.app-juli.com
```

Do this BEFORE step 4's vhost install: nginx refuses every site if a vhost names a
certificate that does not cover it.

## 4. nginx vhost

```bash
cd ~/Juli-AI-v2 && git fetch && git checkout <deployed sha>
sudo INSTALL_OPS_VHOST=1 ./infra/scripts/provision-nginx.sh
curl -sI https://ops.app-juli.com/ops | head -3     # 302 to Cloudflare Access (after step 5)
```

`infra/nginx/ops.app-juli.com.conf` proxies `/v1/ops/` to the API, 404s every other
`/v1/` path, serves the Next.js app for the rest (`juli_demo`, the same process as
demo.app-juli.com), and adds `X-Robots-Tag: noindex`. The app's middleware serves only
`/ops/*` on this host and 404s `/ops` on demo.app-juli.com.

## 5. Cloudflare Zero Trust Access

Zero Trust → Settings → Authentication → add **Google** as a login method (if not yet).

Zero Trust → Access → Applications → **Add an application → Self-hosted**:

| Field | Value |
|---|---|
| Application name | Juli Ops |
| Session duration | 24 hours |
| Application domain | `ops.app-juli.com` (path empty = whole host) |
| Identity providers | Google only; enable "Instant Auth" |
| Policy | **Allow** — Include: *Emails ending in* `@app-juli.com` |

Save, then open the application → **Overview → Application Audience (AUD) Tag** and copy
it. The team domain is under Settings → Custom pages (`<team>.cloudflareaccess.com`).

## 6. API environment

Add to `/etc/juli/api.env` (template: `infra/scripts/env/api.env.example`), then restart
the API lane (or deploy):

```bash
CF_ACCESS_TEAM_DOMAIN=<team>                 # or <team>.cloudflareaccess.com
CF_ACCESS_AUD=<the AUD tag from step 5>
OPS_ALLOWED_EMAIL_DOMAIN=app-juli.com
# Invites / disconnect e-mails (optional; without SMTP Ops shows the link to forward):
OPS_SMTP_HOST=...  OPS_SMTP_PORT=587  OPS_SMTP_USER=...  OPS_SMTP_PASSWORD=...
OPS_MAIL_FROM=Juli <no-reply@app-juli.com>
OPS_INVITE_ACCEPT_BASE_URL=https://demo.app-juli.com
# Shared with P15: the monthly OpenAI cap when a shop has none set (default 5):
OPENAI_MONTHLY_CAP_USD_DEFAULT=5
```

Never set `OPS_CF_ACCESS_BYPASS` on the VPS (it is refused when `ENVIRONMENT=production`).

## 7. Supabase redirect URL

Supabase → Authentication → URL Configuration → **Redirect URLs** → add
`https://ops.app-juli.com/ops/dang-nhap` (the ops host signs in with Google on its own
origin; its session is separate from demo.app-juli.com's).

## 8. Seed the first Admin

The first Admin is seeded by e-mail; the row binds to the Supabase user on first sign-in.
Owner connection (or the SQL editor), as the table owner:

```sql
INSERT INTO public.ops_staff (id, email, role, active)
VALUES (gen_random_uuid(), 'thien.phung@app-juli.com', 'admin', true)
ON CONFLICT (email) DO UPDATE SET role = 'admin', active = true;
```

Every further staff member is added by an Admin in Ops → Nhân viên (audited).

## 9. Smoke

1. Private window → `https://ops.app-juli.com` → Cloudflare Access → Google
   (`@app-juli.com`) → Juli Ops → "Đăng nhập với Google" → Tổng quan lists the shops.
2. A non-`@app-juli.com` Google account is stopped by Access.
3. `curl -s -o /dev/null -w '%{http_code}' https://api.app-juli.com/v1/ops/me` → `401`/`403`
   (no Supabase token / no Access assertion).
4. `https://demo.app-juli.com/ops` → 404.
5. Ops → a shop → Xem như shop → the banner reads "chỉ xem, không ghi được"; no button acts.

## Rollback

Remove the vhost (`sudo rm /etc/nginx/sites-enabled/ops.app-juli.com.conf && sudo nginx -t &&
sudo systemctl reload nginx`) and disable the Access application. The migration is
additive; `alembic downgrade 081_order_cost_data` drops the ops tables (the `juli_ops` role
stays, like `juli_app`), but only after the deferred phone cleanup's parent is considered.

## Notes

- **Deploy workflow:** no change needed — the demo artifact is host-independent (relative
  `/v1/` URLs, no host baked in); the ops pages ship in the same artifact. The deploy's
  public check still targets demo.app-juli.com.
- **Huỷ kết nối** (Admin): TikTok Shop has no token-revoke API; Juli overwrites its stored
  tokens, marks the credential `needs_reauth`, pauses the shop, cancels pending runs and
  e-mails the seller. The seller can additionally remove the app in Seller Center.
