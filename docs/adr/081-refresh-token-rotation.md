# ADR-081: Refresh-token rotation — three-layer refresh, one guarded door, vendor-authoritative expiry

**Status:** Proposed
**Date:** 2026-08-18
**Deciders:** grill-with-docs (Architect) with owner, during W4 planning

**Amends:** [ADR-080](080-tiktok-credential-lifecycle.md). ADR-080's decisions 1, 3, 4 and 5
are kept in intent and corrected in mechanism; its decision 2 (`CREDENTIALS_DATABASE_URL`)
is descoped from this slice. Where the two disagree, this ADR governs.

**Builds on:** ADR-027 (migration safety), ADR-030 (secrets posture), ADR-074 decision 4
(dedicated Celery queue precedent), the existing refresh primitives
(`integrations/tiktok/auth.py::refresh_access_token`,
`core/security/tiktok_oauth.py::_refresh_credential`, `services/tiktok/token_expiry.py`).

## Context

ADR-080 proposed a credential lifecycle but was never implemented. In the interval, the
owner kept 2 credentials alive with a session-scoped operator script
(`refresh_cloud_credentials.py`) that prompts for the cloud `DATABASE_URL`, loops two
hardcoded capabilities, and ends by telling the operator to re-copy rows into the local
smoke DB. That does not scale to the ~100 shops the Demo stage targets, and every dead
credential is an ingestion gap that is not backfillable once past TikTok's own retention.

Re-reading the code against ADR-080 surfaced six gaps. ADR-080 removes two of them, is
partial on two, silent on one, and — critically — **specifies a beat that would be a
no-op**:

1. **Rotation is unguarded.** TikTok returns a *new* refresh token on every refresh and
   invalidates the old one. Three call sites refresh today (`orchestrate.py:174`,
   `orchestrate.py:244`, `targeted_fetch_executor.py:253`) with no lock. Two concurrent
   refreshes of one row can leave a dead refresh token persisted — an unrecoverable shop.
2. **No refresh-token expiry is stored.** `refresh_token_expire_in` appears nowhere in the
   codebase, docs, or fixtures.
3. **No fleet driver.** Production reads are pinned to one hardcoded merchant
   (`PRODUCTION_AUTH_ID`); real seller credentials (`capability='seller_connect'`) have no
   refresh driver at all.
4. **Refresh failure is cycle-fatal.** `_refresh_credential` raises; the poll cycle aborts
   before any bronze row lands, so one bad credential costs every shop that cycle.
5. **No terminal state.** A dead credential is invisible until something 401s.
6. **`REFRESH_BUFFER = 30 minutes` contradicts ADR-080's 24h window.** ADR-080's beat
   selects rows with `< 24h` to expiry, then calls a function that returns early unless
   expiry is within 30 minutes. As specified, the beat scans 100 rows and refreshes none.
   The buffer is also shorter than a single hourly-reconcile run (~37 min).

A seventh problem is the reason a column-driven design cannot be the whole answer. The
sandbox credential's `token_expires_at` was **invented** by a seeding script (`now + 7d`)
rather than read from the vendor. The column claimed fresh while the API answered
`105002 Expired`, and the operator script had to grow a `FORCE_EXPIRED=1` flag that
backdates the column so the refresh would run at all. `token_expires_at` is a *cache of
the vendor's opinion*, and it can be wrong. Only the API response observes the truth.

## Decision

### 1. Three refresh layers, with distinct jobs

| Layer | Reads | Job | Detects a wrong expiry column |
|---|---|---|---|
| **Beat** — every 30 min, fleet-wide | column | keeps ~100 credentials warm with no human | no |
| **Lazy** — at `resolve_*_credential` | column | covers beat downtime | no |
| **Reactive** — on vendor `105002` / 401 | **the API's answer** | self-heals a lying column | **yes — the only layer that can** |

The reactive layer is `FORCE_EXPIRED=1` promoted from a manual flag to a typed argument:
force-refresh ignoring the column, retry the originating call **once**, and on refresh
failure mark `needs_reauth`. It is what actually retires the operator script, because it
removes the human who decides "the column is lying."

