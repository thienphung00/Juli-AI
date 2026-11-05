# P92 deploy checklist (branch fasttrack/p92-builder)

One deploy for all of P92 (B-1 to B-10) together with the product-page hotfix (`fasttrack/p91-hotfix`).
Never pushed, tagged or merged into another branch by the integration agent. The owner runs the deploy.
Never write Fujiwa (shop 2b1da87b...). Synthetic data only in the repo and its tests; client files stay outside it.

Builds on P91 (`p91-deploy-checklist.md`, deployed as `fasttrack-deploy-20261104T1301Z`); production is at
`120_planned_changes`. Gate counts of this integration are in the LOG entry "P92 ready to deploy".

## 1. Migrations

**None.** Alembic head stays `120_planned_changes` (verified: empty -> head, head -> -1 -> head). The market
tables the new Connector reader fills (`market_listing_snapshots`, `market_keyword_snapshots`) came with
`108_shopee_ops_data`; the exclusions are `shop_rules` rows (`excluded`, `exclude_reason`); the fee backtest and the
plan steps read only. `infra/safe-alembic-upgrade.sh` finds nothing pending and takes no dump.

## 2. New environment variables / flags

| Name | Where | Default | Purpose |
|---|---|---|---|
| `SHOPEE_BUILDER_LLM` | API environment (AWS secret `juli/api/production`) | **on** (unset = on; `0` / `false` / `no` / `off` = off) | The builder's text drafts (Tiêu đề, Ảnh bìa, Mô tả). Needs `OPENAI_API_KEY` and the shop's `llm_processing` consent as before; without them the drafts say "LLM tắt" and the manual edit still works. Set `0` to stop all drafts. |
| `CONNECTOR_MARKET_SEARCH` | API environment | **off in code** (unset = off) | Server switch of the Connector's public search reader. Off: `GET /v1/ingest/market/keywords` answers an empty list and `POST /v1/ingest/shopee/market_search` refuses. **The owner turns it on after the deploy and after the connector reload** (section 5 step 3). |
| `CONNECTOR_MARKET_SHOP_IDS` | API environment | empty | Comma-separated Juli shop ids allowed to post market captures; empty = any shop once the switch is on. Set it to the ORY shop id (the Connector is ORY-pilot only anyway). |
| `NEXT_PUBLIC_P92_BUILDER` | demo web build | on (anything but `0`) | The P92 builder (all kinds, compare of 4). `0` brings back the P91 builder. |

Existing, still needed: `JULI_ORDER_REF_MASTER_KEY`, `CONNECTOR_FILL_LISTING` (P91, unchanged).

To change a server variable: edit the AWS secret, run `fetch-secrets.sh` / `refresh-secrets.sh` on the VPS, restart the API.

## 3. Beat entries

None new. The market reader is driven by the Connector's own alarm (weekly per keyword, max 12 keywords per run).

## 4. New routes (summary)

- Seller (Demo, `/v1/demo/shopee`): `builder/*` (picker, variations, evaluate / compare / choose, drafts, keywords table,
  ads campaigns, co-purchase), exclusions (`/exclusions`), the four Ops pages (`/keywords`, `/dashboard/{products,flows,ads,promotions}`,
  `/orders`), `products/{item}/market-price` and `builder/products/{item}/market-range` (**seller body = median and
  average only**: no listings, shop names, titles or P25-P75), draft plan steps.
- Ops (`/v1/ops/shops/{id}/shopee`): the same builder / exclusions / pages, the **full** market block (5 closest listings, P25-P75),
  `GET .../shopee/fee-backtest?days=90` (formula fees vs Income actuals; Xem+).
- Connector (ingest token): `GET /v1/ingest/market/keywords`, `POST /v1/ingest/shopee/market_search` (switch-gated).
- The Sản phẩm + luồng funnel (`.../dashboard/products`, Ops `.../shopee/products`) now carries per product `price_min`,
  `price_max`, `list_price`, `price_basis`, `margin_pct`, `margin_basis`.

## 5. Post-deploy steps (in this order)

1. **Smoke**: `GET /health`; Ops opens ORY; Tổng quan loads; **a product page opens without a crash** (Sản phẩm >
   any product; this was the hotfix: version shape, partial-period GMV). On Sản phẩm the GMV basis reads
   `order_lines` (no Shopee product file for the window) or `shopee_product_period`.
