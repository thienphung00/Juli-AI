# KiotViet API Authentication

## Overview

KiotViet API uses **OAuth 2.0 Client Credentials** flow for authentication. All API calls (except token retrieval) require a valid access token passed in the `Authorization` header.

## Prerequisites

To connect to the KiotViet API, you need two credentials:

| Credential | Description |
|---|---|
| `client_id` | Unique identifier for your API connection (UUID format) |
| `client_secret` | Secret key for authentication (alphanumeric hash) |

These credentials are obtained from the KiotViet admin panel:  
**Settings > Store > API Connection > Edit > Generate Secret Key**

## Token Endpoint

```
POST https://id.kiotviet.vn/connect/token
```

### Request

**Headers:**
```
Content-Type: application/x-www-form-urlencoded
```

**Body (form-urlencoded):**

| Parameter | Value | Description |
|---|---|---|
| `scopes` | `PublicApi.Access` | Access scope for the Public API |
| `grant_type` | `client_credentials` | OAuth 2.0 grant type |
| `client_id` | `<your-client-id>` | Your Client ID (UUID) |
| `client_secret` | `<your-client-secret>` | Your Client Secret |

**Example body:**
```
scopes=PublicApi.Access&grant_type=client_credentials&client_id=e4fe37ab-5d10-4919-bf59-d9a568456d0b&client_secret=01A3703244752CFF6350A801F900742179C7CCDA
```

### Response

```json
{
  "access_token": "<jwt-token>",
  "expires_in": 86400,
  "token_type": "Bearer"
}
```

| Field | Type | Description |
|---|---|---|
| `access_token` | string | JWT token for API authorization |
| `expires_in` | int | Token validity in seconds (default: 86400 = 24 hours) |
| `token_type` | string | Always `"Bearer"` |

## Using the Token

All subsequent API requests must include these headers:

```
Retailer: <your-store-name>
Authorization: Bearer <access_token>
```

**Example:**
```
Retailer: taphoaxyz
Authorization: Bearer eyJhbGciOiJSU0EtT0FFUCIsImVu...Z31gSjq6REOpMUj3hBYBojekzw
```

## Token Refresh Strategy

- Tokens expire after **24 hours** (86400 seconds).
- There is no refresh token mechanism; request a new token using the same client credentials.
- Implement proactive token renewal before expiry to avoid request failures.

## Security Considerations

- The API secret key is only visible to the admin account of the store.
- Admin can control which data is accessible through the API.
- Never expose `client_secret` in client-side code or public repositories.
- Store credentials in environment variables or a secrets manager.

## Deactivating API Access

To temporarily disconnect a third-party system:
1. Navigate to API Connection settings.
2. Click **Edit** > Set status to **Deactivated**.
3. Click **Save** to confirm.
