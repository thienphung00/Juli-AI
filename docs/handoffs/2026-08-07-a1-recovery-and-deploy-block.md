# A1 recovery — medallion KPIs, reconcile perf, and the deploy block

**Date:** 2026-08-07
**Status:** three fixes merged, **none deployed**. Production still serves 3 of 5 Demo KPIs.

## The one-paragraph version

The medallion pipeline was empty because migration tests wiped production on 2026-07-30. The
data is recoverable from a dump. Three issues fixed the code side (#789 KPIs, #790 reconcile
performance, #791 backfill automation) and all merged — but every Release run since has failed,
so none of it is live. The current blocker is Supabase pooler exhaustion (#813), with a likely
fix open as PR #815.

## What was actually wrong

### The wipe (root cause of the empty pipeline)

Between 06:15 and 08:47 UTC on 2026-07-30, production lost:

| table | before | after |
|---|---|---|
| `analytics_performance_intervals` | 6,662 | 0 |
| `analytics_backfill_partitions` | 512 | 0 |
| `tiktok_credentials` | 2 | 0 |
| `shops` | 3 | 1 |

No migration drops these in `upgrade()` — every `drop_table` in `020`–`025` is in `downgrade()`.
Schemas survived intact with zero rows and `shops` was reseeded to a fixture: the signature of
`alembic downgrade base` + upgrade against production, i.e. **#734**, which was not found until
2026-08-06. Two fingerprints remain visible: a `shops` row named "Migration Test Shop"
(`754b83ac-…`) and a migration-test fixture row in `silver.orders`.

**#734 was not a latent risk. It already fired.**

### Recovery source

`/root/backups/juli-pre-migrate-20260730T061519Z.dump` is the **only** surviving copy — every
later dump has zero rows, and it sits in a directory subject to `BACKUP_RETENTION_DAYS`.

Contents, all scoped to `2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f`, which equals the current
`DEMO_REFERENCE_SHOP_ID` (so no remap needed):

| grain | rows | carries |
|---|---|---|
| `product` | 4,424 | `click_order_rate` on all — CTOR's source |
| `live` | 1,982 | per-session rows |
| `shop` | 128 | `live_hours` on all — LIVE hours' source |
| `catalog_daily` | 128 | |

Range `2026-03-16 .. 2026-07-21`.

To audit a dump without a database:
`pg_restore --data-only --table=<t> -f - <dump>` and count COPY lines.

## Merged (not deployed)

| issue | what | notes |
|---|---|---|
| #789 | wire `ctor` / `live_hours` to `analytics_performance_intervals` | inert until the restore runs — the table is empty |
| #790 | per-stage commits + batched silver upserts | 2244.9s → bounded; 201 queries → 3 for 50 rows |
| #791 | bulk-load completions, race-safe budget, scheduled top-up | |
| #804 | mypy errors blocking the release build | |

## Open PRs

| PR | What | Priority |
|---|---|---|
| **#815** | one session factory per worker process | **highest — likely unblocks deploys** |
| #812 | guarded restore script + 15 contract tests | run after a deploy succeeds |
| #811 | KPI grain-filter and masking pins | tests only |
| #809 | run lint + typecheck at wave tier | |

All four verified to compose cleanly in any order: `mypy` clean across 298 files, 1960 tests
passing with all four merged together.

## Open issues

- **#813** — deploys blocked, Supabase pooler exhausted. #815 is a partial fix; the diagnosis
  needs `SELECT count(*), state FROM pg_stat_activity GROUP BY state;` and a worker restart to
  confirm.
- **#795** — real concurrency in the analytics backfill, carried out of #791.
- Six duplicates to close: **777, 779, 780, 786, 787, 788** (filed twice; work lives on 789/790/791).

## Defects that shipped and what let them through

Every issue was reported complete-and-passing by its executor while carrying a real defect. The
pattern is worth internalising more than the individual bugs:

1. **A dropped invariant.** #790's batch rewrite lost the stale-write guard inside
   `OrderRepo.upsert` (`repos.py:387-393`). Reproduced: an order's `total_amount` went 100 → 50
   with `update_time` regressing 9 hours. Guards *inside* a replaced function are invisible at
   the call site, and perf tests measure queries, not invariants.
2. **A stub that fabricated success.** #791's `auto_topup` marked every partition complete while
   making zero Partner calls — it would have poisoned `ops.analytics_backfill_partitions` so all
   future backfills skipped the range permanently.
3. **A call that could never succeed.** The same dispatcher used
   `session.get(TikTokCredential, shop_id)` when the primary key is `id`, and read
   `app_key`/`app_secret`, which are not columns.
4. **Contract breaks invisible to pytest.** It also called `backfill_product_partition` and
   `run_catalog_partition` with keywords they do not accept — the product and catalog buckets
   would have raised `TypeError` on every run. The test faked all four runners with `**kwargs`,
   which proves routing but not that the real call would work.

**Why 3 and 4 reached production:** `pr.yml` runs `lint` and `typecheck` only at issue tier, or
main-not-via-wave. These waves were assembled by merging issue branches **locally**, so neither
ever ran. The gate was correct; the path around it was not. #809 closes that.

## Verification discipline that worked

- Run the **full** suite from the coordinator, not the executor's chosen subset — that caught
  every one of the above.
- **Mutation-test** any guard you rely on. Used on the stale-write guard, the KPI grain filter,
  the masking allowlist, and the factory cache; each time it confirmed the test was load-bearing
  rather than decorative.
- Pin `PYTHONPATH` to the worktree. Backend pytest otherwise imports `juli_backend` from the main
  checkout via an editable `.pth`, and greens are fake.
- `ruff` needs `--config backend/pyproject.toml`. The bare command reports different results.

## Next steps

1. Merge **#815**, then confirm the Release reaches the VPS.
2. Preserve the dump before rotation: `cp -p /root/backups/juli-pre-migrate-20260730T061519Z.dump /root/backups-hold/`.
3. Merge **#812** and run `restore-analytics-history.sh --dry-run`, then for real.
4. Wait for the top of the hour, then confirm all five KPIs:
   ```sql
   SELECT k.key, k.value->>'availability', k.value->>'value'
   FROM gold.kpi_envelopes e, jsonb_each(e.payload->'kpis') k ORDER BY 1;
   ```
   Expect five rows, all `available`. That is A1's exit condition.

## Caveat worth carrying

`gmv_tiktok` is computed over silver orders bounded by #744's 20-page cap, so it reflects the
most recent 1000 orders rather than a period total, while `live_hours` sums 128 days of history.
Two KPIs in one envelope with different implicit windows. Documented in code, flagged as
non-blocking by review, but unresolved as a product question.
