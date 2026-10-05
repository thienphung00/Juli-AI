# Backend deploy runbook — App Review (#258)

> **Parent:** [#249](https://github.com/thienphung00/Juli-AI/issues/249) · **Issue:** [#258](https://github.com/thienphung00/Juli-AI/issues/258)  
> **Prerequisite:** [#256](https://github.com/thienphung00/Juli-AI/issues/256) — DNS, Nginx, and HTTPS wired  
> **Next:** [#259](https://github.com/thienphung00/Juli-AI/issues/259) (OAuth callback) → [#254](https://github.com/thienphung00/Juli-AI/issues/254) (E2E)

Deploy the existing FastAPI app behind `https://api.app-juli.com/` for TikTok App
Review. This slice serves only the endpoints required for review: `/health`, auth
surface, and (after #259) the TikTok OAuth callback.

> **Update (#381):** `POST /webhooks/tiktok` is now also served by this same
> `juli-api` process (see `backend/src/juli_backend/api/routes/webhook_tiktok.py`).
> No new systemd unit or Nginx location is required — the existing catch-all
> `location /` in `infra/nginx/api.app-juli.com.conf` already proxies it to
> `127.0.0.1:8000`. Partner Center webhook deliveries need `TIKTOK_APP_KEY` /
> `TIKTOK_APP_SECRET` set (already required for OAuth, below); no other new
> service is deployed for webhooks.

---

## Topology

```
https://api.app-juli.com  →  Nginx  →  juli-api (127.0.0.1:8000)  →  FastAPI (uvicorn)
```

| Item | Value |
|------|-------|
| Service | `juli-api` (systemd) |
| Upstream | `127.0.0.1:8000` |
| Env file | `~/Juli-AI-v2/.env` (from `infra/scripts/env/api.env.example`) |
| ASGI entry | `backend.api.api.main:app` |
| Provision script | `sudo ./infra/scripts/provision-backend.sh` |

---

## Required env vars (startup only)

The API opens the database engine at startup via FastAPI lifespan. Set these on the
VPS only — never commit real values.

| Var | Required | Notes |
|-----|----------|-------|
| `DATABASE_URL` | Yes | Supabase Postgres for review |
| `CORS_ALLOW_ORIGINS` | Yes | `https://app-juli.com` |
| `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` | OAuth (#259) | Partner Center review app |
| `TIKTOK_TOKEN_ENCRYPTION_KEY` | OAuth persistence (#259) | Dedicated secret for encrypted token storage |
| `SUPABASE_JWT_SECRET` | Yes | Required at startup — the API refuses to boot-serve authenticated routes without it; there is no UI-only demo login fallback |

See [`env/api.env.example`](env/api.env.example). App Review **does not** require
`REDIS_URL`, cron, workers, ML batch jobs, polling, or a *separate* webhook
service — TikTok webhook ingress (#381) is a route on this same `juli-api`
process, not an additional deploy target. If startup forces one of the former,
stop and split the dependency into a new issue.

---

## Alembic migrations

**Skip** full Alembic migrations for App Review unless a route needs persisted data.

`/health` only needs DB connectivity. **TikTok OAuth callback persistence** and
`GET /debug/tiktok/verify-connection` require the base identity tables from
revision `001`:

```bash
cd ~/Juli-AI-v2
.venv/bin/alembic upgrade 001
sudo systemctl restart juli-api
```

Without `users` / `shops` / `tiktok_credentials`, verify-connection returns
`503` JSON (not plain-text 500) after the hardened handler is deployed.

---

## One-time deploy (VPS)

Run on the review VPS after [#256](vps-wiring-runbook.md) sign-off:

```bash
cd ~/Juli-AI-v2
git pull

# 1. Backend env (placeholders only in git — real file stays on VPS)
cp -n infra/scripts/env/api.env.example .env
grep DATABASE_URL= .env
grep CORS_ALLOW_ORIGINS=https://app-juli.com .env

# 2. Install systemd unit, venv deps, and start juli-api
chmod +x infra/scripts/provision-backend.sh
sudo ./infra/scripts/provision-backend.sh

# 3. Verify backend health over public HTTPS
curl -sS https://api.app-juli.com/health
APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
```

`provision-backend.sh` copies `juli-api.service`, ensures `.env` exists from the
template, runs `pip install -r requirements.txt` in `.venv`, and enables the service
on `127.0.0.1:8000` with a **single uvicorn worker**.

---

## Redeploy (code or env change)

```bash
cd ~/Juli-AI-v2
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart juli-api
sudo systemctl status juli-api --no-pager
```

Backend redeploy is **independent** of the frontend — restarting `juli-api` does not
restart `juli-web` and vice versa.

Manual equivalent:

```bash
cd ~/Juli-AI-v2
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp infra/systemd/juli-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart juli-api
```

---

## Sign-off checklist

- [ ] `.env` sets `DATABASE_URL` and `CORS_ALLOW_ORIGINS=https://app-juli.com`
- [ ] `juli-api` is active (`systemctl is-active juli-api`)
- [ ] `curl -sS http://127.0.0.1:8000/health` returns JSON with `"status":"ok"`
- [ ] `https://api.app-juli.com/health` returns 2xx JSON over HTTPS
- [ ] `./infra/scripts/smoke-test.sh` passes backend `/health` check
- [ ] Redis, cron, workers, ML jobs, polling, and a separate webhook service **not** started (webhook ingress runs as a route on `juli-api`, see #381)
- [ ] Alembic migrations **not** run unless OAuth/login persistence requires schema

---

## Troubleshooting

### 502 from Nginx

`juli-api` is down or not listening on `127.0.0.1:8000`:

```bash
sudo systemctl status juli-api --no-pager
sudo journalctl -u juli-api -n 50 --no-pager
```

### Startup fails on DATABASE_URL / Alembic "Connection refused"

Supabase **direct** hosts (`db.<project-ref>.supabase.co`) are **IPv6-only**.
Most VPS hosts are IPv4-only — `getent ahostsv4 db....supabase.co` returns
nothing, and connections to `2600:...` fail with `Connection refused`.

**Fix:** set `DATABASE_URL` in `.env` to the **Session pooler** URI (IPv4):

1. Supabase Dashboard → **Connect** → **Session mode** (port `5432`)
2. Copy the URI — host looks like `aws-0-<region>.pooler.supabase.com`
3. User is `postgres.<project-ref>` (not plain `postgres`)

```bash
# Confirm direct host has no IPv4 (expected on free/paid without IPv4 add-on)
getent ahostsv4 db.YOUR_PROJECT_REF.supabase.co   # empty = use pooler

# After updating .env
set -a && source .env && set +a
.venv/bin/alembic upgrade 001
sudo systemctl restart juli-api
```

Use the **same pooler `DATABASE_URL`** for both Alembic and `juli-api`.

---

## Separately-operated contract migrations

The `api` deploy lane runs `infra/scripts/migration_additive_gate.py` before it
starts any candidate instance, and **refuses** a pending migration that moves
rows or narrows a column. That is deliberate: during a release the candidate and
the still-serving stable instance share one database, and only additive change
keeps a code rollback possible. The gate has no allowlist and must not be given
one.

So a schema change that genuinely needs a backfill or a `NOT NULL` is split in
two: an **expand** step that ships with the release, and a **contract** step an
operator runs by hand once the expand release is serving. A contract migration
lives in
`backend/src/juli_backend/database/migrations/deferred/`, **not** in
`versions/` — in `versions/` it would be pending on every release, the gate
would refuse it, no candidate would start, and the expand code it depends on
could never go live.

**Currently outstanding:** `074_users_placeholder_phone_cleanup` (#1972) —
sets `users.phone` to NULL on every row whose stored number equals the value
the removed code derived from that row's own id
(`f"+849{user_id.int % 10_000_000_000:010d}"`). Until it runs, those sellers
still carry a fabricated Vietnamese mobile that is not theirs, in a `UNIQUE`
column a real number could later collide with;
`064_users_phone_nullable` and the code change that stopped minting new ones
are already in the expand release.

**Unlike `063_workflow_subject_contract`, running this late is harmless** —
every day it waits is a day the fabricated rows sit in a column nothing reads.
Running it *before* the expand release serves is pointless rather than
dangerous: the old code would write the placeholders straight back. Its
precondition is therefore that the serving release contains
`064_users_phone_nullable` and `alembic current` reports
`073_waiting_external`. The step is idempotent, so an operator unsure
whether it already ran may simply run it.

> **This step has now been renumbered four times** — 065 → 066 (#1973),
> 066 → 070 (#1712), 070 → 072 (#1950), 072 → 074 (#1706) — because it must
> stay the **tail** of
> the chain: a deferred step with a later revision above it forks the chain the
> moment it is copied into a serving release's `versions/`, and
> `alembic upgrade head` then refuses with multiple heads. It has not been
> applied anywhere.
>
> **Every PR that adds a migration to `versions/` must re-parent this file onto
> the new head** and update `PHONE_REVISION`, `CLEANUP_REVISION`,
> `CLEANUP_PATH` and `_SCHEMA` in
> `tests/unit/test_users_phone_placeholder_cleanup.py`, plus
> `EXPECTED_DEFERRED_FILES` in
> `tests/unit/test_workflow_subject_contract_migration.py`.
>
> **Choosing a deferred number "above" a known concurrent sibling does not
> avoid this.** #1712 tried that (070 sits above both 068 and 069) and it still
> had to move, because #1950's own revision could not stay a second child of
> 065 once 069 landed there. Only being re-parented onto whatever actually
> becomes the head is merge-order-proof.
>
> All three renumbers were found by a red test *after* a merge race, never
> prevented before one. This should become a pre-commit check that re-parents
> the deferred tail automatically — see #1950's PR body and review artifact.

See "Applied contract migrations" below for the worked example this procedure
was written against.

### Preconditions — check all three before running anything

1. **The expand release is serving.** The running `juli-api` must be a release
   that contains the expand step this contract step chains onto. The contract
   step is what makes an INSERT that omits its column(s) fail; any older code
   still serving starts erroring the moment it lands. Running it early is the
   one way to turn a stalled release into an outage.
2. **The database is at the expand revision.**
   `.venv/bin/python infra/scripts/safe_alembic_helpers.py current-revision`
   must print the expand step's revision id. If it prints an earlier one,
   stop — the expand step has not been applied.
3. **A verified backup exists.** Take one now if the release's own
   `safe-alembic-upgrade.sh` did not just run (see ADR-027).

### Procedure

Run on the VPS, against the release directory that is **currently serving**
(`~/releases/<sha>`); `RELEASE_DIR` below is that path.

```bash
# 1. Confirm precondition 2 with the release interpreter, not system python3.
# Capture it — step 3 needs it as an explicit start revision, not "head".
FROM_REV="$("${RELEASE_DIR}/.venv/bin/python" \
    infra/scripts/safe_alembic_helpers.py current-revision)"
echo "${FROM_REV}"   # must be the expand step's revision id, never earlier

# 2. Copy the contract migration into the serving release's chain and LEAVE IT
#    THERE. Removing it afterwards leaves Alembic at a revision with no file on
#    disk — the same care taken for 056_series_source_column on 2026-09-09.
cp backend/src/juli_backend/database/migrations/deferred/<NNN_contract_name>.py \
   "${RELEASE_DIR}/backend/src/juli_backend/database/migrations/versions/"

# 3. Preview the SQL offline before writing anything — from the database's
#    ACTUAL current revision, never a bare `alembic upgrade head --sql`.
#    Offline mode has no database connection, so with no explicit start it
#    does not know where the database already is and replays the ENTIRE
#    chain from base. Run as a bare `alembic upgrade head --sql` against
#    production on 2026-09-20 (063_workflow_subject_contract), this got 14
#    migrations in and died on `049_drop_legacy_isolation_policies`, which
#    runs a live `pg_policies` query offline mode has no connection for
#    (`AttributeError: 'NoneType' object has no attribute 'all'`). Nothing
#    was written — offline mode cannot write — but the preview is useless
#    without the explicit start.
cd "${RELEASE_DIR}" && .venv/bin/alembic upgrade "${FROM_REV}:head" --sql
```

**If the contract migration's own `upgrade()` runs a live pre-flight guard**
— a query against `op.get_bind()` before it writes anything, the way
`063_workflow_subject_contract._refuse_if_a_subjectless_run_exists` counted
rows with both `subject_ref` and `product_id` NULL — step 3's preview
**cannot complete for that migration, and that is expected, not a fault.**
Offline mode has no connection for the guard to query either, so it raises
the same class of error one migration later (for 063, immediately after
fixing the range above:
`AttributeError: 'NoneType' object has no attribute 'scalar_one'`). The
preview mechanism itself cannot represent a migration whose `upgrade()`
reads the database before deciding what to write. When this happens: skip
completing the preview for this migration, read the guard's query out of the
migration's source, and run it by hand against the database instead. For
063 that query was:

```sql
SELECT COUNT(*) FROM public.workflow_runs WHERE subject_ref IS NULL AND product_id IS NULL;
-- must be 0, or the migration will refuse the same way online, before
-- writing anything, when step 4 runs it for real
```

```bash
# 4. Apply, through the backup/row-count wrapper. This runs online, so both
#    the guard and the migration's SQL execute for real here regardless of
#    whether step 3's preview completed.
RELEASE_DIR="${RELEASE_DIR}" API_ENV_FILE="${API_ENV_FILE}" \
    infra/scripts/safe-alembic-upgrade.sh

# 5. Verify.
"${RELEASE_DIR}/.venv/bin/python" \
    infra/scripts/safe_alembic_helpers.py current-revision
```

If the migration carries its own guard (like 063's), it refuses itself,
before writing, when that guard's condition is not met — resolve the
offending rows and re-run rather than editing the guard away.

**Afterwards**, land a follow-up PR moving the file from `deferred/` into
`versions/`. It is applied by then, so it is no longer pending and the gate
accepts the next release. Until that PR merges, the repo's Alembic head stays
at the expand revision while production is one step ahead — expected, and the
reason step 2 leaves the copied file in place.

**Rollback** is the migration's own `downgrade()`. For 063 specifically, that
reopens the column to nullable and deliberately does not erase the backfilled
values — check the migration you are operating for whether its own downgrade
makes the same choice.

### Applied contract migrations

| Migration | Applied | Verified | Follow-up |
|---|---|---|---|
| `063_workflow_subject_contract` (#1701, #2050) | 2026-09-20T12:06Z | `alembic_version` = `063_workflow_subject_contract`; `workflow_runs.subject_ref` `NOT NULL`; 37/37 rows backfilled, 0 NULL; row counts identical pre/post | #2057 promoted the file from `deferred/` into `versions/` |

---

## Local development migration gate

For local schema changes, use the safety-gated wrapper instead of a bare
`alembic upgrade head`:

```bash
cd ~/Juli-AI-v2
cp -n .env.example .env   # fill DATABASE_URL
./infra/scripts/safe-alembic-upgrade-local.sh
```

Behavior:

- Loads `DATABASE_URL` from the repo-root `.env` (same convention as `runtime.py`).
- Prints the resolved Supabase project ref (or `local/non-Supabase host: …`) and,
  when stdin is a TTY, prompts for `yes` before proceeding.
- Writes a pre-migration `pg_dump` to `~/.juli-backups/` (override with `BACKUP_DIR`).
- Snapshots protected-table row counts before/after and aborts with a `pg_restore`
  command on regression — same helpers as the VPS deploy gate
  (`safe-alembic-upgrade.sh`).

Non-interactive / scripted use: pass `--yes` or set `SAFE_MIGRATE_YES=1`.

Against a disposable local Postgres with zero rows (e.g. a fresh Docker container),
the gate still runs but completes quickly — backup is small and row-count checks are
no-ops when counts do not decrease.

Production deploys continue to use `infra/scripts/safe-alembic-upgrade.sh` via
`deploy-release.sh` (fully non-interactive, no TTY prompt). See
[ADR-027](../adr/027-database-migration-safety-pipeline.md).

### /health returns non-2xx over HTTPS but works locally

Nginx upstream or TLS may be misconfigured — re-run [#256](vps-wiring-runbook.md)
checks:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
curl -sS https://api.app-juli.com/health
```

Full deploy reference: [`app-review-runbook.md`](app-review-runbook.md).
