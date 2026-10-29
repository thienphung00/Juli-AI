# App hostname cutover — app.app-juli.com (fast track P74-B)

Shopee's reviewer read `demo.app-juli.com` / the tab title "Juli Demo" as "not live". The
product now also answers on **`app.app-juli.com`**. `demo.app-juli.com` keeps working,
unchanged (existing sellers, links). Both names are served by the same nginx vhost
(`infra/nginx/demo.app-juli.com.conf`, `server_name demo.app-juli.com app.app-juli.com`) from
the same `juli_demo` upstream, so one release answers both. A later demo -> app redirect is a
separate owner step, not part of this runbook.

Do the steps IN ORDER. Steps 1-3 must be done before the landing site (whose CTAs now point at
`app.app-juli.com`) is deployed, otherwise its buttons hit an unresolved host.

## 1. Cloudflare DNS

Cloudflare -> `app-juli.com` -> DNS -> Add record:

| Type | Name | Content | Proxy status |
|---|---|---|---|
| A | `app` | the VPS IPv4 (same as `demo`) | **Proxied** (orange cloud) |

Proxied, like `ops`: the origin accepts Cloudflare ranges only
(`cloudflare-origin-lockdown.sh`), so a grey-cloud record can neither be reached nor pass the
certbot HTTP-01 challenge. Confirm the existing `demo` record is proxied too and match it.

## 2. Certificate: expand the demo certificate lineage

The vhost keeps `ssl_certificate /etc/letsencrypt/live/demo.app-juli.com/...`, so the existing
lineage must cover the new name. Keep every name already on it (ops, if step 3 of the ops
runbook was done):

```bash
sudo openssl x509 -noout -ext subjectAltName \
  -in /etc/letsencrypt/live/demo.app-juli.com/fullchain.pem      # note the current names
sudo certbot certonly --nginx --cert-name demo.app-juli.com \
  -d demo.app-juli.com -d ops.app-juli.com -d app.app-juli.com --expand
sudo openssl x509 -noout -ext subjectAltName \
  -in /etc/letsencrypt/live/demo.app-juli.com/fullchain.pem      # must list app.app-juli.com
```

Do this BEFORE step 3: an nginx vhost for a name the certificate does not cover is served the
wrong certificate (browser error on `app.`) even though `nginx -t` passes.

## 3. Install the vhost

On the VPS, from the checked-out release containing this change:

```bash
sudo ./infra/scripts/provision-nginx.sh      # re-installs demo.app-juli.com.conf, runs nginx -t, reloads
```

(`INSTALL_OPS_VHOST=1` as before if ops is installed.) The upstream indirection (#839) is
untouched: `/etc/nginx/juli/demo-upstream.conf` is not overwritten.

## 4. API env: nothing required

`CORS_ALLOW_ORIGINS` (read by `cors_allow_origins()`, env-only; code default is localhost) is
`https://app-juli.com` on the VPS. The product calls the API through the same-origin `/v1`
proxy on its own host (the browser never calls `api.app-juli.com` cross-origin), so
`app.app-juli.com` needs NO CORS change. Only if a browser-side cross-origin call to
`api.app-juli.com` from the product host is ever added, extend it to
`https://app-juli.com,https://app.app-juli.com` and restart `juli-api`.

Optional: `OPS_INVITE_ACCEPT_BASE_URL=https://app.app-juli.com` in the API env. The code default
(`services/ops/invites.py`) is now `app.app-juli.com`; if the VPS env sets the old demo URL
explicitly, invites keep pointing at demo until you change it.

## 5. Supabase Auth

Supabase -> Authentication -> URL Configuration -> **Redirect URLs**: add
`https://app.app-juli.com/**` (KEEP `https://demo.app-juli.com/**`). Leave Site URL as is.
Google sign-in: the Google Cloud authorized redirect URI is Supabase's own
`https://<project>.supabase.co/auth/v1/callback`, not the app host, so no Google console change;
just test it (step 6). Sessions are per origin (localStorage): a seller signed in on demo must
sign in again on app.

## 6. Verify

```bash
dig +short app.app-juli.com A                                   # Cloudflare IPs (proxied)
curl -sI https://app.app-juli.com/ | head -5                    # 200, x-robots-tag: noindex, nofollow
curl -sI https://app.app-juli.com/decisions | head -1           # 200
curl -sI https://demo.app-juli.com/ | head -1                   # still 200
curl -sI http://app.app-juli.com/ | head -3                     # 301 -> https://app.app-juli.com/
curl --tls-max 1.2 -sI https://app.app-juli.com/ | head -1      # TLS 1.2 handshake works
curl -s -o /dev/null -w "%{http_code}\n" https://app.app-juli.com/v1/shops   # 401, not 404: /v1 proxy reaches the API
```

Browser: open `https://app.app-juli.com/auth/email`, tab title reads "Juli" (after the demo
release containing this slice is deployed), Google sign-in and email OTP both return to
`app.app-juli.com`.

## 7. Shopee submission values (after step 6 passes)

- Test URL: `https://app.app-juli.com/auth/email#doi-tac`
- Reviewer sign-in details unchanged (reviewer account on `/auth/email#doi-tac`).

## Not changed on purpose

- **TikTok OAuth redirect URIs** are on `api.app-juli.com`
  (`TIKTOK_REDIRECT_URI` -> `https://api.app-juli.com/v1/auth/tiktok/callback`,
  `TIKTOK_BUSINESS_REDIRECT_URI`, `TIKTOK_BUSINESS_ACCOUNT_HOLDER_REDIRECT_URI`). They are not
  on the demo host, so the hostname move needs no Partner Center change.
- Post-deploy checks (`deploy.sh` `lane_public_url`, `deploy-demo-release.sh`
  `DEMO_PUBLIC_BASE_URL`, `rollback.yml`) still probe `demo.app-juli.com`: it is the same
  upstream, and adding `app.` to a hard gate before DNS exists would fail deploys. Add `app.`
  after step 6 if wanted.
- Workflow review copy in apps/demo still says "Demo" in places ("Làm mới Demo", "chưa có
  trong Demo"); only the tab title changed.