2. **Builder check (Quyết định > Tự tạo phương án)**: pick a product, Voucher: enter **5.000 / 100.000** and **10.000 /
   100.000** as two versions (typed numbers, no sliders) and compare side by side; both show orders that would have qualified,
   cost at expected usage, Δ GMV / Δ orders / Δ profit and margin after. Then a Giảm giá version: the price marker
   shows (or says why there is no market price yet). Choose one version: a manual card with a JC code appears.
3. **Connector 0.3.5 reload**: `cd apps/connector && pnpm install --frozen-lockfile && node scripts/build.mjs` (Node 20) ->
   `apps/connector/dist` (manifest 0.3.5; new host permission `https://shopee.vn/*`). On the ORY operator's Chrome:
   `chrome://extensions` -> reload the unpacked extension (Chrome asks to accept the new permission).
   **First-capture verification** (the reader is built from recon, not from a real answer): follow the "First live run
   checklist" in `docs/integrations/shopee/market-search-recon.md` (search-items call path and fields, price unit,
   which of `sold` / `historical_sold` is "Đã bán", ad marker, `shop_name` present, anti-bot on a background tab).
   Only then set `CONNECTOR_MARKET_SEARCH=1` and `CONNECTOR_MARKET_SHOP_IDS=<ORY id>`, restart the API, let one run post, and check
   Ops > ORY > Sản phẩm > a product with a main keyword shows "Giá thị trường" (median, P25-P75, closest listings) and the
   **seller** page shows only median / average / number of similar listings. A schema drift pauses the dataset and
   posts nothing: fix the constants in `src/shopee/market.ts` and rebuild. No keyword = "chưa có từ khoá chính".
4. **Demo pages**: sign in as the seller (demo.app-juli.com): Từ khóa, Quảng cáo + khuyến mãi, Đơn hàng, Sản phẩm + luồng open
   read-only with the same numbers as Ops (order keys are hashes; no buyer data); the Sản phẩm + luồng table shows giá
   (list struck) and biên with its basis per product.
5. **Exclusions**: Cài đặt > Loại trừ sản phẩm: add a listing with a reason; it leaves cards, product rows, the builder, Phân tích
   flags and Phân tích > KOL; Tổng quan keeps the sales and shows "trong đó Xđ từ sản phẩm đã loại trừ". Undo it.
6. **Fee backtest value**: as Ops open `GET /v1/ops/shops/<ORY>/shopee/fee-backtest?days=90`
   after the Income files are loaded: the mean absolute gap between formula fees and actual fees per order must be
   **<= 1 % of buyer-paid**. Record the figure in LOG. A larger gap does not block the deploy; it means the fee formula
   (and every strategy margin) needs recalibration before the owner trusts the numbers.
