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
| `allocation` | `channel_partition` (§6), `shop_lines` (§7 "Cả shop" lines) |

Generated TS contract: `apps/demo/src/lib/metrics/registry.generated.ts`, written by
`scripts/gen_metric_contract.py`; `tests/unit/test_metric_contract.py` fails when it is stale.

## Rules (each has a test in `tests/unit/test_metric_registry.py`)

- A bare id in a formula is a component when one exists by that id, else a metric.
- Ratios from summed components; a summable metric is a sum / difference of summable ids.
- Missing is not zero: a `None` operand makes the metric `None`; ÷ 0 or ÷ `None` is `None`.
- Rounding once, on the metric asked for (`shopee_profit/money.py` helpers).
- Cost-dependent metrics carry `coverage` (`cost_coverage`) and `partial` below 100 %.
- A formula change bumps `DERIVATION_VERSION`, and the TS file is regenerated.

## Must not

- Read the database or the clock (a later step wires `components` to layer-4 tables).
- Hold an `if shopee:` -- a platform's source is data in `sources`.
