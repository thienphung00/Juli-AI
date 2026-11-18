# T5 maintenance window: migration 134 (canonical tables)

Owner decision 2026-11-18. Migration `134_canonical_tables` renames the seven Shopee fact tables,
renames columns, converts the time columns to `timestamptz` and fills data. The additive-only gate
in `infra/scripts/deploy.sh` (`infra/scripts/migration_additive_gate.py`) refuses it by design. So
the owner applies 134 by hand on the VPS in a short window, and the deploy tag runs afterwards with
nothing pending. The gate then inspects no revision and passes.

**Forward fix only.** After 134 is applied, the old code and the new schema do not match: the old
code uses old column names and naive order times, and `day` is NOT NULL. A code rollback
(`docs/runbooks/rollback-runbook.md`) would therefore run broken code. If something is wrong, fix
it forward with a new commit and a new tag. The migration's downgrade exists for tests and a
supervised emergency, never as part of a rollback.

## Before the window

- Prod is at `135_connector_multi_computer`: batch 1118e (PR #2328, Connector on several
  computers) is deployed and its additive migration 135 applied. 134 revises 135 (chain
  `133 -> 135 -> 134`), so the window applies exactly one revision. If prod is still at 133,
  do not run the window: deploy the 1118e tag first (135 is additive and passes the gate).
- The batch that carries 134 is merged into `fasttrack/optimize-product`, and
  `fasttrack/gate_status.py` prints VALID for its merge sha (the GitHub gate, including the
  Postgres `check` shards, ran `tests/integration/test_t5_canonical_tables_db.py`).
- No other session holds a deploy (`fasttrack/state.py check`).
- The pre-migrate dump of `safe-alembic-upgrade.sh` costs about 210 MB of Supabase egress.

## Steps (VPS, as root)

1. Pause the workers. They write the canonical tables (metrics rebuild, stock alert).

   ```bash
   systemctl stop juli-celery-beat.service juli-celery-worker.service
   systemctl is-active juli-celery-beat.service juli-celery-worker.service
   ```

   Expect `inactive` twice. You cannot pause the Connector from the server. Its posts fail with
   5xx during the window, and it queues 5xx posts and retries them later
   (`apps/connector/src/platforms/shopee/background/connector.ts`). No data is lost.

2. Put the canonical clone on the merged code. `deploy.sh` checks the same clone out at the tag's
   sha anyway.

   ```bash
   git -C /root/Juli-AI-v2 fetch origin fasttrack/optimize-product
   git -C /root/Juli-AI-v2 checkout --detach FETCH_HEAD
   git -C /root/Juli-AI-v2 log -1 --format='%H %s'
   ls /root/Juli-AI-v2/backend/src/juli_backend/database/migrations/versions/134_canonical_tables.py
   ```

   The sha printed must be the one `gate_status.py` called VALID.

3. Load the environment and check the current revision is 135 and the code's head is 134.

   ```bash
   set -a; . /etc/juli/api.env; set +a
   PYTHONPATH=/root/Juli-AI-v2/infra/scripts:/root/Juli-AI-v2/backend/src /root/releases/current/.venv/bin/python /root/Juli-AI-v2/infra/scripts/safe_alembic_helpers.py current-revision
   PYTHONPATH=/root/Juli-AI-v2/infra/scripts:/root/Juli-AI-v2/backend/src /root/releases/current/.venv/bin/python /root/Juli-AI-v2/infra/scripts/safe_alembic_helpers.py head-revision --alembic-ini /root/Juli-AI-v2/alembic.ini
   ```

   Expect `135_connector_multi_computer`, then `134_canonical_tables`. Stop if either differs:
   `133_fleet_draws_real_shops` means 1118e is not deployed (deploy it first, then restart the
   window from step 1); anything else means the chain moved and the batch needs a re-chain.

4. Count the rows before.

   ```bash
   psql "$DATABASE_DIRECT_URL" -At -c "SELECT 'order_lines', count(*) FROM public.shopee_order_lines UNION ALL SELECT 'order_settlements', count(*) FROM public.shopee_order_income UNION ALL SELECT 'affiliate_lines', count(*) FROM public.shopee_affiliate_lines UNION ALL SELECT 'shop_metrics_daily', count(*) FROM public.shopee_shop_metrics_daily UNION ALL SELECT 'product_metrics_daily', count(*) FROM public.shopee_product_metrics_daily UNION ALL SELECT 'source_metrics_daily', count(*) FROM public.shopee_source_metrics_daily UNION ALL SELECT 'stock_history', count(*) FROM public.shopee_stock_history" | tee /root/t5-counts-before.txt
   ```

