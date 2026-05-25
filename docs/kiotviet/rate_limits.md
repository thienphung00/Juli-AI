# KiotViet API Rate Limits

## Overview

KiotViet enforces rate limits to protect the API infrastructure and ensure fair usage across all integrators.

## Rate Limit Rules

| Method | Limit | Window |
|---|---|---|
| GET requests | 5,000 requests | Per hour |
| POST/PUT/DELETE | Not explicitly documented | Use conservatively |

## Handling Rate Limits

### Detection

When the rate limit is exceeded, the API will return an error response. Implement detection logic for HTTP 429 (Too Many Requests) or equivalent error responses.

### Retry Strategy

1. **Exponential backoff**: Start with 1 second delay, double on each retry.
2. **Jitter**: Add random delay (0-500ms) to prevent thundering herd.
3. **Max retries**: Cap at 3-5 attempts before failing.

```python
import time
import random

def retry_with_backoff(func, max_retries=5, base_delay=1.0):
    for attempt in range(max_retries):
        try:
            return func()
        except RateLimitError:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            time.sleep(delay)
```

### Best Practices

1. **Cache responses**: Avoid redundant GET calls by caching data locally.
2. **Use `lastModifiedFrom`**: Fetch only changed records since last sync.
3. **Batch operations**: Use bulk endpoints (`listaddproducts`, `listupdatedproducts`) instead of individual calls.
4. **Respect `pageSize`**: Use appropriate page sizes (max 100) to minimize total requests.
5. **Off-peak syncing**: Schedule heavy sync operations during low-traffic hours.

## Request Budget Planning

With 5,000 GET requests per hour:
- ~83 requests per minute
- ~1.4 requests per second

Plan your sync frequency and data volume accordingly.

## Pagination Impact on Rate Limits

Each paginated page counts as a separate request. For a resource with 1,000 items at `pageSize=100`:
- 10 requests consumed for full list retrieval
- Consider whether full sync is needed vs. incremental (`lastModifiedFrom`)
