# ADR-080: TikTok credential lifecycle — layered refresh, single source of truth, needs_reauth

**Status:** Proposed
**Date:** 2026-08-17
**Deciders:** grill-with-docs (Architect) with owner, during W3 live-gate preparation

**Builds on:** ADR-030 (secrets posture), ADR-068 (capability boundary), the existing
refresh primitives (`TikTokAuthClient.refresh_access_token`,
`core/security/tiktok_oauth.py::refresh_tokens`/`refresh_merchant_tokens`,
`services/tiktok/token_expiry.py`, encryption at rest via
`TIKTOK_TOKEN_ENCRYPTION_KEY`).

## Context

The refresh primitives exist but nothing invokes them automatically: no beat task, no
lazy refresh at `resolve_*_credential`. Access tokens die silently at day 7; the
sandbox credential was hand-seeded interactively; local live-lane runs required
hand-copying encrypted rows between databases. W3's live smokes made the cost
concrete. Production-grade systems (Google oauth client libs, Supabase auth,
Nango-class integration platforms) converge on refresh-ahead scheduling plus
single-flight locking; this ADR adopts that shape over the existing rows.

## Decision

1. **Layered refresh.** A 30-minute beat task scans `tiktok_credentials` for access
   tokens inside a refresh-ahead window (< 24h to expiry) and refreshes them; and
   `resolve_*_credential` checks expiry at read time, refreshing lazily if the beat
   missed. Beat keeps tokens warm (no refresh latency on hot paths); the lazy path
   guarantees correctness when the worker was down.
2. **Single source of truth via `CREDENTIALS_DATABASE_URL`** (default:
   `DATABASE_URL`). The credential resolver gains an optional dedicated engine.
   Production/VPS leaves it unset (zero change). Local smokes and live-lane tests
   point it at the Supabase DB while run tables stay local — credential reads and
   refreshes from ANY environment hit the one true row; hand-copying is
   structurally unnecessary. Credential writes stay transactionally independent of
   run-table writes (they already are; cross-DB transactions do not exist).
3. **Retry-then-mark failure handling.** Transient failures (network, 5xx, rate
   limit): beat retries next cycle; lazy path does one bounded in-line retry; the
   credential serves until real expiry. Terminal failures (invalid-grant class, or
   expiry passed with refresh still failing): set new column
   `tiktok_credentials.status = 'needs_reauth'` (default `'active'`) +
   `last_refresh_error` + timestamp; resolvers fail closed naming the re-OAuth
   runbook step; a security-event log line fires. Credentials are never deleted
   automatically; consumers never see a silent 401.
4. **Single-flight refresh via Postgres advisory lock** on the credentials DB:
   `pg_try_advisory_xact_lock(hashtext(credential_id))`; if held, skip (re-read
   after the winner commits). After acquiring, re-read expiry — if a concurrent
   refresher already renewed, skip the vendor call (double-refresh guard). Winner
   writes tokens + expiry in one transaction. Because decision 2 routes every
   environment to the same DB, the lock is global across environments by
   construction. Rejected: `SELECT FOR UPDATE` (row lock held across an external
   HTTP call); optimistic CAS (loser has already spent a possibly-single-use
   refresh token).
5. **Audit via columns + structured logs, no new table.** `tiktok_credentials`
   gains `last_refreshed_at`, `refresh_count`, `last_refresh_error` (+ `status`).
   One structured log line per attempt (`tiktok_credential_refresh`: credential
   id, capability, outcome, latency — never tokens); per-cycle beat summary
   (scanned/refreshed/skipped-locked/failed). Upgrade path when multi-merchant
   scale makes history matter: a `credential_refresh_events` audit table.
6. **Tests and phase gate.** Unit: window selection boundaries; lazy trigger;
   transient-vs-terminal classification; fail-closed `needs_reauth` resolver
   message; no-token-in-logs. Concurrency (real Postgres): two refreshers → exactly
   one vendor call; acquire-after-renewal → zero vendor calls. Config seam: two
   disposable DBs prove credential I/O follows the second engine while run tables
   follow the first; unset → single engine, zero change. Beat wiring: schedule
   entry, cycle summary, `needs_reauth` exclusion. **Gate:** all green plus one
   real end-to-end refresh of an actual TikTok token (the sandbox credential,
   expiring 2026-08-24, is the natural candidate) — row shows new expiry +
   incremented `refresh_count`, log line present.

## Consequences

- The manual seeding/copying performed during W3 live-gate prep becomes a one-time
  bootstrap; steady-state credential health is automatic and queryable.
- Multi-merchant rollout (P13, per-merchant OAuth) inherits a lifecycle instead of
  multiplying manual token care.
- New env surface: `CREDENTIALS_DATABASE_URL` (optional), documented in the
  runbook's Secret inventory alongside its default-unset semantics.
- Implementation is one slice (backend/data-platform), scheduled after the W3
  wave→main merge; not on the W3 exit-gate critical path.
