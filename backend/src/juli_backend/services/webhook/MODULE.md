# backend/api/services/webhook

## Purpose

Receives TikTok Shop webhooks, verifies HMAC-SHA256 signatures, and hands validated
raw payloads to the ingest pipeline (ETL) via an injected `handoff_fn`.

## Public API

- `create_app(*, app_key, app_secret, handoff_fn) -> FastAPI` — application factory
  - `handoff_fn: Callable[[str, str, bytes], Awaitable[None]]` — async function
    invoked with `(channel, shop_key, payload_bytes)` for each verified event
- `HandoffFn` — type alias (from `backend/integrations/ordering/api/ingestion/handoff`)
- `EVENT_CATEGORY_ROUTES` — prefix → channel mapping for livestream/creator/settlement

## Dependencies

- FastAPI, httpx (via test client)
- No database or ETL imports — handoff is injected by the deploy wiring layer

## Key Behaviors

- Returns `{"code": 0}` within TikTok's 3-second ACK window; persistence is async
  via ETL after handoff
- Missing or invalid `Authorization` header → HTTP 401 without handoff
- Malformed JSON or missing `type` / `shop_id` → HTTP 400 without handoff
- Channel derived from event `type` (category prefixes or `tiktok.{type}`)
- `shop_id` is the handoff key (TikTok shop id) for per-shop ordering downstream
- Duplicate webhook delivery is expected; deduplication is in `backend/integrations/ordering/use_cases/etl`

## Wiring (production)

```python
from src.etl.consumer import EtlConsumer
from src.ingestion.handoff import make_etl_handoff

consumer = EtlConsumer(session=session, dlq_handoff=dlq_fn)
handoff = make_etl_handoff(consumer)
app = create_app(app_key=..., app_secret=..., handoff_fn=handoff)
```
