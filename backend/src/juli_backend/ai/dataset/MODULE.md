# backend/ai/dataset

## Purpose

Phase 1.5 backtest dataset assembly: synthetic parquet generation, schema validation,
and versioned manifest output for seller-money ML training. No TikTok API calls;
no Postgres writes ([ADR-011](../../../docs/adr/011-buyer-behavior-anomaly-scope.md)).

## Public Interface

- `assemble_backtest_dataset(output_dir, *, seed, n_shops, orders_per_shop, return_rate, ads_days, source) -> dict` — generate parquet + manifest; validate before return
- `validate_backtest_dataset(output_dir) -> dict` — fail-fast schema/enum validation
- `DatasetValidationError` — raised when parquet or manifest is invalid
- `ORDERS_COLUMNS`, `ORDER_ITEMS_COLUMNS`, `RETURNS_COLUMNS`, `LABELS_COLUMNS`, `ADS_COLUMNS`, `RETURN_TYPE_VALUES` — parquet contracts
- CLI: `python -m backend.ai.dataset.cli` (`assemble-backtest-dataset`)

## Dependencies

- `pandas`, `pyarrow` — parquet I/O
- `docs/api/data-models/canonical-entities.md` — entity field authority
- `docs/api/data-models/mock-data-generator.md` — synthetic generation rules

## Key Behaviors

- Writes `orders.parquet`, `order_items.parquet`, `returns.parquet`, `labels.parquet`, `ads.parquet` under caller-provided output directory
- `labels.parquet` contains buyer-behavior labels only: `return_id`, `ground_truth_anomaly`, `return_type`
- Synthetic generator uses masked `buyer_id` only — no PII
- Manifest records row counts, date range, train/eval split boundaries, dataset version
- No affiliate parquet in anomaly path (ADR-011)

## Out of Scope

- Feature engineering (#137)
- Model training (#138–#140)
- TikTok API ingestion
- Legacy `catalog/domain/intelligence/scoring`
