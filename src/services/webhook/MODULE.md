# Module: services/webhook

## Responsibility
Receives TikTok Shop webhooks, verifies HMAC-SHA256 signatures, and publishes
the raw event payload to a Kafka topic derived from the event type.

## Public Interface

- `create_app(*, app_key, app_secret, publish_fn) -> FastAPI` — application
  factory returning a configured FastAPI app
  - `publish_fn: Callable[[str, str, bytes], Awaitable[None]]` — async function
    invoked with `(topic, partition_key, payload_bytes)` for each verified
    event
- `PublishFn` — type alias for the publish function contract
- `EVENT_CATEGORY_ROUTES: dict[str, str]` — prefix→topic mapping for
  livestream, creator/affiliate, and settlement event categories

The app exposes a single HTTP endpoint:

- `POST /webhooks/tiktok` — accepts a JSON event; returns `{"code": 0}` on
  success, `401` on signature failure, `400` on malformed/incomplete payload

## Dependencies
- `fastapi` — HTTP framework
- Standard library: `hashlib`, `hmac`, `json`, `logging`

The publish function is injected by the caller — this module does not import
any Kafka client directly. This keeps the module testable with an in-memory
`publish_fn` stub.

## Invariants
- Every request must include an `Authorization` header containing the HMAC
  signature; missing or invalid signatures return HTTP 401 without publishing
- Signature verification uses constant-time comparison (`hmac.compare_digest`)
- Malformed JSON or missing required fields (`type`, `shop_id`) return HTTP
  400 without publishing
- Topic routing uses `EVENT_CATEGORY_ROUTES` prefix match: `LIVESTREAM*` →
  `livestream-events`, `CREATOR*`/`AFFILIATE*` → `creator-events`,
  `SETTLEMENT*` → `settlement-events`; unrecognized types fall back to
  `f"tiktok.{event_type.lower()}"`
- Partition key for Kafka is always `shop_id` — ensures per-shop ordering
- The handler is idempotent at the transport level: a duplicate webhook
  produces a duplicate publish (deduplication is downstream consumer's
  responsibility)

## Owners
- domain: integrations
- code: `src/services/webhook/`
- tests: `tests/unit/test_webhook_*.py`, `tests/integration/test_webhook_*.py`