7. Optional: set the daily marketing cap in Cài đặt > Mục tiêu (the builder's ads cap, B-7.6) and fill the "loại trừ" / "lý do" columns of the
   Thông số shop file.

## 6. Rollback

- Backend: redeploy the previous release; there is no migration to undo. Exclusions already saved are ordinary `shop_rules`
  rows that old code ignores.
- Web: build with `NEXT_PUBLIC_P92_BUILDER=0` for the P91 builder; the other P92 screens are additive.
- Connector: set `CONNECTOR_MARKET_SEARCH` off (stops posts and the keyword list server side at once), or remove / disable the
  extension, or ship a build without the market reader; 0.3.4 behaves as before.
- Text drafts: `SHOPEE_BUILDER_LLM=0`.

## 7. Known limits

- The market reader has no real capture yet (recon only); until step 5.3 passes, "Giá thị trường" says "chưa thu thập".
- **Seller sees only median and average of similar products** (owner 2026-11-05); listings and shop names are Ops-only.
- The public market tables are Ops-only for the runtime role (migration 108); the seller routes read them through a short
  `ops_role` block inside the service (same as Từ khóa), only aggregates leave it. The Từ khóa / title-keyword reads now use the
  same block (before, the guarded read silently returned nothing for a seller).
- Excluded listings keep their sales in the shop totals; only rows, cards, flags and KOL rows go.
- The 23 older tables holding UPDATE without a registered call site still fail
  `tests/integration/test_migrations.py::test_no_public_table_holds_update_beyond_its_call_site` (separate ticket, P91 D-14).
- `.gitleaks.toml` gained a line-level allowlist for the false positive `campaign_key=key,` in `tests/unit/test_shopee_builder.py`.
- Nothing writes to Seller Centre. Every change is applied by a person who presses the platform's own save.

## 8. P93 shop team (same branch, adds migration 121)

Several seller people on one shop; only Ops (Vận hành+) invites and removes (contract `p93-shop-team.md`). This section is for the
deploy that carries P93; P92 alone still needs no migration.

1. **Migration 121_shop_members** (additive; head becomes `121_shop_members`): table `shop_members` (RLS; `juli_app` SELECT of its own rows, `juli_ops`
   SELECT/INSERT/UPDATE), two replaced `shops` policies (SELECT / UPDATE admit an active member, or the owner who has no member row of their own), and an AFTER
   INSERT trigger that gives a new seller owner a member row. No row is moved, so the additive gate accepts it. Rollback: `alembic downgrade -1` drops the
   table, trigger and restores the owner-only policies (member rows are lost; shops untouched).
2. **Backfill (separately operated, deferred)**: `deferred/102_shop_members_backfill.py` (an INSERT, so the additive gate refuses it from the release). Until it
   runs nothing is lost: an owner with no row keeps access and Ops lists them as a member. Run it with the same procedure as the 101 deferred step; it is
   idempotent. Check after: `SELECT count(*) FROM shops s JOIN users u ON u.id = s.user_id WHERE (u.email IS NOT NULL OR u.phone IS NOT NULL) AND u.email NOT ILIKE
   '%@app-juli.com' AND NOT EXISTS (SELECT 1 FROM shop_members m WHERE m.shop_id = s.id AND m.user_id = u.id)` returns 0.
3. **Smoke (ORY)**: in Ops, ORY > Cài đặt shop > "Thành viên shop": invite two e-mails (two separate links). Each person opens `/nhan-shop`, signs in with
   their own e-mail and joins; both see ORY and act under their own name. The first accept on a shop with no seller member also takes the shop (as before). Then
   "Gỡ" one of them (in-page confirmation): that person's next request gets 403 and the shop disappears from their list; the other keeps working. Check the audit
   rows `member_add` / `member_remove`.
4. Known limit: deleting the account of the shop's primary account (`shops.user_id`) still purges the whole shop (the existing P50-B purge); other members do not
   keep it. Ask Ops to hand the shop over first. Last-seen time is not shown (no such field exists yet).

---

# Release 2026-11-05b (branch `fasttrack/release-1105`)

Second release of the day, on top of what 196f955e ships (invite fix, P95 doc). It is the merge of
`fasttrack/reco-fixes` and `fasttrack/view-fixes`. P94 is **not** in it.
Carries **migration `121_shop_members`** (P93, additive; head becomes `121_shop_members`) and the shop-team code; see §8 above for its details.

## What ships

- **Recommendations (reco-fixes)**: Gỡ thẻ (Ops withdraws open cards with a reason, one or in bulk); voucher versions say what
  binds (units, "không đổi kết quả" notes, quantity cap) and per day / per order / period units; builder bugs 1-9 (costs and
  variations found by the order lines' SKU, zero-order listings, price response, ads campaigns, affiliate flag); V8 imported
  "done" rows start measurement (`backfill_executed`); V13 the Xem như shop view (`audience=seller`) never shows unsent drafts.
- **Card freshness**: every card and version carries `freshness` (computed_at, `ENGINE_VERSION`, inputs fingerprint, as_of);
  stale ones are flagged and recomputed (`shopee_reco_refresh.refresh_shop`).
- **Views (view-fixes)**: V1 order amount key no longer hits the PII mask (Đơn hàng NaN); V2 a thin previous period withholds
  deltas (Tổng quan 90 ngày); V3 the data anchor follows the Connector's days (`default_as_of` over shop_overview,
  traffic_overview, shop_traffic); V4-V6 variation rows match pack-keyed costs, header SKU and title; V7 Quy tắc header; V10 a bare
  number never glues onto a keyword; V11/V12 dd/mm/yyyy date fields and Phân tích filter; X1/X2 Xếp hạng sorts a KPI card by that KPI,
  busy products are not "ít đơn".
- **P93 shop team (`fasttrack/p92-builder`)**: `shop_members` table, membership-based shop access (RLS on `shops`, `shops_of_user_clause`, `is_shop_member`), Ops members routes / "Thành viên shop" UI, invite changes.
- **Integration changes made in this release**: Xếp hạng (products) now refuses with `previous_period_thin` when the previous
  period fails the same V2 gate as every other delta; `ShopLine.variation_id` is the one place that reads the variation out of a
  line's scope (used by the builder's `observed_skus` and the V4 `base_sku`/`variation_id` columns).

