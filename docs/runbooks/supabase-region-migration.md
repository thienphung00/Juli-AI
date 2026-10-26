# Supabase region migration: us-west → Singapore (ap-southeast-1)

Status: **PLAN** (2026-10-26). Do not start before Shopee's ISV review is decided.
Owner runs every step that touches the dashboards, credentials or production data.

## Why

The API and Celery run on the Hetzner VPS in **Singapore**; Supabase Postgres is in **us-west**.
Measured 2026-10-26 from the VPS: **197 ms per database round trip**. A signed-in API call makes
many round trips (`/v1/reviewer/me` ≈ 9.5 s, `/v1/demo/decisions` ≈ 24.8 s server-side before
P69). P69 cuts the round trips per call; this migration cuts the cost of each one.

Expected after the move: VPS → Supabase Singapore ≈ 1–3 ms per round trip. Sellers (Vietnam) are
close to both. Cloudflare is anycast and needs no change.

Rejected alternative: moving the VPS to Hetzner Hillsboro (US-west). It shortens VPS↔DB to
≈ 20 ms but puts the Pacific between every Vietnamese browser and the API, and slows TikTok
Shop VN calls from the workers.

## What moves

Supabase cannot change a project's region in place. We create a **new project in Singapore**
and move everything into it:

| Item | How it moves | Notes |
|---|---|---|
| `public`, `silver` and other app schemas, data, sequences | `pg_dump` / `pg_restore` | Alembic head must match (`alembic_version` travels with the data) |
| Custom roles `juli_app`, `juli_ops` and their grants | recreated by hand (roles are cluster-level, not in a schema dump), then grants re-applied | Migration 043 defines `juli_app`'s grant map; 083 creates `juli_ops`. Set new passwords |
| RLS policies, `SECURITY DEFINER` functions (061, 099, 102, …) | come with the schema dump | Function owners must exist before restore |
| `auth.users`, `auth.identities` (incl. password hashes) | data-only dump of the `auth` schema tables, restored into the new project | Keeps user ids and passwords: the Shopee reviewer's password keeps working |
| Auth settings: site URL, redirect URLs, email/SMS providers and templates, rate limits, JWT expiry | copied by hand in the new project's dashboard | Screenshot every page of the old project first |
| JWT signing keys (ES256 / JWKS) | **not** copied: the new project has new keys | Every session is signed out once; users sign in again. The API reads JWKS from `SUPABASE_URL`, so it follows automatically |
| API keys (anon, service role), `SUPABASE_JWT_SECRET` | new values | `/etc/juli/api.env`, Celery env, GitHub repo secrets |
| Pooler (Supavisor) and direct URLs | new hostnames | `DATABASE_URL`, `DATABASE_DIRECT_URL` |
| Pool limits | set again | Session pool was raised from 15 (2026-10-22, EMAXCONNSESSION); set the same or higher |
| Storage, Edge Functions, Realtime, pg_cron | **not used** by Juli (checked 2026-10-26) | Nothing to move |

## Config that changes

- VPS `/etc/juli/api.env` (API + Celery): `DATABASE_URL`, `DATABASE_DIRECT_URL`, `SUPABASE_URL`,
  `SUPABASE_JWT_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, and any
  `SUPABASE_ORIGIN_AUTHORIZE_URL` / `SUPABASE_AUTH_MODULE` value that names the old project.
- GitHub repo secrets read by `fasttrack-deploy.yml` when building demo + landing:
  `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (inlined at build, so a rebuild
  is required; `verify-supabase-env-in-build.mjs` checks them).
- Backup job (`infra/scripts/backup-database.sh`, `juli-db-backup.timer`): uses the env above.
- Anything else that holds the old project ref: grep the VPS for it
  (`grep -rl <old-ref> /etc/juli /root/releases/current/.env* 2>/dev/null`).

## Phase 0 — prepare (no downtime, 1–2 h)

1. Create the new project in **Southeast Asia (Singapore)**, same plan/compute size as today.
   Save its ref, URLs and keys in the password manager, never in chat or git.
2. Copy every auth setting by hand from the old project (Authentication → URL configuration,
   providers, email/SMS templates, rate limits, JWT expiry). Copy the pooler size.
3. From the VPS, measure the new project: `psql "<new direct url>" -c '\timing on' -c 'select 1'`
   → expect < 5 ms. If it is not, stop and find out why before going further.
