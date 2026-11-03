# backend/src/juli_backend/services/shopee_profit

## Purpose

Pure profit arithmetic for the Shopee "broad -> precise" pipeline, aligned with
`fasttrack/contracts/p90-metrics.md` (the authority; a change there is a change here): fee
formula by date, per-order waterfall, traffic flows from aggregates, price levers, product and
shop profit, floor price / max discount, what-if scenarios, the five numbers. No DB, no I/O,
no clock; `Decimal` VND; frozen dataclasses.

## Public API

- `fees`: `FeeComponent`, `FeeFormula.fee(line, fixed=)`, `FeeFormula.split_fixed(weights)`,
  `FeeSchedule.formula_on(date)`. Fixed per-order fees are charged once per order.
- `order_profit`: `OrderLine`, `SkuCost`, `AdsPool`, `line_profit(...)`,
  `profit_lines(...)` -> `ProfitBreakdown` (`contribution` = before ads; `profit` = after the
  DISPLAY line-level ad split). `profit_lines` takes whole orders (splits fixed fees).
- `flows`: `build_flow_tables(rows, shop_gmv=, shop_orders=, product_totals=, ads=)` ->
  `FlowTables(shop, products)`; five flows (`the_san_pham` = Thẻ sản phẩm - Trang shop,
  `trang_shop`, `live`, `video`, `lien_ket`) + `chenh_lech_nguon` residual row; CTR / CTOR /
  AOV, exact identity `gmv_by_identity()`, ads as an overlay (`FlowMetrics.ads`).
- `sources`: `build_source_matrix(...)`, `assert_additive(...)` -- price lever only
  (`combo` > `khuyen_mai` > `voucher` > `khong_uu_dai`) from order lines.
- `shop_profit`: `product_profits`, `shop_profit(pairs, campaigns=, product_ad_spend=,
  other_marketing_costs=, export_gmv=)` -> `ShopProfit` (contribution, total / unattributed ad
  spend, profit, margin, cost coverage, GMV reconciliation, break-even ROAS per product);
  `pools_from_product_spend` reconciles the display line ad split to the ads report.
- `floor`: `FloorInputs`, `compute_floor(...)` -> `FloorResult`.
- `five_numbers`: `snapshot_from(pairs, ad_spend, ...)`, `five_numbers(before, after,
  spend_cap=)` -> discount, dGMV / dchi (+ `giam_chi`), margin, orders, AOV, spend/day vs cap.
- `whatif`: `voucher_whatif` (usage model of contract 7: `VoucherRule(usage_limit, per_user_limit)`,
  `usage_rate` u, `voucher_days` / `window_days`; returns used, cost, per-order organic vs
  ad-attributed, floor breaches, break-even, spend per day, and the five numbers),
  `price_change_whatif`, `ads_whatif` -> `{certain, predicted}`.

## Rules (see each module docstring)

- Rates are fractions, `*_pct` outputs are percent points (0.1). Fees/ads/floors round to
  đồng half up; offered discounts round down to 1.000đ. Missing input -> `None` + reason,
  never 0. `predicted` only multiplies a caller range; nothing here forecasts.
- Margin = profit / buyer_paid everywhere. Cost coverage < 100 % -> margin is PARTIAL
  (covered lines only, ad spend charged in full), flagged, never extrapolated.
- Product profit = sum(contribution) - ads-report spend by product; shop profit = sum(contribution)
  - total spend of all campaigns - other marketing costs. The line-level ad split is display only.
- Flows come from aggregates, not order lines; they add up to shop GMV via the residual row.
- Voucher: used = min(Q x u, usage_limit), Q scaled to the voucher's days; cost = used x average
  discount of a qualifying order. u defaults to 1 (`usage_rate_source == "default_1"`).

## Must not

- Touch a database, network or clock; import from routes or repositories.
- Hard-code which base a Shopee fee uses -- it is `FeeComponent.base`.
- Derive traffic flows from order lines or add ads as a row of the flow sum.