5. Upgrade. This takes the pre-migrate dump, applies 134 in one transaction (seconds for a small
   table) and compares the row counts.

   ```bash
   RELEASE_DIR=/root/Juli-AI-v2 VENV_PYTHON=/root/releases/current/.venv/bin/python ALEMBIC_BIN=/root/releases/current/.venv/bin/alembic PYTHONPATH=/root/Juli-AI-v2/backend/src API_ENV_FILE=/etc/juli/api.env /root/Juli-AI-v2/infra/scripts/safe-alembic-upgrade.sh
   ```

   It must end with `safe-alembic-upgrade complete`. It runs the new migration code with the
   current release's interpreter; the T5 batch adds no Python dependency.

6. Check that the head is 134 and the rows are all there.

   ```bash
   PYTHONPATH=/root/Juli-AI-v2/infra/scripts:/root/Juli-AI-v2/backend/src /root/releases/current/.venv/bin/python /root/Juli-AI-v2/infra/scripts/safe_alembic_helpers.py current-revision
   psql "$DATABASE_DIRECT_URL" -At -c "SELECT 'order_lines', count(*) FROM public.order_lines UNION ALL SELECT 'order_settlements', count(*) FROM public.order_settlements UNION ALL SELECT 'affiliate_lines', count(*) FROM public.affiliate_lines UNION ALL SELECT 'shop_metrics_daily', count(*) FROM public.shop_metrics_daily UNION ALL SELECT 'product_metrics_daily', count(*) FROM public.product_metrics_daily UNION ALL SELECT 'source_metrics_daily', count(*) FROM public.source_metrics_daily UNION ALL SELECT 'stock_history', count(*) FROM public.stock_history" | tee /root/t5-counts-after.txt
   diff /root/t5-counts-before.txt /root/t5-counts-after.txt && echo "row counts equal"
   psql "$DATABASE_DIRECT_URL" -At -c "SELECT relname, relkind FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relname IN ('order_lines', 'shopee_order_lines', 'stock_history', 'shopee_stock_history') ORDER BY relname"
   psql "$DATABASE_DIRECT_URL" -At -c "SELECT count(*) FILTER (WHERE day <> (ordered_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date), count(*) FILTER (WHERE status NOT IN ('pending', 'confirmed', 'in_transit', 'delivered', 'cancelled', 'refunded_accepted', 'refunded_not_received', 'returned', 'on_hold')) FROM public.order_lines"
   ```

   Expect `134_canonical_tables`, then "row counts equal". The new names must show `r` and the
   old names `v`, and the last query must return `0|0`.

7. Tag the sha from step 2, from the owner's Mac, with the `deploy` skill's tag step. The skill
   prints the exact `fasttrack/bin/tag-deploy.sh` command for the batch worktree. Watch the run
   with `fasttrack/bin/deploy_watch.py`. In the deploy log, the additive gate must report
   `pending revisions inspected: (none)` and ACCEPTED.

8. Unpause the workers once the deploy is green. The deploy syncs the two units, so this is
   idempotent.

   ```bash
   systemctl start juli-celery-worker.service juli-celery-beat.service
   systemctl is-active juli-celery-worker.service juli-celery-beat.service
   ```

   Expect `active` twice. Then run the LIVE check of the acceptance table: on the sample shop and
   one real shop, compare dashboard GMV, đơn, AOV, ads, profit and both margins with a read-only
   query on the new tables, and check they equal the values from before the window.

## The old API during the window (between step 5 and the deploy)

The old code keeps serving. After 134 it reaches the canonical tables only through the
`security_invoker` views under the old names. Those views show the NEW column names and aware
times, so on the Shopee screens and ingest endpoints that touch the seven tables:

- reads of `shopee_subsidy`, `ship_shopee_subsidy`, affiliate `model_id` / `order_status` and stock
  `model_id` fail with 5xx;
- order-line and affiliate writes fail (`day` is NOT NULL and the old code does not set it). The
  Connector retries them after the deploy;
- the rest of the app (TikTok, auth, Ops pages that do not read these tables) is unaffected,
  including the 1118e fill-job leases and per-computer Connector state (135's tables are not
  renamed).

Keep the gap between step 5 and step 7 short: tag right after step 6.

## If step 5 fails

`safe-alembic-upgrade.sh` stops before or inside the migration's single transaction, so the
database stays at 135. Restart the workers (step 8 without the tag), leave the clone where it is,
and report the output. Do not tag.
