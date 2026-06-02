# Webhooks & Event Handling

## Overview

TikTok Shop provides push-based webhooks for real-time event notifications. Webhooks are the **primary** data ingestion mechanism — they eliminate polling overhead and provide sub-minute latency for critical events like new orders and status changes.

## Registration

1. Navigate to Partner Center → App → Webhook Settings
2. Configure your HTTPS endpoint URL
3. Select event types to subscribe to
4. TikTok will verify your endpoint with a challenge request

### Endpoint Requirements

- Must be HTTPS (TLS 1.2+)
- Must respond with HTTP 200 within 3 seconds
- Must verify the request signature (see below)
- Should be idempotent (same event may be delivered multiple times)

## Event Types

### Order Events

| Event | Trigger | Priority |
|-------|---------|----------|
| `ORDER_STATUS_CHANGE` | Order status transitions (new, paid, shipped, delivered, cancelled) | Critical |
| `ORDER_PAYMENT_STATUS_CHANGE` | Payment confirmed or refunded | Critical |

### Fulfillment Events

| Event | Trigger | Priority |
|-------|---------|----------|
| `PACKAGE_UPDATE` | Shipping/tracking status change | High |
| `RETURN_STATUS_CHANGE` | Return request created/approved/rejected/completed | High |

### Product Events

| Event | Trigger | Priority |
|-------|---------|----------|
| `PRODUCT_STATUS_CHANGE` | Product approved/suspended/removed by platform | High |
| `PRODUCT_INFORMATION_CHANGE` | Product details modified | Medium |

### Authorization Events

| Event | Trigger | Priority |
|-------|---------|----------|
| `SELLER_DEAUTHORIZATION` | Seller revokes app access | Critical |
| `UPCOMING_AUTHORIZATION_EXPIRATION` | 30 days before refresh token expires | High |

### Communication Events

| Event | Trigger | Priority |
|-------|---------|----------|
| `NEW_CONVERSATION` | Buyer initiates a new conversation | Medium |
| `NEW_MESSAGE` | New message in existing conversation | Medium |

## Webhook Payload Format

```json
{
  "type": "ORDER_STATUS_CHANGE",
  "shop_id": "7000000000000001",
  "timestamp": 1234567890,
  "data": {
    "order_id": "577000000000001",
    "order_status": "AWAITING_SHIPMENT",
    "update_time": 1234567890
  }
}
```

## Signature Verification

TikTok signs webhook payloads so you can verify authenticity.

### Verification Steps

1. Extract the `Authorization` header from the request
2. Reconstruct the signing string: `{app_key}{path}{body}`
3. Compute HMAC-SHA256 using your App Secret
4. Compare your computed signature with the header value

```python
import hmac
import hashlib

def verify_webhook(app_key: str, app_secret: str, path: str, body: bytes, received_sig: str) -> bool:
    sign_string = f"{app_key}{path}{body.decode()}"
    expected = hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, received_sig)
```

## Handling Strategy

### Architecture

```
TikTok Webhook → HTTPS Endpoint → Validate Signature → ETL handoff → ACK (200)
                                                              │
                                                              ▼
                                                     src/etl (dedup + transform)
                                                              │
                                         ┌────────────────────┼────────────────────┐
                                         ▼                    ▼                    ▼
                                   Update DB           (v2.0 cache)         Trigger Alerts
```

### Best Practices

1. **Respond fast** — Acknowledge (HTTP 200) immediately, process asynchronously
2. **Idempotency** — Use `(event_type, shop_id, data.order_id, timestamp)` as dedup key
3. **Ordering** — Events may arrive out-of-order; use `update_time` to resolve conflicts
4. **Retry handling** — TikTok retries failed deliveries; ensure your endpoint is idempotent
5. **Dead letter queue** — Store unprocessable events for manual review
6. **Backfill** — If webhooks are missed (downtime), use list endpoints with `update_time_from` to catch up

### Failure Recovery

If your webhook endpoint is down:
- TikTok will retry with exponential backoff (typically 3-5 retries)
- After retries exhaust, events are lost
- Implement a periodic reconciliation job that polls recent orders/products to detect missed events
- Use the `update_time_from` filter on list endpoints for gap detection

## Recommended Event Processing Pipeline

```python
# Webhook handler (FastAPI example)
@app.post("/webhooks/tiktok")
async def handle_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("Authorization")
    
    if not verify_webhook(APP_KEY, APP_SECRET, "/webhooks/tiktok", body, signature):
        raise HTTPException(status_code=401)
    
    event = json.loads(body)
    
    await handoff_fn(
        f"tiktok.{event['type'].lower()}",
        event["shop_id"],
        body,
    )

    return {"code": 0}
```

Production wiring uses `create_app(..., handoff_fn=make_etl_handoff(etl_consumer))`.
See `src/services/webhook/` and `src/ingestion/handoff.py`.

## Monitoring & Alerts

- Track webhook delivery success rate (target: >99.5%)
- Alert on consecutive delivery failures (>3 in 5 minutes)
- Monitor processing lag (time from event to DB write)
- Dashboard showing event volume by type per hour
- Alert on `SELLER_DEAUTHORIZATION` for immediate credential cleanup
- Alert on `UPCOMING_AUTHORIZATION_EXPIRATION` for proactive token refresh
