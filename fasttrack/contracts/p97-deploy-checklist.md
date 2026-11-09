# P97 deploy checklist (branch fasttrack/p97-shopee-data)

One deploy for all of P97: T1 Connector readers (0.3.11), T2 metrics layer + plan math, T3 fill on approval
(0.3.12), T4 builder (picker, many targets, groups, combo tiers, listing combo, ads levers), T5 combo fill
(0.3.13). Builds on production `86c6f673` (`fasttrack-deploy-20261108T0708Z`, Connector 0.3.10, head
`121_shop_members`). Owner approved the deploy on 2026-11-09. Never write Fujiwa; synthetic data only in the repo.

## 1. Migrations (expand-only, reversible; `safe-alembic-upgrade.sh` dumps once before upgrading)

| Revision | Adds |
|---|---|
| `122_shopee_affiliate_lines` | Connector affiliate conversion lines (KOL tab without the order export) |
| `123_shopee_metrics_tables` | `shopee_shop_metrics_daily`, `shopee_product_metrics_daily`, `shopee_plan_base_snapshots` |
| `124_shopee_fill_jobs` | fill-job queue (one job per approved target) |
| `125_reco_plan_groups` | plan groups (Nhóm A/B…) and their members |

All tenant-direct with RLS and `juli_app` SELECT / INSERT / UPDATE. The deferred tail `101_write_mode_backfill`
now follows 125. Not verified locally against Postgres (sandbox): the deploy gate (`check.sh`) is the first run
of the Postgres integration and RLS / grant tests for 122–125.

## 2. Environment / flags

| Name | Where | Default | Purpose |
|---|---|---|---|
| `CONNECTOR_FILL_LISTING` | API environment | **off** | Kill switch for all fill-in. Off: approvals queue nothing, `GET /v1/ingest/fill-jobs` serves nothing. Turn on only after section 5 step 3. |

No other new variable. Existing: `JULI_ORDER_REF_MASTER_KEY` (order / affiliate hashing), `CONNECTOR_MARKET_*`.

## 3. Beat / workers

No new beat entry. Metrics tables rebuild after each ingest write (`after_ingest` hook); a failed rebuild is
logged (`shopee_metrics_rebuild_failed`) and never fails the ingest.

## 4. Deploy

1. `fasttrack/p97-shopee-data` fast-forwards `fasttrack/optimize-product` (production head is its ancestor).
2. Push `fasttrack/optimize-product`, then `git tag fasttrack-deploy-<UTC> <full-sha> && git push origin <tag>`.
3. Watch `.github/workflows/fasttrack-deploy.yml`: plan, check, build, frontend, backend-unit, static, deploy.
   A red gate deploys nothing; fix on the branch and tag again.

## 5. After the deploy (owner)

1. Backfill the metrics tables (VPS, API environment):
   `python scripts/backfill_shopee_metrics.py --database-url "$DATABASE_DIRECT_URL" --all-shopee --dry-run`, then
   without `--dry-run`. Until a shop is backfilled, screens read the raw tables as before.
2. Reload Juli Connector 0.3.13 on ORY's Chrome (`apps/connector/dist`, chrome://extensions → Reload). Next day,
   check in Ops: shop totals, product period, order lines, per-order income, ads per product, KOL lines posted;
   no `system_connector_stop` event in the Ops audit log. Any `TODO(first capture)` mapper that reports drift is
   a recon fix, not a data error.
3. Fill-in, watched: set `CONNECTOR_FILL_LISTING=1`, approve one voucher card on ORY, open the job from the
   execution checklist, check every field, press Xác nhận yourself, then check the captured voucher id. Then one
   ads budget / ROAS edit, one affiliate commission bulk edit, one combo. Set the flag back to off if any field
   lands wrong.
4. Daily request budget 400 / shop; a CAPTCHA, login wall, password prompt, 403 or 429 stops every reader for 72 h
   and posts a connector event.

## 6. Rollback

Plan, then roll back to the previous deploy (`86c6f673`), per fasttrack/README "Rolling back" and
`docs/runbooks/rollback-runbook.md`:
`git tag fasttrack-rollback-plan-<UTC> origin/fasttrack/optimize-product && git push origin <tag>`, then
`git tag fasttrack-rollback-<UTC>-to-86c6f673… origin/fasttrack/optimize-product && git push origin <tag>`.
Rollback never touches the database: the new tables stay (expand-only) and the old code does not read them.
Connector: reload 0.3.10 from the previous build.
