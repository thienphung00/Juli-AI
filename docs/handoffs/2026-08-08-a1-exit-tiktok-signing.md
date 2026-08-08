# A1 exit — restore complete, TikTok fetch newly unblocked, 500 on page 2

**Date:** 2026-08-08
**Status:** one error away from the A1 exit gate. Gold is 3/5 and stale since 2026-08-06 05:37.

## Read this first

The Demo has been serving KPIs computed on **2026-08-06 05:37** ever since. They look healthy
(`gmv_tiktok 172945097.0`, `aov 209884.83`, `cancellation_rate 0.176`) — they are simply two days
old. `ctor` and `live_hours` are `unavailable`.

The blocker is **not** the KPI code and **not** the data. Both are in place. The hourly reconcile
aborts in its bronze stage on a TikTok fetch error, before silver and gold recompute.

## Where it stands right now

Last manual run on release `18c337d7`:

```
requests.exceptions.HTTPError: 500 Server Error
  .../order/202309/orders/search?...&page_size=50&page_token=aDV5MHJHR1JaRWhQUzJKUDl5U0li...&sign=...
```

**The `page_token` in that URL is the important detail** — TikTok only issues one in a successful
response, so page 1 fetched fine and the failure is on a subsequent page. The previous
`401 / code 106001 invalid sign` is gone.

### Immediate next step

Get the 500's response body. `_handle_response` calls `raise_for_status()` before reading it, so
every error discards TikTok's explanation — that is why the earlier 401 took two days to identify.

```bash
cd ~/releases/current && set -a; . /etc/juli/api.env; set +a
PYTHONPATH=backend/src ./.venv/bin/python -c "
import requests
from juli_backend.workers.tasks.mock_analytics_reconcile import mock_analytics_hourly_reconcile
try:
    mock_analytics_hourly_reconcile()
except requests.exceptions.HTTPError as e:
    print('STATUS:', e.response.status_code); print('BODY  :', e.response.text[:800])
"
```

Two candidates, and the body separates them:

1. **Transient TikTok 500.** Run it twice before investigating.
2. **Page-2 request malformed.** `page_token` is a query parameter. If it is added to
   `query_params` after `_build_params` computes the signed set, page 2 is signed over a
   different parameter set than page 1 — invisible on page 1, which has no `page_token`. That
   would be the same class of bug as the one just fixed, one layer along. Start at
   `integrations/tiktok/client.py::get_all_pages` (~line 278).

## The chain of root causes, in order found

Each of these looked like the answer and each was wrong until the last. Worth reading so you do
not re-tread it.

