# Rate Limits & Throttling Strategy

## TikTok's Rate Limit Model

Rate limits are enforced **per (app_id × shop_id) pair**. This means each seller's shop has its own quota bucket when accessed through your app.

### Limit Tiers

| Endpoint Category | Frequency Tier | Typical Limit |
|-------------------|---------------|---------------|
| Orders list/search | High frequency | Stricter (lower quota) |
| Order detail | Medium frequency | Moderate |
| Product CRUD | Medium frequency | Moderate |
| Inventory update | Medium frequency | Moderate |
| Finance/Settlement | Low frequency | More lenient |
| Shop info | Low frequency | More lenient |

> **Note:** TikTok does not publicly document exact numeric limits. Monitor 429 responses to calibrate.

### Rate Limit Response

When limits are exceeded, the API returns:

```json
{
  "code": 100005,
  "message": "Request rate limit exceeded",
  "request_id": "..."
}
```

HTTP status: `429 Too Many Requests`

Headers may include:
- `X-RateLimit-Limit` — Max requests in window
- `X-RateLimit-Remaining` — Remaining requests
- `X-RateLimit-Reset` — Unix timestamp when window resets

## Throttling Architecture

### Token Bucket per Shop

Maintain a token bucket (or leaky bucket) for each `(app_id, shop_id)` pair:

```
┌─────────────────────────────────────────────────┐
│                  Rate Limiter                     │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Shop A   │  │ Shop B   │  │ Shop C   │ ...  │
│  │ Bucket   │  │ Bucket   │  │ Bucket   │      │
│  │ 10/min   │  │ 10/min   │  │ 10/min   │      │
│  └──────────┘  └──────────┘  └──────────┘      │
│                                                  │
└─────────────────────────────────────────────────┘
```

### Implementation with Redis

```python
import time
import redis

class RateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
    
    async def acquire(self, app_id: str, shop_id: str, endpoint: str, max_requests: int, window_seconds: int) -> bool:
        key = f"ratelimit:{app_id}:{shop_id}:{endpoint}"
        current = self.redis.get(key)
        
        if current and int(current) >= max_requests:
            return False
        
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        pipe.execute()
        return True
    
    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        key = f"ratelimit:{app_id}:{shop_id}:{endpoint}"
        return self.redis.ttl(key)
```

## Retry & Backoff Strategy

### Exponential Backoff with Jitter

```python
import random
import asyncio

async def call_with_retry(func, max_retries: int = 5):
    for attempt in range(max_retries):
        response = await func()
        
        if response.status_code == 429:
            base_delay = min(2 ** attempt, 60)
            jitter = random.uniform(0, base_delay * 0.5)
            delay = base_delay + jitter
            await asyncio.sleep(delay)
            continue
        
        if response.status_code >= 500:
            await asyncio.sleep(2 ** attempt)
            continue
        
        return response
    
    raise MaxRetriesExceeded(f"Failed after {max_retries} attempts")
```

### Retry Decision Matrix

| Error Code | Action | Retry? |
|------------|--------|--------|
| 429 | Backoff and retry | Yes (with exponential delay) |
| 500/502/503 | Transient server error | Yes (up to 3 times) |
| 401 | Token expired | Refresh token, then retry once |
| 403 | Scope missing | Do not retry, alert |
| 400 | Bad request | Do not retry, fix request |

## Job Queue Design

### Priority Queues

Use a priority-based job queue for API calls:

| Priority | Use Case | Example |
|----------|----------|---------|
| P0 (Immediate) | Webhook-triggered updates | Order detail fetch after ORDER_STATUS_CHANGE |
| P1 (High) | User-initiated actions | Manual inventory sync, ship order |
| P2 (Normal) | Scheduled sync | Hourly product catalog sync |
| P3 (Low) | Backfill/reconciliation | Full inventory audit, historical data |

### Queue Architecture

```
┌─────────────┐     ┌────────────────┐     ┌──────────────────┐
│  Scheduler  │────▶│  Priority Queue│────▶│  Worker Pool     │
│  (Cron)     │     │  (handoff/ETL) │     │  (Rate-Limited)  │
└─────────────┘     └────────────────┘     └──────────────────┘
                           ▲                        │
                           │                        │
                    ┌──────┴──────┐          ┌──────▼──────┐
                    │  Webhook    │          │  TikTok API │
                    │  Handler    │          │             │
                    └─────────────┘          └─────────────┘
```

## Optimization Strategies

### Minimize API Calls

1. **Prefer webhooks** — Use real-time push over polling wherever possible
2. **Batch requests** — Where API supports batch IDs (e.g., order detail accepts multiple IDs)
3. **Cache aggressively** — Product details change rarely; cache with 1-hour TTL
4. **Incremental sync** — Use `update_time_from` filters to fetch only changed records
5. **Conditional requests** — Skip fetch if webhook already provided full data

### Scaling for Many Sellers

With 1000+ sellers, total API calls = sellers × endpoints × frequency:

| Strategy | Description |
|----------|-------------|
| Staggered scheduling | Don't sync all sellers at the same second |
| Adaptive frequency | Sync active sellers more often, dormant ones less |
| Webhook-first | Only poll for initial sync or gap recovery |
| Request coalescing | Group read requests where possible |

### Monitoring

Track these metrics:

- API call volume per shop per hour
- 429 response rate (target: <1%)
- Average retry count per request
- Queue depth and processing latency
- Token bucket utilization per shop
