# Authentication & Authorization

## Overview

TikTok Shop Partner API uses a dual-layer security model:
1. **OAuth 2.0** — Seller authorization and token-based access
2. **HMAC-SHA256 Signing** — Request integrity verification on every API call

Both layers are mandatory. OAuth provides user-level authorization; HMAC proves the request originated from your registered app.

## OAuth 2.0 Flow

### App Registration

| Field | Description |
|-------|-------------|
| App Key | Public identifier for your app |
| App Secret | Private key for signing and token exchange |
| Redirect URI | Where TikTok sends the auth code after consent |
| App Type | `custom` (single seller) or `public` (multi-seller ISV) |

### Authorization Sequence

```
┌──────────┐     ┌─────────────┐     ┌──────────────┐
│  Seller  │     │  Your App   │     │  TikTok API  │
└────┬─────┘     └──────┬──────┘     └──────┬───────┘
     │  1. Click "Connect"│                   │
     │──────────────────▶│                    │
     │                    │ 2. Redirect to     │
     │◀───────────────────│    TikTok OAuth    │
     │                    │                    │
     │  3. Login + Grant  │                    │
     │────────────────────────────────────────▶│
     │                    │                    │
     │                    │ 4. Redirect with   │
     │                    │◀───────────────────│
     │                    │    auth_code       │
     │                    │                    │
     │                    │ 5. Exchange code   │
     │                    │───────────────────▶│
     │                    │                    │
     │                    │ 6. Return tokens   │
     │                    │◀───────────────────│
     │                    │   (access+refresh) │
```

### Token Exchange Request

```
POST /api/v2/token/get
Content-Type: application/json

{
  "app_key": "<APP_KEY>",
  "app_secret": "<APP_SECRET>",
  "auth_code": "<AUTH_CODE>",
  "grant_type": "authorized_code"
}
```

### Token Exchange Response

```json
{
  "data": {
    "access_token": "ROW_xxx...",
    "access_token_expire_in": 604800,
    "refresh_token": "ROW_yyy...",
    "refresh_token_expire_in": 5184000,
    "open_id": "seller_open_id",
    "seller_name": "Shop Name"
  }
}
```

## Token Lifecycle

| Token | TTL | Renewal Strategy |
|-------|-----|-----------------|
| Access Token | 7 days (604,800s) | Refresh before expiry via refresh endpoint |
| Refresh Token | ~60 days (5,184,000s) | If expired, seller must re-authorize |

### Refresh Strategy

Schedule daily token refreshes to maintain a healthy buffer. Never wait until expiration.

```
POST /api/v2/token/refresh
Content-Type: application/json

{
  "app_key": "<APP_KEY>",
  "app_secret": "<APP_SECRET>",
  "refresh_token": "<REFRESH_TOKEN>",
  "grant_type": "refresh_token"
}
```

### Token Storage Requirements

- Encrypt tokens at rest (AES-256 or cloud KMS)
- Store per seller: `shop_id`, `access_token`, `refresh_token`, `expires_at`, `refresh_expires_at`
- Set up automated refresh jobs (cron/scheduler) running daily
- Monitor for `UPCOMING_AUTHORIZATION_EXPIRATION` webhook (fires 30 days before refresh token expiry)
- Handle `SELLER_DEAUTHORIZATION` webhook to invalidate stored tokens immediately

## HMAC-SHA256 Request Signing

Every API call must include a signature computed from request parameters.

### Signing Algorithm

1. Collect all query parameters (excluding `sign` and `access_token`)
2. Sort parameters alphabetically by key
3. Concatenate as `key=value` pairs (no separator between pairs)
4. Prepend the API path (e.g., `/api/orders/search`)
5. Append the request body (if POST with JSON body)
6. Wrap with App Secret: `{app_secret}{canonical_string}{app_secret}`
7. Compute HMAC-SHA256 of the wrapped string using App Secret as key
8. Convert to lowercase hex string

### Pseudocode

```python
import hmac
import hashlib

def sign_request(app_secret: str, path: str, params: dict, body: str = "") -> str:
    sorted_params = sorted(params.items())
    canonical = "".join(f"{k}{v}" for k, v in sorted_params)
    
    sign_string = f"{app_secret}{path}{canonical}{body}{app_secret}"
    
    signature = hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return signature
```

### Required Request Headers/Params

| Parameter | Location | Description |
|-----------|----------|-------------|
| `app_key` | Query | Your App Key |
| `timestamp` | Query | Unix timestamp (seconds) |
| `sign` | Query | HMAC-SHA256 signature |
| `access_token` | Query | OAuth access token |
| `shop_cipher` | Query | Encrypted shop ID (cross-border only) |

## API Scopes

Scopes control which endpoints your app can access. Configure in Partner Center → App Settings.

### Common Scopes

| Scope | Access Granted |
|-------|---------------|
| `shop.authorization` | View authorized shop info |
| `product.basic` | Read/write product listings |
| `order.basic` | Read order information |
| `order.fulfillment` | Manage shipping/tracking |
| `inventory.basic` | Read/write inventory levels |
| `finance.basic` | Read settlement/payment data |
| `affiliate.basic` | Manage affiliate campaigns |
| `message.basic` | Read/send buyer messages |

### Scope Categories

- **Seller scopes** — Access seller-specific shop data
- **Partner scopes** — Partner-level management capabilities
- **Creator scopes** — Creator marketplace interactions

## Implementation Checklist

- [ ] Register app in Partner Center, obtain App Key + Secret
- [ ] Implement OAuth redirect flow with state parameter (CSRF protection)
- [ ] Build token exchange and storage (encrypted DB)
- [ ] Implement automatic daily token refresh job
- [ ] Build HMAC signing utility with canonical string construction
- [ ] Handle auth errors: 401 (bad sign), 403 (expired token), re-auth flows
- [ ] Monitor `SELLER_DEAUTHORIZATION` and `UPCOMING_AUTHORIZATION_EXPIRATION` webhooks
- [ ] Test with sandbox/test shops before production
