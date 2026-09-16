# ADR-104: A poll step reports its outcome, and runs inside the cycle's remaining budget

**Status:** Proposed
**Date:** 2026-09-16
**Deciders:** Owner, Architect, integrations Executor, Review (#2009)
**Related:** #1969, #1948, #1950, #1967, #1978, PR #2009, ADR-021, ADR-031

## Context

A Fujiwa poll cycle ran for **47 minutes** inside `ep_poll`, emitted nothing
between start and a single `tiktok_pagination_max_pages_reached` warning, and
had to be killed by hand. Under Celery beat that wedges a worker slot
indefinitely and silently. Three separate properties of the polling code
combined to produce it, and none of them was individually visible:

1. **Every `sync_*` step returned `None`.** A step that hands a row to the ETL
   and a step that hands over nothing are the same value. The failure that was
   actually happening — the handoff raising for every row, so 100% of rows were
   dropped — was therefore indistinguishable from "this shop has nothing to
   sync". It stayed invisible for the lifetime of the table.
2. **Watermarks advanced on fetch, not on persistence.** A step that fetched
   rows and persisted none still moved its cursor, so the next cycle started
   after the rows it had just lost. That is how the orders drifted.
3. **The cycle had no wall-clock bound, and the two budgets that did exist
   composed by addition.** `pagination_scope` bounded a single fetch (600s by
   default) and nothing bounded the cycle. Adding a cycle budget naively would
   not have fixed defect 3: an 1800s cycle can still *start* a 600s fetch at
   1799s, so the composed worst case is ~2400s — roughly the 40 minutes the
   incident actually lasted.

Two of the three fixes change interfaces that other code depends on, which is
why this decision is recorded rather than left in commit messages.

## Decision

**1. Every poll step returns a `SyncOutcome`, and emits exactly one
`poll_step_outcome` record on every exit path.**

`SyncOutcome(resource, shop_id, fetched, persisted, failed, pages, backfill,
skipped, error)`. The return type of `sync_orders`, `sync_products`,
`sync_returns`, `sync_inventory`, `sync_analytics` and `sync_creators` changes
from `None` to `SyncOutcome` — a **breaking** change to the polling module's
public API. `SyncWorkerFn` is typed `Callable[..., Awaitable[SyncOutcome]]`
concretely rather than left as `Awaitable[None]`, so mypy, not a reviewer, is
what catches a step regressing to a silent return.

The "on every exit path" clause is the load-bearing half. The record is emitted
from a context manager (`_StepRun.__exit__`), not from the happy path, because
the exits that mattered in the incident were the ones nobody had written a log
line for. A step that fetched rows and persisted none of them raises
`PollStepDroppedRowsError` carrying its outcome. **Watermarks advance only when
`persisted` is non-zero.**

`persisted` means *rows the ETL handoff accepted without raising*. It is **not**
a count of committed Postgres rows: `HandoffFn` is typed `-> None` and
`make_etl_handoff` discards `EtlConsumer.ingest`'s verdict, so a DLQ'd row counts
as accepted. Widening that is #1950's work in `services/ingestion/handoff.py`.
The narrower meaning still catches the failure that was occurring.

**2. `sync_inventory` raises where the other steps report.**

`sync_inventory` propagates `TikTokAPIError` and the non-dict-response
`ValueError` after reporting its outcome, rather than swallowing them and
returning. The other three search steps keep #1948's swallow-and-return for a
fetch error.

**3. The orchestrator publishes the cycle's remaining wall clock as the
enclosing `pagination_scope`, so the two budgets compose by `min`.**

`_CycleDeadline` bounds the cycle (`TIKTOK_POLL_CYCLE_BUDGET_SECONDS`, default
1800s). `_within_cycle_budget` opens `pagination_scope(budget_seconds=remaining)`
around each stage; `pagination_scope` resolves an inner budget to
`min(requested, enclosing)`. `_run_poll_step` gains a **required** keyword-only
`deadline: _CycleDeadline` with no default — also a breaking change.

The deadline is constructed by the *entrypoints*, not by `_poll`, because the
clock has to start before the credential resolve (DB work plus a possible token
refresh over HTTP) — work the beat slot is holding and the budget must therefore
cover.

## Rationale

**Why an outcome object rather than richer logging.** A log line is read by a
human who is already looking. The bar this work was held to is "the poll can be
relied on without someone watching it", so the verdict has to be a value the
*calling code* can branch on — which is what makes `fetched > 0 and
persisted == 0` able to raise, and what makes the watermark guard expressible at
all. Logging alone cannot stop a cursor from advancing over lost rows.

**Why `sync_inventory` raises and the others do not.** This is the one decision
where two merged branches disagreed, and the argument that settled it is
narrower than it first looked.

The case *against* raising was that inventory is step 4 of 4, so an exception
discards steps 1–3's watermarks and the next cycle refetches a larger delta
under the *incremental* 20-page cap, where over-running only warns. That was a
good argument and it is no longer true: `_poll` now saves partial `sync_state`
before re-raising **any** exception (`TestPartialStateSurvivesAMidCycleFailure`),
so a step-4 failure no longer discards steps 1–3.

The case *for* raising is #1948's: an inventory sync that drops every row must
not be indistinguishable from one with nothing to sync. An `ok=False` record is
loud inside the process, but the Celery task still exits zero.

The decisive point, and the one the review supplied, is that **raising is not a
new cost this change introduces.** On `origin/main` today `sync_inventory`
already raises, inventory is already step 4 of 4, `sync_analytics` already runs
after it, and `_poll` has no `try`/`except` at all. So the admitted cost —
analytics not running when inventory fails — is inherited, not created; and the
save-before-reraise makes the same failure **strictly cheaper** than `main`,
which discards steps 1–3's watermarks on it. Reverting to report-don't-raise
would be a regression against `main`, and turns four tests red (two of #1969's,
two of #1948's merged ones), verified by mutation.

The asymmetry with the other three steps is deliberate and sibling-respecting:
#1948 chose the swallow for orders/products/returns, and turning a fetch error
into a cycle failure across the board is #1950's structural work. Ordering
analytics ahead of inventory, or giving the cycle an end-of-cycle verdict so no
step can block another, is also #1950's.

**Why the budget must be published into the pagination scope rather than merely
existing.** A cycle budget that is only consulted *between* stages is defect 3
unfixed: the stage that starts at 1799s is not refused, and once it starts
nothing inside it knows the cycle is nearly over. Making the remaining cycle
budget the *enclosing scope* is what turns addition into `min`, because
`pagination_scope` already caps an inner scope by its enclosing one. The
composition is one line, and until #2009's review it was a mutation survivor —
deleting it left the entire 5,671-test unit suite green, because the nesting
behaviour was proven in isolation and the publication was proven nowhere.
`TestTheStageRunsUnderTheRemainingCycleBudget` now pins the seam.

**Why `deadline` is required rather than defaulted.** A default would let a
caller run a step under a fresh full-budget deadline, which is exactly the
"budget measures something narrower than it claims" failure the whole mechanism
exists to prevent. When a merged test needed the new argument it was given a
generous explicit deadline; the signature was not weakened to accommodate it.

**What the deadline honestly cannot do.** It bounds *scheduling*, not execution.
It can refuse a stage that has not begun and cancel one parked on a real
`await` (rate-limit backoff on a Redis TTL, DB I/O in the handoff). It cannot
interrupt a stage blocked inside a synchronous `requests` or redis-py call — the
thread is blocked, so `asyncio.wait_for`'s timer cannot fire. The residual worst
case after the budget is spent is one in-flight vendor request (15s socket
timeout) plus the current page's handoff loop. That limit is pinned by a
*passing* test (`TestDeadlineCannotInterruptBlockingVendorIo`) so it cannot be
quietly overclaimed later.

## Consequences

- **Breaking, in-tree:** any caller of a `sync_*` function now receives a
  `SyncOutcome`; any caller of `_run_poll_step` must supply a `deadline`. Both
  are module-internal or test-only today, and mypy catches every site.
- **Manual refresh changes behaviour (ADR-021).** `run_action_card_refresh`
  calls the cycle with no `try`/`except`, so an inventory failure now fails a
  manual refresh instead of quietly producing stale cards. That matches the
  fail-loud intent; `refresh.py` was not modified.
- **An inventory failure still costs the analytics step.** Accepted, inherited
  from `main`, routed to #1950.
- **The fields are inert where the poll actually runs (#1978).** Every value
  above travels in `logger.*(extra={...})`, rendered only by `JsonFormatter`,
  installed only by `configure_logging`, whose sole caller is `api/main.py`.
  `workers/celery_app.py` never calls it, so in the Celery beat process an
  operator sees `poll_step_outcome` with none of the numbers. Tests read
  `LogRecord` through `caplog` and structurally cannot see this. **#1969 must
  not be closed as "the poll is observable" until #1978 lands.**
- **`SyncOutcome.pages` is always 0 for inventory** by construction: Search
  Inventory is one POST per product-id batch and never walks a cursor, so
  nothing increments the scope's page counter. Documented in the module rather
  than papered over.
- **One loop on the poll path is still unbudgeted:** `sync_inventory`'s
  `range(0, len(product_ids), page_size)` batch loop is not a stage boundary and
  never enters `_paginate`. Harmless at Fujiwa's 116 products; at 30k it is
  ~1,000 sequential POSTs under a 10-request/60s limiter. Introduced by #1948,
  not addressed here.