Reactive-only is rejected: at 100 shops every credential's first call after expiry would
fail, producing a constant drip of auth errors through the ingest path. Warm is the
optimization; reactive is the correctness.

### 2. One refresh-ahead constant: 24 hours

`REFRESH_BUFFER` becomes 24h and is the *single* value used by both the beat's scan
predicate and the guard inside the refresh function. This is what makes the beat's
placement on a shared worker safe: a 37-minute wait behind a reconcile run is irrelevant
against a 24h window, and fatal against a 30-minute one.

### 3. Expiry is vendor-authoritative — never synthesized

`token_expires_at` may only be written from a vendor token response.
`services/tiktok/token_expiry.py::access_token_expires_at(None)` currently synthesizes
`now + 1 hour`; it must raise instead. A wrong expiry is worse than a missing one, because
a wrong one *suppresses* the refresh that would have corrected it. Existing rows are not
backfilled with computed values — they acquire truth on their next real refresh.

### 4. One guarded door — `core/security/credential_refresh.py`

```python
async def refresh_credential(
    session: AsyncSession,
    credential_id: uuid.UUID,
    *,
    auth: TikTokAuth,
    force: bool = False,
) -> RefreshOutcome
```

`RefreshOutcome` carries the credential plus one of `fresh` (inside window, no vendor
call), `refreshed`, `locked`, `transient` (network/5xx/rate-limit — the existing
credential stays valid), `needs_reauth` (terminal, row marked).

- **It returns an outcome and does not raise on refresh failure.** This is the structural
  fix for gap 4: each caller must state its policy — the beat logs and moves to the next
  shop, the resolver fails closed *for that shop only*, the client retries once. Isolation
  stops depending on someone remembering a `try/except`.
- **`force` is the only per-caller variation.** Beat and lazy pass `False`; reactive passes
  `True`.
- Extracted from `TikTokOAuthService._refresh_credential` because three new callers should
  not construct an OAuth service carrying `redirect_uri` — an authorization-flow concern a
  refresh does not have. `refresh_tokens` / `refresh_merchant_tokens` remain as thin
  wrappers so nothing outside this slice breaks; the three direct call sites stop using
  them and go through the resolver instead.

### 5. Session-level advisory lock, never held across the vendor call

