# KiotViet API Error Handling

## HTTP Status Codes

| Status Code | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad Request - Invalid parameters or business logic error |
| 401 | Unauthorized - Invalid or expired token |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found - Resource does not exist |
| 429 | Too Many Requests - Rate limit exceeded |
| 500 | Internal Server Error - Server-side failure |

## Error Response Format

```json
{
  "responseStatus": {
    "errorCode": "string",
    "message": "string",
    "errors": [
      {
        "errorCode": "string",
        "fieldName": "string",
        "message": "string"
      }
    ]
  }
}
```

## Common Error Scenarios

### Authentication Errors

| Error | Cause | Resolution |
|---|---|---|
| Invalid token | Token expired or malformed | Request a new access token |
| Unauthorized | Missing `Authorization` header | Add `Bearer <token>` header |
| Invalid client | Wrong `client_id` or `client_secret` | Verify credentials |

### Business Logic Errors

| Error Message (Vietnamese) | English Translation | Context |
|---|---|---|
| "Thiết lập 'Cho phép đặt hàng' đang không được bật" | "Allow Orders" setting is not enabled | Orders API requires this setting |
| "Thiết lập 'Sử dụng tính năng giao hàng' đang không được bật" | "Use delivery feature" setting is not enabled | Delivery-related API calls |
| "Thiết lập 'Không cho phép thay đổi thời gian bán hàng' đang không được bật" | "Do not allow changing sale time" setting conflict | Time-related POST/PUT calls |
| "Cập nhật dữ liệu thành công" | Data updated successfully | Success message |
| "Xóa dữ liệu thành công" | Data deleted successfully | Delete success |

### Validation Errors

| Scenario | Response |
|---|---|
| Category name > 125 characters | Validation error |
| Barcode > 16 characters | Validation error |
| Deleting parent category with children | Business logic error |
| Deleting category in use | Business logic error |
| Category depth > 3 levels | Business logic error |

## Error Handling Strategy

### Retry Logic

```python
import time
from enum import IntEnum

class RetryStrategy(IntEnum):
    NO_RETRY = 0
    IMMEDIATE = 1
    BACKOFF = 2

def classify_error(status_code: int) -> RetryStrategy:
    if status_code == 429:
        return RetryStrategy.BACKOFF
    elif status_code >= 500:
        return RetryStrategy.BACKOFF
    elif status_code == 401:
        return RetryStrategy.IMMEDIATE  # refresh token, then retry
    else:
        return RetryStrategy.NO_RETRY
```

### Token Refresh on 401

```python
def handle_unauthorized(client):
    """Re-authenticate and retry the failed request."""
    client.refresh_token()
    # Retry the original request with new token
```

### Rate Limit on 429

```python
def handle_rate_limit(response, attempt: int):
    """Wait and retry when rate limited."""
    wait_time = min(60, 2 ** attempt)  # exponential backoff, max 60s
    time.sleep(wait_time)
```

## Best Practices

1. **Always check HTTP status** before parsing response body.
2. **Log all errors** with request context (URL, params, headers sans secrets).
3. **Distinguish retryable vs. non-retryable** errors.
4. **Implement circuit breakers** for sustained failures.
5. **Validate inputs locally** before sending to API to reduce error responses.
6. **Handle Vietnamese error messages** - map them to your application's error codes.
7. **Token pre-renewal** - refresh tokens before expiry to avoid auth errors mid-operation.
