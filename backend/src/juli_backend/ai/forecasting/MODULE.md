# Module: intelligence/forecasting

## Responsibility
SKU-level inventory depletion forecasting on a 3–7 day horizon using sales
velocity derived from completed shop orders (equal attribution across active
SKUs). Surfaces low-stock risk rankings and acceleration/deceleration signals.
Read-only against `src/data` — no writes or migrations.

## Public Interface

### Forecasting
- `get_forecast(session, shop_id, sku_id) -> ForecastResult` — projected
  depletion date and daily velocity; linear regression when ≥30 days of order
  history exist, otherwise simple moving average.
- `ForecastResult` — `sku_id`, `depletion_date`, `daily_velocity`, `method`
  (`linear_regression` | `moving_average`), optional `horizon_mape` backtest.

### Low-stock risks
- `get_low_stock_risks(session, shop_id, window_days=7) -> list[LowStockRisk]`
  — SKUs likely to stock out within the window, sorted by urgency.
- `LowStockRisk` — `sku_id`, `tiktok_product_id`, `quantity`, `daily_velocity`,
  `days_until_stockout`, `urgency_score`

### Reorder quantity computation (Issue #721)
- `REORDER_LEAD_TIME_DAYS`, `REORDER_SAFETY_STOCK_DAYS` — the reorder policy. Any
  consumer displaying a *basis* to the seller must read these rather than restate
  the numbers, or the basis can drift out of agreement with the quantity.
- `compute_reorder_quantity(risk, lead_time_days=REORDER_LEAD_TIME_DAYS,
  safety_stock_days=REORDER_SAFETY_STOCK_DAYS) -> float`
  — Suggested reorder quantity for a low-stock item based on sales velocity.
  For `daily_velocity > 0`, returns `ceil(daily_velocity * (lead_time_days + safety_stock_days))`
  with a floor of 1 unit. For `daily_velocity ≤ 0` (no recent sales), returns 10 units.
  Computed on-demand when recommendation is displayed; value is freely editable before approval.

### Velocity changes
- `get_velocity_changes(session, shop_id) -> list[VelocityChange]` — SKUs whose
  last-7-day velocity differs from the prior 7 days by ≥15%.
- `VelocityChange` — `sku_id`, `direction` (`accelerating` | `decelerating`),
  `recent_velocity`, `prior_velocity`, `change_ratio`

## Dependencies
- `sqlalchemy[asyncio]` — async reads
- `src.data.models.Order`, `InventoryItem`

## Invariants
- Read-only; shop-scoped queries only
- ≥30 days of daily order history → linear regression; below → moving average
- Velocity change detection requires ≥14 days of attributed daily series
- Order attribution splits completed orders equally across active inventory SKUs
  (MVP proxy until per-SKU line items exist)

## Owners
- domain: intelligence
- code: src/intelligence/forecasting/