4. Create the roles on the new project (`CREATE ROLE juli_app LOGIN PASSWORD …`, `juli_ops`, and
   any membership the API needs: `GRANT juli_ops TO <runtime user>`, see `deploy.sh`
   `require_ops_role_grant`).

## Phase 1 — rehearsal (no downtime, 2–3 h)

1. Dump the live database with the **direct** URL (not the pooler), from the VPS:
   - schemas + data of every app schema (`pg_dump -Fc --no-owner --no-privileges`,
     excluding Supabase-managed schemas: `auth`, `storage`, `realtime`, `supabase_*`,
     `extensions`, `graphql*`, `pgsodium*`, `vault`);
   - `auth.users` and `auth.identities` data only (`pg_dump -Fc --data-only -t auth.users -t auth.identities`).
2. Restore into the new project in that order: app schemas → re-apply grants (043 map, 047,
   later migrations' `GRANT … TO juli_app`) → auth data.
3. Check:
   - `alembic current` on the new project = production's head;
   - row counts match for `shops`, `tiktok_credentials`, `silver.orders`, `public.order_items`,
     `shop_diagnosis_reports`, `auth.users` (one query per table on each side);
   - `fasttrack/check.sh`-style isolation tests pass against the new DB as `juli_app`;
   - point a **candidate** API slot at the new project (not live traffic), sign in as a test user
     and as the reviewer, load every tab, time `/v1/reviewer/me`.
4. Throw the rehearsal data away (`drop` + recreate the schemas), keeping roles and settings.
   Write down the dump size and how long dump + restore took: that is the downtime estimate.

## Phase 2 — cutover (downtime ≈ dump + restore time + 15 min)

Pick a low-traffic window (Vietnam night). Tell Fujiwa beforehand. Not during an app review.

1. Freeze writes: stop Celery beat + workers and the webhook receiver path (or the whole API
   with a maintenance response). TikTok retries webhooks, and polling catches up afterwards.
2. Final dump from the old project (same commands as the rehearsal).
3. Restore into the new project; re-apply grants; restore auth data.
4. Re-run the Phase 1 checks (counts, alembic head, isolation).
5. Swap config: `/etc/juli/api.env` → new values; GitHub secrets → new values.
6. Deploy through the normal path (push a `fasttrack-deploy-*` tag) so demo + landing are rebuilt
   with the new public keys and the API/Celery restart on the new env. No migration in this
   deploy, so the backup job is skipped.
7. Start Celery again. Watch the first poll cycle and the first webhooks.

## Phase 3 — verify (30 min)

- From the VPS: `select 1` < 5 ms.
- `http_request.duration_ms` for `/v1/reviewer/me` and `/v1/demo/decisions` (journal) in the
  low hundreds of ms or less.
- Reviewer signs in with the **existing** password; every tab loads; "Đồng bộ ngay" works.
- Fujiwa: poll succeeds, a webhook lands (`etl_event_processed` for `2b1da87b`), no `etl_dlq`.
- Seller sign-in on demo + landing works (users sign in once more, sessions were reset).
- Backup timer runs against the new project; `DUMP_SIZE` line appears.

## Rollback

Keep the old project untouched (paused writes, not deleted) for 14 days.
If Phase 3 fails: restore the old values in `/etc/juli/api.env` and GitHub secrets, redeploy,
start Celery. Writes made on the new project after cutover are lost unless copied back by hand,
so decide within the first hour. Delete the old project only after 14 clean days and a fresh
backup of the new one.

## Risks and open questions

- **Auth data restore:** follow Supabase's current guide for moving `auth` data between projects
  at the time of the migration; the auth schema is managed and its shape can change between
  versions. If the guide says otherwise than this plan, the guide wins.
- **Sessions reset:** everyone signs in again once (new signing keys). Do it outside a review.
- **Shopee/TikTok reviewers:** the reviewer account keeps its id and password; check it in
  Phase 3 before announcing anything.
- **TikTok tokens** move with `tiktok_credentials`; no re-authorisation expected.
- **Egress:** two full dumps (rehearsal + cutover) from us-west count toward Supabase egress.
- Ask Supabase support whether "restore backup to a new project" can target another region for
  this plan; if yes, it can replace the manual dump/restore of app data (auth still needs checking).
