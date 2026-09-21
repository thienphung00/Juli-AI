# ADR-105 — A poll cycle has a verdict, and leaves a record a formatter cannot drop

- **Status:** Accepted
- **Date:** 2026-09-21
- **Issue:** #1950
- **Supersedes nothing. Extends:** [ADR-104](104-poll-steps-report-outcomes-inside-the-cycle-budget.md) (#1969, PR #2009)

## Context

Two production data-loss bugs survived for months for one structural reason: **a
poll step that failed or dropped its rows was indistinguishable from one that
had nothing to do.**

- **#1948** — `sync_inventory` called Search Inventory without the `product_ids`
  the endpoint hard-requires, caught the resulting `TikTokAPIError`, logged a
  warning and returned `None`. 100% failure rate, invisible for the lifetime of
  the table, because "no inventory row" and "no inventory to sync" are the same
  observation.
- **#1949** — `sync_orders` advanced `tiktok_sync_state.last_update_time`
  regardless of how many rows actually landed. 3,581 orders fetched and skipped,
  with a healthy-looking `updated_at` on every run.

Both were found by querying the destination table and comparing it against the
vendor API by hand. The issue notes this is the **third** occurrence of the
shape in this repository (the hourly-reconcile "never commits" defect is the
first).

ADR-104 / #1969 closed most of it: `SyncOutcome` replaced every step's `None`
return, `_StepRun.report` raises `PollStepDroppedRowsError` when
`fetched > 0 and persisted == 0`, and the four search steps gate their
watermark on `outcome.persisted`. Its own PR body recorded two things it had
deliberately left open, and a third the review found:

1. **A failed FETCH still completed the cycle.** `sync_orders`,
   `sync_products` and `sync_returns` catch `TikTokAPIError` around the vendor
   call and `return step.report(error=exc)`. The outcome carries `ok=False` —
   and nothing read it. `_poll` discarded every return value.
2. **The analytics watermarks were never gated.** `sync_analytics` fans out
   over ~10 endpoints, each of which wrote `sync_state[<key>] = synced_at` the
   instant its LIST call returned, before one row had reached the ETL.
3. **The observability is inert where the poll runs (#1978).** Every field
   `poll_step_outcome` carries travels in `logger.*(extra={...})`, rendered
   only by `JsonFormatter`, installed only by `configure_logging`, whose sole
   caller is `api/main.py`. `workers/celery_app.py` has never called it. In the
   Celery beat process an operator sees the event name and **none of the
   numbers**. Every test reads `LogRecord` through `caplog`, which bypasses the
   formatter and structurally cannot see this.

## Decision

### 1. A cycle in which any step failed is a failed cycle

`_poll` collects each step's `SyncOutcome` and `_assert_cycle_succeeded` raises
`PollCycleFailedError` when any of them reports `ok=False`.

**Why an end-of-cycle verdict rather than making the three fetch arms raise.**
Raising at the fetch would abort the cycle at step 1 of 5 and prevent the other
four endpoints from running at all — turning one endpoint's vendor outage into
a total sync outage, and reintroducing the "a loud failure that silently
enlarges the next read" trade ADR-104 refused. Collecting and judging at the end
gets both: every endpoint that can still work does, and the cycle is still
loudly a failure.

**The verdict is raised after the writes, not before.** `_record_cycle` persists
the partial `sync_state` and the per-endpoint verdicts, and only then does
`_assert_cycle_succeeded` raise. Raising first would leave the one durable
record of what failed unwritten, which is the position this issue started from.
`_record_cycle` is itself guarded and never raises: an exception escaping from
the bookkeeping would replace a diagnosable failure with an undiagnosable one.

**Accepted cost.** `services/action_cards/refresh.py::maybe_poll_tiktok_data`
(ADR-021 manual refresh) calls the cycle with no `try`/`except`, so a vendor
outage now fails a manual refresh where it previously produced stale cards
quietly. That is the direction this issue exists to push; `refresh.py` was not
modified to soften it.

### 2. A watermark is charged to the endpoint whose rows it describes

Analytics watermarks are **staged** at the point the write used to happen and
committed by `_StepRun.flush_watermarks`, which charges each endpoint the rows
offered between its own stage point and the next one.

**Why per-endpoint and not per-step.** `sync_analytics` is one `_StepRun` with
one shared pair of counters. A gate asking "did this STEP persist anything"
would advance the SKU cursor on the strength of the shop-performance rows — the
same wrong answer with more arithmetic. The staging ledger makes the arithmetic
per-endpoint without threading a counter through ten call sites.

**The rule is the issue's, both halves.** Advance on `persisted > 0`, **or** on
a genuine `offered == 0`. An endpoint whose window held no rows is not a
failure and must not be refetched forever; three analytics endpoints
(`bestselling_products`, `bestselling_videos`, `promotion_activity`) offer no
rows at all by construction and keep advancing, unchanged.

**The ledger is flushed on every exit path**, including the exception one, for
the same reason `_poll` saves partial state before re-raising: a step that dies
at endpoint 7 of 10 must not discard the six cursors whose rows did land.

**Constraint this creates.** `stage_watermark` must be called where the write
used to be — immediately before the endpoint's own handoffs. One call
(live-performance) sat after its handoff and was moved; staged there the
interval is empty, the gate reads "nothing offered", and the watermark advances
over dropped rows exactly as before. The constraint is stated in the method's
docstring and pinned by
`test_one_endpoints_rows_do_not_unlock_a_siblings_held_back_cursor`.

### 3. The verdict is a column, not only a log line

`tiktok_sync_state` gains six nullable columns (migration `067`):
`last_outcome`, `last_outcome_at`, `last_fetched`, `last_persisted`,
`last_error`, `last_success_at`. `TikTokSyncStateRepo.record_outcomes` writes
them, and — unlike `save` — **INSERTS a row for an endpoint that has no
cursor.**

That insert is the decision. `save` iterates the cursors present in
`sync_state`, and a step that never persisted a row contributes none, so an
endpoint that has failed every time it ever ran leaves no row at all. That is
exactly how #1948 stayed invisible. `last_success_at IS NULL` on a row that
exists is the question "has this endpoint ever succeeded", in SQL; it is only
ever advanced, never cleared, so the answer survives the next failure.

It is also **the answer to (3) above that does not wait on #1978.** A column
does not go through a log formatter. This is why #1950 can close while #1978 is
still open — but it is also why the new `poll_cycle_outcome` and
`poll_watermark_held_back` events must not be read as production-visible
evidence until #1978 lands.

`sync_analytics` is one step over seven `tiktok_sync_state` endpoints, so its
single verdict is written to all seven. That over-approximation can mark a quiet
endpoint failed when a sibling dropped rows. It errs in the direction this issue
wants, and it is written down rather than discovered later.

## Consequences

- `run_fujiwa_poll_cycle` and `run_fujiwa_material_resource_fetch` now raise
  where they previously returned over a failed vendor fetch. Breaking, by
  design, and recorded as such in the polling `MODULE.md`.
- "Has this endpoint ever succeeded?" becomes a SQL query instead of an
  inference from a missing row.
- `persisted` still means "the ETL handoff accepted the row without raising",
  not a committed Postgres row — `HandoffFn` is typed `-> None` and
  `make_etl_handoff` discards `EtlConsumer.ingest`'s `ProcessOutcome`, so a
  DLQ'd row counts as accepted. ADR-104 recorded this; every number written to
  `tiktok_sync_state` inherits it. Widening that contract belongs in
  `services/ingestion/handoff.py`.
- `sync_creators` and `sync_products_with_local_upsert` still return `None` and
  still advance their watermarks ungated. Neither is in `_FUJIWA_POLL_STEPS`, so
  neither is reached by the cycle this ADR governs; both carry the shape and are
  left for a follow-up rather than silently widened into this slice.
- Migration `067` chains onto `065_users_email`, the head of `versions/`. Because
  #1972's deferred contract step also chained onto 065 — and a test forbids a
  second child, which would fork the chain the moment an operator copies the
  deferred file into a serving release — that step is renumbered onto `067`
  (`deferred/068`). The rule now sits in the deploy runbook explicitly: **every
  PR that adds a migration to `versions/` must renumber the deferred tail onto
  the new head.**

## Alternatives considered

**Make the three `except TikTokAPIError` arms raise.** Rejected: one endpoint's
outage becomes a total sync outage, and the remaining endpoints lose the chance
to run at all. See decision 1.

**Gate the analytics watermarks on the step's total `persisted`.** Rejected: it
credits one endpoint's rows to another. See decision 2.

**Record the outcome in a new table rather than on `tiktok_sync_state`.**
Rejected: the question "has this endpoint ever worked" is asked about the same
`(shop, endpoint)` pair the cursor is keyed on, and a second table would make
"no row yet" ambiguous in a second place.

**Backfill `last_outcome` for existing rows.** Rejected on two grounds. It is a
data-moving `UPDATE`, which `infra/scripts/migration_additive_gate.py` refuses
from an automatic release by design; and there is nothing true to write — a row
that predates the column has no verdict, and a default of `'ok'` or `0` would
manufacture the claim that an endpoint succeeded, which is the comfortable
lie this whole issue exists to remove. NULL means "not measured", and that is
the honest value.
