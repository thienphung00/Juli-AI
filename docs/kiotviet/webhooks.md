# KiotViet Webhooks

## Overview

KiotViet supports webhooks to notify your system of data changes in real-time. Instead of polling the API, you can register webhook URLs to receive push notifications when specific events occur.

## Webhook Registration

### Register Webhook

```
POST https://public.kiotapi.com/webhooks
```

**Request Body:**

```json
{
  "Webhook": {
    "Type": "string",
    "Url": "https://your-domain.com/webhook-handler",
    "IsActive": true
  }
}
```

### Webhook Types

| Type | Description |
|---|---|
| `product.update` | Product created or updated |
| `product.delete` | Product deleted |
| `stock.update` | Inventory/stock level changed |
| `order.update` | Order created or updated |
| `order.delete` | Order deleted/cancelled |
| `invoice.update` | Invoice created or updated |
| `invoice.delete` | Invoice deleted/cancelled |
| `customer.update` | Customer created or updated |
| `customer.delete` | Customer deleted |

### List Webhooks

```
GET https://public.kiotapi.com/webhooks
```

### Delete Webhook

```
DELETE https://public.kiotapi.com/webhooks/{id}
```

## Webhook Payload

When an event occurs, KiotViet sends an HTTP POST request to your registered URL with the relevant data.

**Expected payload structure:**

```json
{
  "Id": 12345,
  "Attempt": 1,
  "Notifications": [
    {
      "Action": "update",
      "Data": [
        {
          "Id": 67890,
          "Type": "product"
        }
      ]
    }
  ]
}
```

## Implementation Guidelines

### Endpoint Requirements

1. Your webhook URL must be publicly accessible (HTTPS recommended).
2. Respond with HTTP 200 within a reasonable timeout.
3. Process webhook payloads asynchronously to avoid timeouts.

### Reliability Patterns

1. **Idempotency**: Handle duplicate deliveries gracefully.
2. **Verification**: Validate webhook source using shared secrets or IP allowlists.
3. **Retry awareness**: KiotViet may retry failed deliveries (non-200 responses).
4. **Ordering**: Do not assume chronological delivery order.

### Recommended Architecture

```
[KiotViet] --> [Your Webhook Endpoint] --> [Message Queue] --> [Worker Process]
```

1. Receive webhook, immediately return 200.
2. Queue the payload for async processing.
3. Worker processes the event and updates your system.

## Best Practices

- Always verify the webhook payload before processing.
- Log all incoming webhooks for debugging and audit.
- Implement circuit breakers for downstream failures.
- Monitor webhook delivery success rates.
- Set up alerts for sustained delivery failures.