## Deploy-time behaviour to expect

1. **ENGINE_VERSION bump (`2026-11-05.1`)**: every stored card is stale by version, so the first refresh after the deploy
   **recomputes all cards of all Shopee shops once** (revise + re-send). Expect CPU / DB load for a few minutes at start-up
   and one batch of "card updated" rows. It is idempotent: a second run changes nothing. The fingerprint is taken over the
   card's own stored `as_of` (7-day order window), so the data anchor moving forward each day does not make cards stale.
2. **New beat `shopee-reco-refresh`, daily 19:11 UTC (02:11 UTC+7)**: restart **beat** (and the worker) so the schedule is read.
3. **Env switches** (both default on; set `0` to turn off): `RECO_REFRESH_AFTER_WRITE` (recompute right after a seller input
   write) and `RECO_REFRESH_ON_START` (the one-time recompute at API start-up). If the start-up load is a concern, deploy with
   `RECO_REFRESH_ON_START=0`, then let the 19:11 beat (or `refresh_shop` per shop) do it off-peak.

## Post-deploy smoke (as Ops, then as the ORY seller)

1. **Gỡ thẻ**: withdraw one open card with a reason; it leaves the seller's list and shows in Ops as withdrawn. (Undo / re-run.)
2. **Voucher rows** show "Dự kiến dùng X/Y lượt"; changing only the quantity below the cap says "không đổi kết quả".
3. **Đo lường** shows the 7 TD cards after the refresh (V8: imported done rows measured at their own date).
4. **Đơn hàng**: no NaN in the order amounts.
5. **Tổng quan 90 ngày**: no absurd delta against a thin previous period (deltas are withheld, not huge).
6. **Data anchor** (header "dữ liệu đến ...") moves past 02/11 to the Connector's last synced day.
7. **TPE variation costs** (Sản phẩm > TPE gloves): each variation row shows its cost; header SKU is the listing's own, not "1000".
8. **Xếp hạng**: "Biên cuối" column shows %, and sorting by a KPI card sorts by that KPI; a product with real volume is not "ít đơn".
9. Check the logs once for `shopee_reco_refresh` start-up counts (flagged / revised) and that a second run reports 0.

## Manual step: deferred 102 backfill (shop members)

Not part of the automatic release (an INSERT; the additive gate refuses it). After 121 is live, run
`backend/src/juli_backend/database/migrations/deferred/102_shop_members_backfill.py` with the 101 deferred-step procedure
(copy into the serving release's `versions/`, take the backup, `alembic upgrade head`, then move it back). Idempotent; running it late is harmless
(owners without a row keep access). Verify, expecting `0`:

```sql
SELECT count(*) FROM shops s JOIN users u ON u.id = s.user_id
 WHERE (u.email IS NOT NULL OR u.phone IS NOT NULL) AND u.email NOT ILIKE '%@app-juli.com'
   AND NOT EXISTS (SELECT 1 FROM shop_members m WHERE m.shop_id = s.id AND m.user_id = u.id);
```

## Data follow-ups (not code)

- Load the **SellerConversionReport CSV** for the KOL cards (the Phân tích > KOL conversion numbers wait for it).
- **Keyword seeds regenerate**: re-run the seeds for the shops whose keyword list changed (V10 changed how numbers are glued).

## Rollback

Redeploy 196f955e (migration 121 can stay: additive, the old code ignores `shop_members`; to remove it `alembic downgrade -1`, see §8.1). Stored cards keep their `freshness` block, which the old code ignores. Turn the recompute
off first with `RECO_REFRESH_ON_START=0` / `RECO_REFRESH_AFTER_WRITE=0` if the load is the problem.
