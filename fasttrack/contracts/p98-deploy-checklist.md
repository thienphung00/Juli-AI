# P98 deploy checklist (branch fasttrack/p98-combo)

One deploy for all of P98 (ADR-122): the stored source funnel, one funnel read model behind every Shopee
screen, the funnel engine and per-family option results, the minimal card and comparison table, Biên ở
giá bán / Biên cuối, the combo / KOL / ads builders, the accuracy checks (Ops "Lệch số liệu", prediction
coverage), Connector 0.3.14 and the drift-flag fix. Builds on production `4a772039`
(`fasttrack-deploy-20261109T0452Z`, Connector 0.3.13, head `125_reco_plan_groups`). Never write Fujiwa;
synthetic data only in the repo.

## 1. Migration (expand-only, reversible; `safe-alembic-upgrade.sh` dumps once before upgrading)

| Revision | Adds |
|---|---|
| `126_shopee_source_funnel` | `shopee_source_metrics_daily` (shop × day × source and product × day × source; RLS tenant-direct, `juli_app` SELECT / INSERT / UPDATE) |

The deferred tail `101_write_mode_backfill` now follows 126. Not run locally against Postgres (sandbox): the
deploy gate (`check.sh`) is the first run of the Postgres tests for 126, the funnel base and the cross-screen
test.

## 2. Environment / flags

No new variable. `CONNECTOR_FILL_LISTING` stays as it is (off unless the P97 fill-in step was done).

## 3. Beat / workers

No new beat entry. The source rows rebuild in the same `after_ingest` hook as the P97 metrics tables, followed
by `funnel_check` (logs `shopee_funnel_mismatch`, never corrects, never fails the ingest).

## 4. Deploy

1. `fasttrack/p98-combo` fast-forwards `fasttrack/optimize-product` (production head `4a772039` is its ancestor).
2. Push `fasttrack/optimize-product`, then one tag `fasttrack-deploy-<UTC>` on the full sha.
3. Watch `.github/workflows/fasttrack-deploy.yml`: plan, check, build, frontend, backend-unit, static, deploy.
   A red gate deploys nothing; fix on the branch and tag again.

## 5. After the deploy (owner)

1. **Backfill the metrics tables, including the new source rows** (VPS, the live release):
   ```bash
   ( set -a; . /etc/juli/api.env; set +a; cd /root/releases/current && PYTHONPATH=backend/src .venv/bin/python scripts/backfill_shopee_metrics.py --database-url "$DATABASE_DIRECT_URL" --all-shopee --dry-run )
   ```
   then the same without `--dry-run`. It prints the days rebuilt and the funnel mismatches found. Until a shop
   is backfilled, screens fall back to the old traffic numbers with a note.
2. **Reload Juli Connector 0.3.14** on ORY's Chrome: build `apps/connector` (`pnpm run build`), copy `dist/`
   over the folder chrome://extensions shows as "Loaded from", press Reload (never Remove — it drops the
   pairing). Next run: the stale "tạm dừng" lines clear; if the orders reader still fails, its reason is now in
   `lastRun.outcomes` (service-worker console) and the page-1 orders still post.
3. **Check in Ops › Shopee › Lệch số liệu** for ORY (last 14 days): an empty list, or mismatches to explain.
4. **Spot-check the numbers once** on ORY: Tổng quan, Phân tích, Sản phẩm and a builder "before" show the same
   Lượt xem, CTR, CTOR, Đơn, AOV, GMV and Lợi nhuận for the same window (ADR-122 d.2, d.14).

## 6. What changes for the seller

- Every option card: Δ Lợi nhuận (money · %, range, build-up), Δ GMV, Δ Đơn, Tác động %, Chi phí + hoà vốn,
  Sau N ngày; the comparison table ranks per 30 days. A voucher can now move orders (CTOR); a title moves CTR.
- One Lợi nhuận on every screen (ShopMetrics, scaled to shop totals, tagged "ước tính theo tỉ lệ"); CTOR =
  đơn (theo Tổng quan) ÷ lượt nhấp.
- Two margins per variation: Biên ở giá bán (chắc chắn) and Biên cuối (ước tính); no 1/3 giá vốn fallback.
- Ads and Affiliate show cost and break-even only until ORY's own history measures them.
- The ads-edit options are hidden from the builder.

## 7. Rollback

Plan, then roll back to `4a772039` per fasttrack/README "Rolling back": `fasttrack-rollback-plan-<UTC>` then
`fasttrack-rollback-<UTC>-to-4a772039…`. Rollback never touches the database: `shopee_source_metrics_daily`
stays (expand-only) and the old code does not read it. Connector: reload 0.3.13 from the previous build.
