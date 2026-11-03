# backend/src/juli_backend/services/shopee_profit

## Purpose

Pure profit arithmetic for the Shopee "broad -> precise" pipeline: fee formula by date,
per-order profit waterfall, floor price / max discount, what-if scenarios, Huyền's five
numbers, product x source matrix. No DB, no I/O, no clock; `Decimal` VND; frozen dataclasses.

## Public API

- `fees`: `FeeComponent`, `FeeFormula.fee(line)`, `FeeSchedule.formula_on(date)`.
- `order_profit`: `OrderLine`, `SkuCost`, `AdsPool`, `line_profit(...)`, `profit_lines(...)` -> `ProfitBreakdown`.
- `floor`: `FloorInputs`, `compute_floor(...)` -> `FloorResult`.
- `whatif`: `voucher_whatif`, `price_change_whatif`, `ads_whatif` -> `{certain, predicted}`.
- `five_numbers`: `snapshot_from(...)`, `five_numbers(before, after, spend_cap=)`.
- `sources`: `build_source_matrix(...)`, `assert_additive(...)`.

## Rules (see each module docstring)

Rates are fractions, `*_pct` outputs are percent points (0.1). Fees/ads/floors round to
đồng half up; offered discounts round down to 1.000đ. Missing input -> `None` + reason, never 0.
`predicted` only multiplies a caller range; nothing here forecasts.

## Must not

- Touch a database, network or clock; import from routes or repositories.
- Hard-code which base a Shopee fee uses -- it is `FeeComponent.base`.
