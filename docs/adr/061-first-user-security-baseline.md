# ADR-061: First-user security baseline — default-deny data boundary + enforced invariants

**Status:** Accepted
**Date:** 2026-08-09
**Deciders:** grill-with-docs (Architect) — **Q1 approved** (default-deny `public` boundary);
**Q2 approved** (CI invariants + startup assertions as the drift-catching mechanism)

**Builds on:** [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) (CI hardening —
`bandit`, `gitleaks`), [ADR-057](057-pre-user-delivery-on-single-vps.md) (pre-user delivery stays
on the single VPS; candidate bound to loopback — the topology every control here assumes),
[ADR-033](033-weekly-secrets-security-check.md) (weekly secrets check),
[ADR-046](046-cdp-medallion-physical-model.md) (medallion grants; gold-only client exposure),
[ADR-003](003-ai-native-cicd-policy.md) (artifact-driven gates).
**Relates to:** [ADR-039](039-docp-phase-2.11-openobserve-posthog.md) — structured logging is a
prerequisite for security observability, and this ADR adds a hard ordering constraint to it.
**Does not change:** the unauthenticated public Demo read surface ([ADR-037](037-phase-2.10-demo-real-data-no-auth.md)),
VPS/SSH deploy topology (ADR-020), or the medallion layer model (ADR-046).

## Context

A pre-first-user audit swept ten security controls across the FastAPI backend, Supabase
Postgres, Next.js apps, iOS, Nginx, and CI. Two controls came back clean: **no secret has
ever been committed** (full-history scan; `.gitignore` verified effective; all vendor calls
server-side; iOS ships only the public anon key), and **input handling is sound** (Pydantic at
every boundary, `hmac.compare_digest` for webhook signatures, zero string-built SQL, no shell
execution).

Three findings block a first user:

1. **Authentication fails open.** `core/security/dependencies.py:27` reads
   `os.environ.get("SUPABASE_JWT_SECRET", "")`. Unset ⇒ every protected route verifies JWTs
   against an empty-string HMAC key. `api/main.py:32` proves the fail-fast idiom
   (`require_env("DATABASE_URL")`) exists and was simply not applied here, and
   [`backend-deploy-runbook.md:48`](../runbooks/backend-deploy-runbook.md) actively documents
   the variable as *"Optional when frontend uses UI-only demo login."*
2. **Thirteen `public` tables have no RLS and never did** — including `action_cards` and
   `webhook_raw_events` (raw webhook bodies, no `shop_id` column at all). The ten policies that
   *do* exist key off `current_setting('app.current_user_id')`, which the backend never sets, so
   they have never scoped a row — they only deny by raising.

   **The decay is active, not historical.** The audit found eleven such tables; re-checking against
   `origin/main` during the same session found **two more that landed within the previous week** —
   `027_decision_emission_budget` and `028_demo_execution_records`, neither carrying a single
   `ENABLE ROW LEVEL SECURITY` statement. Any fix expressed as "remember to add a policy to each new
   table" is losing this race in real time; only a default can win it.
3. **No logging configuration exists.** No `basicConfig`/`dictConfig` anywhere, no `--log-config`
   on the systemd unit. Every `logger.info` audit event is discarded and every `logger.warning`
   loses its `extra={user_id, shop_id, error}` payload. No client IP is captured; uvicorn runs
   without `--proxy-headers`, so access logs show `127.0.0.1`.

The decisive question was not *which fix* but *why the standard decayed*. RLS was applied in
migrations 001–002, then silently dropped from 006, 007, 009, 011, 012, 013, 014, and 016 —
because `public` never had `ALTER DEFAULT PRIVILEGES` set, so each new table inherited Supabase's
permissive bootstrap grants. The medallion schemas did not decay, because
[migration 021](../../backend/src/juli_backend/database/migrations/versions/021_medallion_schemas.py)
set default privileges on `bronze`/`silver`/`ops`. **The controls that survived were the ones
expressed as defaults; the ones expressed as conventions rotted.**

## Decision

### 1. Default-deny on `public`, not per-table RLS

Extend migration 021's existing role-guarded `_revoke_client_access` helper to the `public`
schema: `REVOKE ALL` from `anon`/`authenticated` **plus** `ALTER DEFAULT PRIVILEGES … REVOKE ALL
ON TABLES/SEQUENCES`. Future tables in `public` are then born closed with no author action.

- Chosen over enumerating RLS on thirteen tables, which requires perpetual vigilance the team has
  already been shown to lose (two more tables landed unprotected during this very audit), and which
  cannot even be expressed for `webhook_raw_events` (no tenant column).
- Safe today: no `supabase-js` in any frontend, the backend connects via the pooler `postgres`
  role, and the iOS anon key targets GoTrue (`/auth/v1`), not PostgREST. The `gold` schema
  `USAGE` grant ADR-046 §5 implies was never issued, so no client-direct read path exists to break.
