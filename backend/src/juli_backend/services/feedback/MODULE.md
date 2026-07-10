# Module: feedback

## Responsibility
Ingests realized campaign outcomes into the commerce graph (Campaign nodes and
`predicted_vs_actual` edges) for calibration and downstream matching.

## Public Interface
- `ingest_campaign_outcome(session, shop_id, …) -> OutcomeIngestResult` — idempotent on `idempotency_key`
- `compute_calibration_weight(predicted_gmv, realized_gmv) -> Decimal` — edge weight in [0, 1]

## API
- `POST /v1/outcomes` — `backend/src/juli_backend/api/routes/outcomes.py`
