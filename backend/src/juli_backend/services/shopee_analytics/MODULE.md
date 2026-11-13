# backend/src/juli_backend/services/shopee_analytics

## Purpose

P90 step 7: the stored Shopee data wired to the pure `services/shopee_profit` package, and the
read APIs for the shop screens -- Tong quan, Phan tich, San pham, Xep hang. Definitions are
`fasttrack/contracts/p90-metrics.md` (the authority; a change there is a change here).
Read-only: nothing here writes.

## Layers

| Module | Role |
|---|---|
| `windows` | 7 / 30 / 90 days, calendar month, custom window; the previous period (same length, the days before); `choose_periods` (exact > contained > approx) |
| `fee_table` | fee formula when the order export has no actual fee: `platform_fee_formulas` row for the category > code-level seed for ORY's categories (contract 10a, `shopee_vn_non_mall`) > shop default (flagged) |
| `catalog`, `rules_view` | items and the SKU -> item resolution; the seller's cost / packaging / target rules |
| `loaders` | repositories -> detached dataclasses per shop and window; says which stored rows stand in for the window (`basis`, `days_covered`) |
| `engine` | order lines -> `OrderLine` + cost + fee context -> waterfall; cost coverage split real / assumed |
| `compute` | one window's `PeriodView` (profit, flows, ads allocation, levers) shared by every builder |
| `overview`, `matrix`, `product`, `critical`, `rankings` | pure builders -> JSON-ready dicts |
| `queries` | one async function per screen (the routes call these) |

Routes: `api/routes/demo_shopee_analytics.py` (seller scope, `/v1/demo/shopee/*`) and
`api/routes/ops_shopee_analytics.py` (Ops viewer, `/v1/ops/shops/{id}/shopee/analytics/*`).
Repositories: `repositories/shopee_analytics.py`.

Beyond the screens' numbers: `matrix` rows carry numbers 1 and 2 against the previous period and
the Thẻ sản phẩm children (only when `item_traffic_sources` day rows exist); the product page
carries `header.versions` (snapshot changes), `daily` (GMV / orders / views / clicks by day),
`ads.campaigns` and `freshness`; the overview carries `freshness` (newest stored day per dataset).
`critical` adds a product-level Lượt xem (search) item against the shop median when the per-source
day rows exist. Card references are attached by the routes (`services/shopee_recommendations/refs`),
never here.

## Rules (from the contract; each has a test)

- Order basis: confirmed = has a payment time (14). GMV, orders and AOV use every confirmed line;
  profit uses delivered / accepted-refund lines only. A line never paid is not an order.
- Flows come from aggregates, never order lines; five flows + `chenh_lech_nguon` add up to the
  shop GMV; Thẻ sản phẩm children are a drill-down, not a sum.
- Ads are an overlay ("trong do"), labelled `đơn đã đặt`, never added to a confirmed total. The ads
  report is allocated to the window (per campaign the best-fitting report window, prorated by days)
  and scaled so the total equals the daily ads figures; the basis is in `ads.allocation`.
- Costs: imported SKU / product cost wins, else gia von = 1/3 of list price (`assumed`); packaging
  falls back to 0 (`assumed`). Every profit figure carries `cost_coverage` (real / assumed / unknown).
- Fees: actual (order export) wins; per-order components are charged once per order.
- Rankings: rows + `few` + `others` + `mix` == the cell's change for additive measures
  (`gmv_per_day`, `profit_per_day`, `orders`); ratio measures say they do not add up.
- A missing input is `None` with a reason, never 0. A missing target is no item, never a default.

## Must not

- Write to the database, or call the network or the clock (the caller passes `as_of`).
- Put a buyer field, an `order_ref`, a voucher code or any key starting with `buyer` in a payload
  (the Ops masking layer would blank it; tests scan every payload).
- Import from routes. Read tables through `repositories`, not raw SQL.
- Re-derive a number `services/shopee_profit` already computes.


## KOL (P91 D-9, D-11)

`kol` builds KOL x sản phẩm x kênh rows from the affiliate-marked order lines (migration 118 keeps
`kol_key`, public handle, channel, campaign type, MCN flag on the line). Commission per line:
the report's `Chi phí(₫)` (`ingest/affiliate_commission`, G-15), else the product's targeted-campaign
rate, else its open-campaign rate (`kol_rates`), on the line's `buyer_paid` (order value after the
shop's discounts, shipping excluded); the profit waterfall is re-run with it. Per row: orders, units,
GMV, commission, net profit, sample cost (Mẫu KOL), profit after samples, ROI incl. samples =
(net - sample) / (commission + sample), `roi_shopee` = Shopee's creator-export ROI as exported,
payback orders, `low_data` below 10 pair orders. Clicks exist per creator only (`kol_clicks`). `KolPool`
carries the same facts for the KOL cards. Entry points `queries.kol_table` / `queries.kol_product_tab`;
`kol.pair_daily` is the KOL x product daily series the measurement reads.

## ShopMetrics and the materialized daily tables (P97 D85.2)

- `metrics.py` -- `ShopMetrics`: headline GMV / đơn = Shopee shop totals, one AOV = GMV ÷ đơn
  (Seller Centre AOV a labelled second line), views / CTR / CTOR, ads, profit, biên, and the product
  splits (order lines scaled to the totals, whole đồng, residual kept). `view.metrics` is what every
  screen reads: the stored daily rows when every day of the window is complete, else the raw tables.
- `stored.py` (read), `materialize.py` (build) -- `shopee_shop_metrics_daily` /
  `shopee_product_metrics_daily` (migration 123). `after_ingest` is the gateway hook;
  `scripts/backfill_shopee_metrics.py` backfills a shop.
- `windows.choose_anchor` / `loaders.load_anchor` -- the one window end: the last day every live daily
  dataset posted (or the last complete materialized day); the payload names it.

## Missing days and unknown costs (P100-A, B.17)

- A day whose order data never arrived (`shop_overview` without đơn, or all-zero with no visitor
  and no click: `loaders.order_day`) is NULL in `shopee_shop_metrics_daily`, never 0. Window sums
  (`stored.load_stored`), the funnel base (`funnel.load_rows`) and the spread series leave it out;
  `ShopMetrics.coverage()` says "N/30 ngày có dữ liệu" on Tổng quan, Sản phẩm and Luồng.
- A day with orders and no costed line has a NULL profit (shop and product), never 0.
- A product row never counts more đơn / GMV than its shop's day; rows on days without order data
  (stale pre-P99 stamps) are ignored on read and rewritten by the backfill.