- **RLS is not abandoned** — it is deferred to where it will actually be exercised: `gold`, keyed
  to `auth.uid()`, built when 3.5-C Login mode ships client-direct reads. The ten existing
  `app.current_user_id` policies are to be treated as **non-functional** and rewritten at that time,
  not trusted in the interim.

### 2. Enforcement = CI invariants + startup assertions

Every control gets a machine check. Controls CI can observe become build failures; controls that
depend on deployed configuration become boot failures.

**CI invariants** (extend `pr.yml`; DB check hangs off the existing `migration-check` job, which
already stands up Postgres 16 and runs `alembic upgrade head`):

| Invariant | Assertion |
|---|---|
| Data boundary | Create `anon`/`authenticated` roles, `upgrade head`, then assert via `pg_catalog` that no table outside an explicit `gold` allowlist is reachable by those roles |
| Route auth | Walk `app.routes`; assert every `/v1/*` route depends on `get_current_user` or `get_active_shop`. Allowlist: `demo_analytics`, `webhooks`, `health` |
| Debug surface | Assert `docs_url`/`redoc_url`/`openapi_url` are `None` when `ENVIRONMENT=production` |
| Secret handling | Ban credential-bearing query strings (custom lint / bandit rule) |
| Rate limiting | Assert a limiter is attached to the public read and webhook routes |

Creating the PostgREST roles in CI is itself a fix: migration 021's `IF EXISTS` guards mean its
medallion revokes have been **silently skipped on every CI run to date** and are untested.

**Startup assertions** (fail to boot): `require_env("SUPABASE_JWT_SECRET")`, debug flags off when
`ENVIRONMENT=production`.

**Prerequisite — no environment discriminator exists.** A repo-wide search finds no
`ENVIRONMENT`/`APP_ENV` concept in `backend/src`, `infra/scripts/env/`, or `infra/systemd/` (the
only `is_production_*` symbols are unrelated TikTok capability guards in
`integrations/tiktok/capabilities.py:147`). The application literally cannot tell which
environment it is running in, which is *why* `/docs` is unconditional at `api/app.py:31-32` and
why the debug route needed the ad-hoc `ENABLE_TIKTOK_DEBUG` flag rather than a production check.
Introducing `ENVIRONMENT` is therefore a **blocking prerequisite** for the debug-surface invariant
and its startup assertion, not an incidental detail — every "off in production" control depends on it.

### 2b. Rate limiting — Nginx primary, one targeted application limit

Inbound rate limiting is absent everywhere (the Redis token buckets in
`integrations/tiktok/rate_limiter.py` are **outbound** TikTok quota control, not inbound
throttling). It lands at the **edge**, not in the app:

- **Nginx `limit_req` zones** per location — strict on `/webhooks/tiktok` and `/v1/demo/*`,
  strict on `/v1/auth/*` (credential stuffing), generous on the authenticated catch-all.
- **One application-level per-shop limit** on `POST /v1/action-cards/refresh`, which Nginx cannot
  express because the caller is authenticated and same-IP; `services/action_cards/dispatch.py:31-35`
  enqueues a TikTok-polling + scoring Celery job unconditionally on every call, with no debounce.

Chosen because `infra/systemd/juli-api.service:30` runs uvicorn with **`--workers 1`** — a single
process serves all API traffic, so availability can only be defended before requests reach Python.
An app-only limiter was rejected for two evidenced reasons: the flood still saturates the sole
worker (a 429 costs nearly as much as a 200), and `REDIS_URL` is commented out at
`infra/scripts/env/api.env.example:58` while `api/main.py:36` warms Redis "fail-open if unset" —
reproducing the exact fail-open shape as the `SUPABASE_JWT_SECRET` finding.

The rate-limiting invariant therefore splits: an **Nginx config lint** asserting `limit_req` on the
webhook and demo locations, plus a **route test** for the refresh limiter.

CI alone was rejected because the highest-severity finding is invisible to it — a missing env var
lives in AWS Secrets Manager, a stale debug flag lives in a systemd env file, and a re-enabled Data
API lives in the Supabase console. None are in git. Runtime-only was rejected because it catches
regressions only once they are already reachable in production.

### 2c. Security logging baseline now — vendor-free and OpenObserve-ready

A minimal logging baseline ships in this workstream rather than waiting for Phase 2.11: root
`dictConfig` emitting JSON to stdout (journald captures it today), a `request_id` middleware that
echoes the id in responses and error bodies, `uvicorn --proxy-headers` so the real client IP
replaces Nginx's `127.0.0.1`, coverage for the events that currently vanish (webhook signature
rejection, missing/invalid JWT, `shop_access_denied`, limiter 429s), and documented journald +
Nginx `logrotate` retention.