`pg_try_advisory_lock(hashtext(credential_id))` with `pg_advisory_unlock` in a `finally`,
**not** the transaction-scoped `pg_try_advisory_xact_lock` ADR-080 specified. ADR-080
rejected `SELECT FOR UPDATE` because it holds a lock across an external HTTP call, then
chose a lock with the same property. Worker sessions use `NullPool` deliberately
(`database.py:54`, #871), so an open transaction is a live Supabase pooler client slot —
the #813 exhaustion concern.

The sequence is: acquire → commit → **re-read the row** (if another refresher already
renewed, return `refreshed` with no vendor call) → HTTP → open transaction → write tokens
+ expiry → release. The re-read after acquiring is what makes concurrent rotation safe and
lives inside the function, not in three callers. Lock losers receive `locked` and poll the
row for a bounded couple of seconds rather than queueing, so twenty simultaneous `105002`s
produce one vendor call, not twenty rotations.

### 6. Dedicated `credentials` Celery queue

One `task_routes` entry plus one `-Q credentials` worker, mirroring ADR-074 decision 4
exactly. That decision isolated multi-minute agent runs so they "never starve beat or the
analytics tasks"; credential refresh has the same asymmetry inverted — a sub-second task
that must never queue behind the ~37-minute hourly reconcile on the shared `celery` queue.
It makes "refresh is not part of the data plane" structural rather than aspirational.

At 100 credentials with 7-day access tokens and a 24h window, steady state is ~14 refreshes
per day across ~48 cycles — roughly 0.3 vendor calls per cycle, over a 100-row scan. The
beat is not a throughput concern; it *removes* one, since refresh is currently a serial
dependency at the top of every poll cycle.

### 7. Five additive columns, no index, no rename

Migration `037`, chaining onto `036_cancel_requested_column`.

| Column | Type | Why |
|---|---|---|
| `status` | `varchar(20) NOT NULL DEFAULT 'active'` | gap 5 — scan predicate + fail-closed resolver; `active` \| `needs_reauth` |
| `last_refreshed_at` | `timestamp NULL` | the load-bearing health signal |
| `last_refresh_error` | `text NULL` | operator diagnosis without SSH |
| `refresh_count` | `integer NOT NULL DEFAULT 0` | free; a climbing count is the rotation-storm signal |
| `refresh_token_expires_at` | `timestamp NULL` | gap 2 — populated **only if the vendor sends it** |

`refresh_token_expire_in` has never been observed in a response, a fixture, or
`docs/integrations/tiktok_api/authentication.md`, so the design does not depend on it.
The unrecoverable-shop warning instead rides on `last_refreshed_at`: **staleness beyond one
access-token lifetime means something is wrong**, whatever the cause. That needs no vendor
cooperation and covers more failure modes. `refresh_token_expires_at` is an opportunistic
capture; the decision-9 gate reveals for free whether the field exists.

Rejected: an index on the scan predicate (~100 rows — the planner will seq-scan and be
right; revisit past a few thousand rows). Rejected: renaming `token_expires_at` to
`access_token_expires_at` — the asymmetry with `refresh_token_expires_at` is real but the
rename touches resolvers, repos, orchestrators and the smoke scripts, which is neither
minimal nor safe to deploy. The meaning is recorded in `CONTEXT.md` instead.

Every column is nullable or server-defaulted, additive, with no data migration and no
change to an existing read path — reversible by `DROP COLUMN`, deployed through
`infra/scripts/safe-alembic-upgrade.sh`.

### 8. `CREDENTIALS_DATABASE_URL` descoped

ADR-080 decision 2 solved a real pain — refreshing a *copied* row mints a refresh token
only the copy knows, orphaning the source of truth. But the fix routes production
credential I/O through a second engine to buy local-development ergonomics, which is the
opposite of "safe to deploy" for the slice that also introduces the fleet's only refresh
driver. The invariant is enforced by policy instead: **only the refresh beat writes
credentials; copies are read-only.** Revisit as its own slice if the pain returns.

### 9. Tests and phase gate

Unit: window-selection boundaries; the beat is *not* a no-op at 20h-to-expiry (the gap-6
regression); lazy trigger; reactive `force=True` path against a column that claims fresh
while the vendor says `105002`; transient-vs-terminal classification; fail-closed
`needs_reauth` resolver message naming the re-OAuth runbook step; `access_token_expires_at(None)`
raises; no token material in any log line.

Concurrency (real Postgres): two refreshers → exactly one vendor call; acquire-after-renewal
→ zero vendor calls; twenty simultaneous forced refreshes → one rotation; no transaction is
open across the vendor call.

Isolation: a `needs_reauth` credential mid-fleet does not abort the beat cycle, and does not
abort another shop's poll.

Wiring: schedule entry, `credentials` queue route, per-cycle summary
(scanned/refreshed/skipped-locked/failed), `needs_reauth` exclusion from the scan.

**Gate:** all green **plus one real end-to-end refresh of the live sandbox credential**
(`sandbox_write`, expiring 2026-08-24) — the row shows a new expiry, incremented
`refresh_count`, populated `last_refreshed_at`, and the log line present. This is the only
step that proves the vendor contract rather than our belief about it, and it is also the
observation that settles whether `refresh_token_expire_in` exists.

## Consequences

- `refresh_cloud_credentials.py` and its `FORCE_EXPIRED=1` flag are retired; the manual
  seeding and row-copying become a one-time bootstrap.
- Credential health becomes queryable (`status`, `last_refreshed_at`) instead of being
  discovered when an ingest cycle fails.
- Refresh leaves the data plane's critical path: ① scheduled sync starts with a warm token
  instead of a serial vendor round trip that can abort it.
- Multi-merchant rollout (P13) inherits a lifecycle rather than multiplying manual token care.
- New operational surface: one extra Celery worker process for the `credentials` queue.
- The design deliberately does **not** address ingest fan-out — production reads remain
  pinned to one hardcoded merchant. Refreshing 100 credentials and polling 100 shops are
  different problems; this ADR only claims the first.
