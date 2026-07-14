# backend/src/juli_backend/services/webhook

## Purpose

Receives TikTok Shop webhooks, verifies HMAC-SHA256 signatures, dispatches through
the Phase 2 catalog (#354), and hands validated raw payloads to the ingest pipeline
(ETL) via an injected `handoff_fn`.

## Public API

- `create_app(*, app_key, app_secret, handoff_fn) -> FastAPI` — standalone application factory
  - `handoff_fn: Callable[[str, str, bytes], Awaitable[None]]` — async function
    invoked with `(channel, shop_key, payload_bytes)` for each verified in-scope event
- `build_webhook_service(*, app_key, app_secret, handoff_fn, side_effects=None) -> TikTokWebhookService`
  — shared verify+dispatch+handoff assembly, reused by `create_app` and by
  `juli_backend.api.routes.webhook_tiktok` (the deployed mount point)
- `HandoffFn` — type alias (from `juli_backend.services.ingestion`)
- `WEBHOOK_PATH` — `/webhooks/tiktok`

## Dependencies

- `juli_backend.services.tiktok` — signature verify, catalog dispatch, channel routing
- FastAPI, httpx (via test client)
- No direct database imports — handoff is injected by the deploy wiring layer

## Key Behaviors

- Returns `{"code": 0}` within TikTok's 3-second ACK window; persistence is async
  via ETL after handoff
- Missing or invalid `Authorization` header → HTTP 401 without handoff
- Malformed JSON or missing `type` / `shop_id` → HTTP 400 without handoff
- Phase 2 catalog types route to catalog-specific ETL channels (see `webhook_catalog.py`)
- Deferred Phase 3+ types (Affiliate, Livestream, etc.) → ACK without handoff
- Account webhooks (#6 deauthorization, #7 auth expiration) → side effects only
- `shop_id` is the handoff key (TikTok shop id) for per-shop ordering downstream
- Duplicate webhook delivery is expected; deduplication is in `juli_backend.services.etl`

## Related modules

- `juli_backend.services.tiktok.webhook_catalog` — Phase 2 registry (#1–#68 subset)
- `juli_backend.services.tiktok.webhook_handlers` — workflow signals + account lifecycle
- `juli_backend.models.models.WorkflowWebhookSignal` — durable workflow-intent records

## Wiring (production)

`WEBHOOK_PATH` (`/webhooks/tiktok`) is registered on **two** ASGI apps that share
the `build_webhook_service` assembly:

1. **`juli_backend.api.app`** (deployed) — `api/routes/webhook_tiktok.py` mounts
   the route directly on the main API via `app.include_router(...)`, using the
   request-scoped `get_session` dependency (same as every other `/v1/*` route)
   instead of an injected `session_factory`. This is what TikTok Partner Center
   actually reaches at `https://api.app-juli.com/webhooks/tiktok` — Nginx and
   `juli-api` (systemd) require no changes since both already proxy/serve every
   path on port 8000 (see `docs/runbooks/backend-deploy-runbook.md`).
2. **`create_app(...)`** below (standalone, not deployed) — a dedicated FastAPI
   app kept for isolated testing (`tests/unit/test_webhook.py`,
   `test_webhook_main.py`) and as a future extraction point if webhook traffic
   ever needs its own process:

```python
from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.ingestion import make_etl_handoff

consumer = EtlConsumer(session=session, dlq_handoff=dlq_fn)
handoff = make_etl_handoff(consumer)
app = create_app(app_key=..., app_secret=..., handoff_fn=handoff)
```

## Co-existence with polling

Webhooks provide low-latency workflow gates; Fujiwa polling (≤15 min) remains the
authoritative reconciliation backstop per `docs/architecture/data-sources.md`.