1. **The 2026-07-30 production wipe.** Migration tests ran `alembic downgrade base` against prod
   (#734), destroying `analytics_performance_intervals` (6,662 rows), `analytics_backfill_partitions`
   (512), `tiktok_credentials` (2) and two `shops` rows. **Recovered** — see below.
2. **Pooler exhaustion (#813).** Worker tasks created an engine per invocation and never disposed
   it. Real, fixed by #815. Blocked deploys. **Not** the cause of the stale KPIs.
3. **Beat not dispatching.** The hourly task never appears in the worker log at all. Still
   unexplained — see Open threads.
4. **Token freshness.** `_refresh_credential` skips the refresh whenever the stored
   `token_expires_at` is in the future, so a server-rotated token is never re-fetched. Real
   fragility, **not** the cause: forcing a refresh produced a valid new token that still 401'd.
5. **The actual cause — signed body ≠ sent body (#855, merged).** `post()`/`put()` signed
   `json.dumps(body, separators=(",",":"), sort_keys=True)` then passed `json=body` to requests,
   which re-serializes with its own separators and key order. TikTok recomputes the signature over
   what it received; the two never matched.

   **Why it surfaced only on 2026-08-06.** `json.dumps({})` is `"{}"` under both settings, so empty
   bodies hid it. The first orders sync had no `sync_state`, therefore no `update_time_from`,
   therefore an empty body — it succeeded, fetched 20 pages, and *wrote sync_state*. Every run
   since sent a non-empty body and failed. **A latent bug armed by its own first success**, which
   is why it presented as an external change with nothing on our side having changed.

   **Why 23 signature tests missed it.** The test helper reconstructed the body from the `json=`
   kwarg and re-derived the signed string exactly as the client did — asserting the client's
   intent against itself rather than observing the wire. Both sides shared the wrong assumption.

## What is already done

**Restored (verified):** 6,662 `analytics_performance_intervals` rows and 512
`ops.analytics_backfill_partitions` checkpoints, from
`/root/backups/juli-pre-migrate-20260730T061519Z.dump` via
`infra/scripts/restore-analytics-history.sh`. Grain distribution confirmed: product 4,424 /
live 1,982 / shop 128 / catalog_daily 128, range 2026-03-16..2026-07-21, all scoped to
`2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f` which equals `DEMO_REFERENCE_SHOP_ID`.

**Merged and deployed:** #789 (ctor/live_hours wired to `analytics_performance_intervals`),
#790 (per-stage commits, batched silver upserts, 201→3 queries per 50 rows), #791 (backfill
speed + scheduled top-up), #804, #809, #811, #812, #815, #816, #818, #819, #855.

**Still open:** #850 (register `analytics_backfill_topup` — its beat entry currently dispatches to
an unregistered task), #852 (beat schedule file lives in a pruned release directory).

## Open threads

- **#813** — pooler exhaustion. #815 deployed; unconfirmed whether it holds under load. Watch
  `SELECT count(*), state FROM pg_stat_activity GROUP BY state;`
- **Beat not dispatching the hourly task.** Ruled out: schedule config, task registration, queue
  routing, module imports, and (by a malformed test I later retracted) crontab due-computation.
  The worker log shows the task name *never appears*, in any form. #852 is a candidate but
  unproven. Get `journalctl -u juli-celery-beat --since "<HH>:59" --until "<HH>:02"`.
- **#853** — nothing alarms on gold staleness. A 50-hour outage produced no signal because the
  endpoint returns 200 with plausible values.
- **Design gap, unfiled.** `ctor` and `live_hours` are computable entirely from restored *local*
  rows, yet a failed upstream fetch aborts the job before gold recomputes. Making the gold stage
  resilient to bronze failure would have let A1 exit days ago.
- **Unfiled.** `_handle_response` discarding response bodies. Fixing it is the single highest-value
  change for future diagnosis.

## The exit gate

```bash
psql "$PGURL" -c "SELECT k.key, k.value->>'availability', k.value->>'value'
                  FROM gold.kpi_envelopes e, jsonb_each(e.payload->'kpis') k ORDER BY 1;"
```

Five rows all `available` = A1 exits (#601), which unblocks #599. Check magnitudes, not just
non-null: `live_hours` should sum 128 shop-grain rows, `ctor` should be a GMV-weighted
`click_order_rate` over 4,424 product-grain rows.

## Traps that cost time here

- **Pin PYTHONPATH.** Backend pytest in any worktree imports `juli_backend` from the *main*
  checkout via an editable `.pth`. Unpinned greens are fake.
- **`ruff` needs `--config backend/pyproject.toml`.** The bare command reports different results;
  it sent me chasing phantom format drift.
- **Never grep logs for success markers.** `shared_compute_job_started|succeeded in` cannot see a
  task that raises before it logs. Three investigations missed a 50-hour outage that way. Check
  the artifact's own `computed_at`, then grep `ERROR|Traceback|raised`.
- **Mutation-test every guard you rely on.** Used on the stale-write guard, KPI grain filter,
  masking allowlist, factory cache and signed-body fix; each time it confirmed the test was
  load-bearing rather than decorative.
- **Locally-merged waves skip `lint` and `typecheck`.** They run at issue tier only, so assembling
  a wave by local merges ships type errors to production. #809 closes this at the wave end.
- **Read the response body before raising.** The server was explaining itself the entire time.
