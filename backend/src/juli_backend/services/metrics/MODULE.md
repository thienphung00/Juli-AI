# backend/src/juli_backend/services/metrics

## Purpose

The metric registry (owner decisions T5, T6, T8): every number a seller, Ops, a reviewer, the
recommender, the measurement, an export or an agent tool sees is one id here with one formula
over canonical components. Design: `docs/architecture/metric-registry.md` (draft 2; owner
decisions §11). Pure: no DB, no I/O, no clock. Step 1 of the migration: nothing reads it yet.

## Layers

| Module | Role |
|---|---|
| `registry` | `MetricDef`, `SourceSpec`, `METRICS` (every §5 id), `PARAMS`, `DERIVATION_VERSION`; formulas as data (`("div", "gmv", "orders")`) |
| `components` | `COMPONENTS` (§4 ids + the ones a §5 metric needs, `in_doc=False`), the `Components` value type |
| `compute` | `evaluate(metric_id, components) -> MetricValue`; `change`, `per_day`; `kol_status` |
| `allocation` | `channel_partition` (§6), `shop_lines` (§7 "Cả shop" lines), `deoverlap_periods` (A6) |

Generated TS contract: `apps/demo/src/lib/metrics/registry.generated.ts`, written by
`scripts/gen_metric_contract.py`; `tests/unit/test_metric_contract.py` fails when it is stale.

## Rules (each has a test in `tests/unit/test_metric_registry.py`)

- A bare id in a formula is a component when one exists by that id, else a metric.
- Ratios from summed components; a summable metric is a sum / difference of summable ids.
- Missing is not zero: a `None` operand makes the metric `None`; ÷ 0 or ÷ `None` is `None`.
- Rounding once, on the metric asked for (`shopee_profit/money.py` helpers).
- Cost-dependent metrics carry `coverage` (`cost_coverage`) and `partial` below 100 %.
- A formula change bumps `DERIVATION_VERSION`, and the TS file is regenerated.

## Stored components (data layer, decisions #62-#66)

- Every component declares `sums_across` (`Dim`: day, item, channel, discounted, campaign);
  `check_sum` raises `InvalidSum` for any other sum (product đơn never add up to shop đơn). The
  stored daily tables (migration 140) hold components under their registry ids.
- `METRIC_ALIASES`: `margin_before_marketing` = `margin_contribution` (A9, one formula);
  `evaluate` resolves an alias. `ADS_PERIOD_RULE` (A6) is the ads-by-product day rule.
- `affiliate_commission` is THE AFF cost (`shopee_profit.ladder.affiliate_cost`, A1).

## TikTok traffic sources and reason codes (W3, decision #7)

`TRAFFIC_SOURCES` says which sources a platform has. TikTok has Thẻ sản phẩm, Video, LIVE (Organic)
and Tiếp thị liên kết (TTLK), which add up to the shop total, and Tab cửa hàng (`trang_shop`), which
is a row beside them (`counts_in_total` is False; orders / CTOR / AOV are `None`, see
`SOURCE_METRIC_GAPS`). Quảng cáo and the Shopee residual are `None`. `source_reason` /
`metric_reason` give the reason code a screen shows beside a `None` (`ads_scope_missing`,
`source_not_on_platform`, `tab_reports_no_orders`); a missing value is never 0. A change here bumps
`DERIVATION_VERSION`.

## Must not

- Read the database or the clock (a later step wires `components` to layer-4 tables).
- Hold an `if shopee:` -- a platform's source is data in `sources`.
