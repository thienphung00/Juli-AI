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
