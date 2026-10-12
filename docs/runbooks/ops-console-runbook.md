# Ops console runbook — Juli Ops on ops.app-juli.com (fast track P16)

> **Decisions:** `fasttrack/DECISIONS.md` D25 (1–15), D27, D28 · **Contract:** `fasttrack/contracts/p16-ops.md`
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

You no longer have to remember this: the deploy refuses a release while the grant is
missing and prints the exact statement, and the API answers every Ops request with
**503** `Thiếu quyền juli_ops cho database — chạy GRANT juli_ops TO <role>.` instead of a
500 — see [Kiểm tra khi deploy](#kiểm-tra-khi-deploy).

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

## 6. API environment — the AWS secret, never api.env

`/etc/juli/api.env` is **generated**: `infra/scripts/fetch-secrets.sh` rewrites it from the
AWS Secrets Manager secret **`juli/api/production`** on every Celery unit start
(`ExecStartPre`) and on `juli-secrets-refresh.timer`. A key hand-added to api.env
disappears on the next regeneration — that is exactly how Ops silently became "Tài khoản
này không có quyền" (403, `ops_cf_access_denied: Cloudflare Access is not configured`)
after a deploy. So every Ops key lives **in the secret**:

| Key | Required | Value |
|---|---|---|
| `CF_ACCESS_TEAM_DOMAIN` | **Yes** (deploy refuses without it) | `<team>` or `<team>.cloudflareaccess.com` (step 5) |
| `CF_ACCESS_AUD` | **Yes** (deploy refuses without it) | the AUD tag from step 5 |
| `OPS_ALLOWED_EMAIL_DOMAIN` | No (default `app-juli.com`) | `app-juli.com` |
| `OPS_SMTP_*`, `OPS_MAIL_FROM` | No (without SMTP Ops shows the link to forward) | see [Gửi email mời](#gửi-email-mời) |
| `OPS_INVITE_ACCEPT_BASE_URL` | No | `https://demo.app-juli.com` |
| `OPENAI_MONTHLY_CAP_USD_DEFAULT` | No (default `5`) | shared with P15: the monthly OpenAI cap when a shop has none set |
| `OPENAI_SYSTEM_CAP_USD_DEFAULT` | No (default `50`) | D28.3: the whole system's monthly OpenAI limit until an Admin saves one in Ops → Chi phí |

`put-secret-value` **replaces the whole JSON** — merge the new keys into the current
value, never send only the new ones. From the admin workstation (values never printed):

```bash
aws secretsmanager get-secret-value --region us-east-2 --secret-id juli/api/production \
  --query SecretString --output text > /tmp/juli-api.json        # chmod 600; delete after
jq --arg team '<team>' --arg aud '<AUD tag>' \
  '. + {CF_ACCESS_TEAM_DOMAIN: $team, CF_ACCESS_AUD: $aud, OPS_ALLOWED_EMAIL_DOMAIN: "app-juli.com"}' \
  /tmp/juli-api.json > /tmp/juli-api.new.json
jq 'keys | length' /tmp/juli-api.json /tmp/juli-api.new.json      # new = old + added keys
aws secretsmanager put-secret-value --region us-east-2 --secret-id juli/api/production \
  --secret-string file:///tmp/juli-api.new.json
rm -f /tmp/juli-api.json /tmp/juli-api.new.json
```

Then on the VPS: `sudo /root/Juli-AI-v2/infra/scripts/fetch-secrets.sh` and re-run the
deploy (or `sudo systemctl restart juli-api` for the durable unit). Check only key
NAMES, never values: `sudo grep -oE '^(CF_ACCESS|OPS)_[A-Z_]+=' /etc/juli/api.env`.

Never set `OPS_CF_ACCESS_BYPASS` in the secret (it is refused when `ENVIRONMENT=production`).

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

## Gửi email mời

"Mời seller" and "Huỷ kết nối" send e-mail through SMTP (`services/ops/mailer.py`:
STARTTLS, then login). With `OPS_SMTP_HOST` unset nothing is sent and Ops shows the
accept link for staff to forward. Google Workspace, all keys in the secret
`juli/api/production` (section 6):

| Key | Value |
|---|---|
| `OPS_SMTP_HOST` | `smtp.gmail.com` |
| `OPS_SMTP_PORT` | `587` |
| `OPS_SMTP_USER` | the Workspace mailbox that signs in (see below) |
| `OPS_SMTP_PASSWORD` | a Google Workspace **app password** for that mailbox (Google Account → Security → 2-Step Verification → App passwords). Put it straight into the secret — **never paste it in chat**, a ticket or a commit. |
| `OPS_MAIL_FROM` | `Juli <lienhe@app-juli.com>` — this is also the code default, so the key can be left out |

- If `lienhe@app-juli.com` is an **alias or a group**, not a mailbox, it cannot sign in:
  set `OPS_SMTP_USER` to a real mailbox (e.g. `thien.phung@app-juli.com`) and, in that
  mailbox's Gmail → Settings → Accounts → **"Send mail as"**, add and verify
  `lienhe@app-juli.com`. Without that, Gmail rewrites the From to the mailbox address.
- **Quote `OPS_MAIL_FROM` if you set it.** fetch-secrets.sh writes `KEY=value` verbatim and
  the deploy reads api.env with bash `source`, where an unquoted `Juli <lienhe@…>` is a
  syntax error (the `<` is a redirect) and the deploy stops. Store the value WITH the
  double quotes — JSON `"OPS_MAIL_FROM": "\"Juli <lienhe@app-juli.com>\""` — which both
  bash and systemd read as `Juli <lienhe@app-juli.com>`. Or simply leave the key out.
- Test: Ops → a shop → Mời seller to your own address; failures log
  `ops_invite_mail_failed` (`sudo journalctl -u 'juli-api*' --since '10 min ago' | grep ops_invite_mail`).

## Kiểm tra khi deploy

Two checks in `infra/scripts/deploy.sh` (API lane, `deploy_lane_api`), both run before
the new API candidate starts; either one fails the lane, so traffic stays on the running
release and the release record shows `ops_preflight` = the reason:

1. **Cloudflare Access config** (`require_cf_access_env`), right after api.env is read and
   before any migration. Fails when `CF_ACCESS_TEAM_DOMAIN` or `CF_ACCESS_AUD` is absent,
   empty or still the `REPLACE_*` placeholder; prints only the key name(s):

   ```
   FAIL: /etc/juli/api.env has no usable CF_ACCESS_AUD — Juli Ops would refuse every request (403 "Cloudflare Access is not configured"). Fix: add CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD to the AWS secret juli/api/production (api.env is regenerated from it; never hand-edit api.env), run fetch-secrets.sh, then re-run the deploy.
   ```

   Fix: section 6 (the secret), then re-run the deploy.
2. **`juli_ops` membership** (`require_ops_role_grant` →
   `safe_alembic_helpers.py verify-ops-role-grant`), right after migrations (they create the
   role). Connects as the RUNTIME role (`DATABASE_URL`, not the migration owner) and asks
   `pg_has_role(current_user, 'juli_ops', 'MEMBER')`. On failure the last line is the
   exact statement to run as the owner:

   ```
   FAIL: juli_ops grant check refused the release
   the runtime database role 'juli_app' (the user in DATABASE_URL) is not a member of juli_ops, so Juli Ops would answer 503 on every request. Run once as the database owner, then re-run the deploy:
   GRANT juli_ops TO juli_app;
   ```

   Migrations have already been applied at that point (additive, never reverted) — run the
   GRANT and re-run the deploy.

If the grant goes missing later anyway, every `/v1/ops/*` request answers **503**
`{"detail": "Thiếu quyền juli_ops cho database — chạy GRANT juli_ops TO <role>."}` and the
API logs `ops_role_missing` (once per request).

## Chi phí và Thời hạn (D28)

Migration `086_ops_cost_and_terms` ships with the release (expand-only: two tables, one
SECURITY DEFINER function). Check: `SELECT version_num FROM alembic_version;` →
`086_ops_cost_and_terms` (or later).

- **Chi phí** — the system OpenAI limit (default $50 / month, Admin "Sửa giới hạn") and each
  shop's own cap ("Sửa", "· riêng" when not the $5 default). At 80 % every Ops page shows an
  amber banner and the hourly beat task `juli_backend.ops_openai_system_alert` e-mails the
  active Admins once that month (needs the SMTP keys below; without them it logs
  `openai_system_alert_unsent` and retries hourly). At 100 % Juli makes no new OpenAI call for
  any shop (drafting, content analysis, agent runs) until the next month (UTC+7) or a higher
  limit; cards are still created.
- **Thời hạn** — Admin "Gói 30 ngày" / "Gói 365 ngày" with the contract number (unique; the
  same number twice adds nothing). A shop with no period is not restricted. 7 days after
  expiry the shop becomes **chỉ xem**: no new cards, runs, drafting or analysis (seller
  actions answer 403 with the contact address); data sync continues, so a new period
  resumes everything at once.

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