Deferring entirely to ADR-039 was rejected because issue **#539 is still open at PRD stage with no
child issues cut** — an unbounded wait during which a breach would leave only bare event names with
no IP, user, or shop, and no trace whatsoever of webhook signature rejections. Pulling the
OpenObserve shipper forward was also rejected: it couples first-user readiness to vendor
onboarding, new Secrets Manager entries, and a new egress dependency.

Nothing here is throwaway — Phase 2.11 points a shipper at the same JSON stream.

### 3. Ordering constraint on ADR-039

`integrations/tiktok/auth.py:76` passes `app_secret`, `auth_code`, and `refresh_token` as GET
**query-string** parameters and logs `str(exc)` on failure; `requests` embeds the full URL in
`ConnectionError`/`HTTPError` messages. This is inert only because logging is unconfigured.

**Fixing the logging configuration before fixing this call site would begin writing live OAuth
secrets into logs**, violating ADR-039's own "hard deny: OAuth/API tokens" clause. The sibling
Business clients (`business_account_holder_auth.py`, `business_advertiser_auth.py`) already use
`requests.post(json=payload)` and are safe — the fix is to match them. This ordering is binding on
any Phase 2.11 logging work.

## Delivery sequence (dependency-forced, not preference)

1. **`ENVIRONMENT` discriminator** — blocks every "off in production" control (§2 prerequisite).
2. **`require_env("SUPABASE_JWT_SECRET")` + runbook correction** — highest severity, one line;
   `backend-deploy-runbook.md:48` must stop calling it optional in the same change.
3. **`integrations/tiktok/auth.py` query-string → POST body** — must precede step 5, or logging
   begins writing live OAuth secrets to disk.
4. **Default-deny migration on `public`** + CI data-boundary invariant (creating the
   `anon`/`authenticated` roles in `migration-check` also gives ADR-046's medallion revokes their
   first real test coverage).
5. **Logging baseline** (§2c) — safe only after step 3.
6. **Nginx `limit_req` zones** + per-shop limit on action-cards refresh (§2b).
7. **Debug-surface closure** — gate `docs_url`/`redoc_url`/`openapi_url` on `ENVIRONMENT`; add a
   real auth dependency to `/debug/tiktok/verify-connection` (unauthenticated cross-tenant IDOR
   today, gated only by an env flag) or delete it; resolve the dashboard's credential-free
   `loginAsReviewer()` stub.
8. **Remaining CI invariants** — route-auth walk, secrets-in-query-string lint, Nginx conf lint.

Steps 1–3 are individually small and carry the most risk reduction; step 4 is the largest single
migration.

## Consequences

- **Positive:** the data boundary becomes a property of the schema rather than a convention, so
  the specific decay that produced eleven exposed tables cannot recur.
- **Positive:** medallion grants from ADR-046 gain real test coverage for the first time.
- **Positive:** `SUPABASE_JWT_SECRET` becomes mandatory, closing a total-auth-bypass path.
- **Negative:** `backend-deploy-runbook.md:48` must be corrected — it currently documents the
  fail-open as acceptable, and the App Review "UI-only login" path that motivated it must either
  supply the secret or be retired.
- **Negative:** startup assertions mean a missing secret becomes an outage rather than a silent
  degradation. That is the intended trade; it must be reflected in the deploy runbook and rollback path.
- **Deferred:** working RLS on `gold` keyed to `auth.uid()` (3.5-C); rewriting the ten
  non-functional `app.current_user_id` policies; adding a tenant column to `webhook_raw_events`.

## Options considered

| Alternative | Why rejected |
|---|---|
| Enumerate RLS on all eleven `public` tables, keep Data API on | Per-table opt-in is the mechanism that already failed; requires fixing the broken GUC pattern first; inexpressible for `webhook_raw_events` |
| Revoke **and** full corrected RLS in one workstream | Safest end state but 2–3× the migration surface, and collides with the in-flight ADR-046 medallion cutover |
| CI invariants only | Cannot observe VPS env vars, systemd debug flags, or Supabase console settings — precisely where the top finding lives |
| Runtime assertions + post-deploy probe only | Catches regressions only after they are live and reachable |

## References

- Audit evidence: `core/security/dependencies.py:27`, `api/main.py:32`,
  `integrations/tiktok/auth.py:76`, `api/routes/debug_tiktok.py:36-38`, `api/app.py:31-32`,
  `infra/systemd/juli-api.service:29-30`, migrations 006/007/009/011/012/013/014/016.
- Durable pattern to extend: `021_medallion_schemas.py:36-66`.
- CI hook points: `.github/workflows/pr.yml:309` (`migration-check`), `:531` (`policy-checks`).
