# Authentication

OAuth 2.0 authorization-code flow for seller consent, plus HMAC-SHA256 signing on
every Open API call.

**Sources:**
- [TikTok Shop Developer Guide](https://partner.tiktokshop.com/docv2/page/tts-developer-guide)
- [Call Get Authorized Shops](https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops)
- [Sign your API request](https://partner.tiktokshop.com/docv2/page/sign-your-api-request)
- Implementation: `src/modules/catalog/domain/integrations/tiktok/auth.py`, `signing.py`

---

## OAuth 2.0 flow

```
Seller → Partner Center consent URL → redirect with auth_code
      → POST /api/v2/token/get → access_token + refresh_token
      → GET /authorization/202309/shops → shop list + shop_cipher
      → Signed API calls with access_token + shop_cipher
```

### Step 1 — Authorization URL

| Field | Value |
|-------|-------|
| URL | `https://services.tiktokshop.com/open/authorize` |
| Query params | `app_key`, `redirect_uri`, `state` |

Implemented in `TikTokAuth.generate_auth_url()`.

**Source:** `auth.py` + Partner Center OAuth docs (developer guide).

### Step 2 — Exchange auth code

| Field | Value |
|-------|-------|
| Method | `POST` |
| Path | `/api/v2/token/get` |
| Base URL | `https://open-api.tiktokglobalshop.com` |

**Request body:**

| Field | Type | Required |
|-------|------|----------|
| `app_key` | string | Yes |
| `app_secret` | string | Yes |
| `auth_code` | string | Yes |
| `grant_type` | string | Yes — `"authorized_code"` |

**Response `data` (observed in tests):**

| Field | Type | Notes |
|-------|------|-------|
| `access_token` | string | Shop-scoped API token |
| `refresh_token` | string | Rotate before access expiry |
| `access_token_expire_in` | integer | Seconds until expiry (604800 = 7d in test fixtures) |
| `open_id` | string | Seller identifier |
| `seller_name` | string | Display name |

**Source:** `tests/unit/test_tiktok_oauth.py`, `TikTokAuth.exchange_code()`.

### Step 3 — Refresh token

| Field | Value |
|-------|-------|
| Method | `POST` |
| Path | `/api/v2/token/refresh` |

**Request body:**

| Field | Type | Required |
|-------|------|----------|
| `app_key` | string | Yes |
| `app_secret` | string | Yes |
| `refresh_token` | string | Yes |
| `grant_type` | string | Yes — `"refresh_token"` |

Refresh returns a new access + refresh pair. `TikTokOAuthService.refresh_tokens()`
in `src/modules/identity/infrastructure/auth/tiktok_oauth.py` persists encrypted
credentials via `TikTokCredentialRepo`.

**Operational rule:** refresh proactively before expiry (tests refresh when within
24h of expiration).

---

## Authorized shops

After OAuth, resolve which shops the token can access.

| Field | Value |
|-------|-------|
| Method | `GET` |
| Path | `/authorization/202309/shops` |
| Header | `x-tts-access-token: <access_token>` |
| Header | `Content-Type: application/json` |
| Query | `app_key`, `sign`, `timestamp` |

**Response `data.shops[]`:**

| Field | Juli mapping | Notes |
|-------|--------------|-------|
| `id` | `Shop.tiktok_shop_id` | Primary shop key for webhooks + ETL |
| `cipher` | `Shop.shop_cipher` | Required on most shop-scoped API calls |
| `name` | `Shop.name` | |
| `region` | `Shop.region` | Market-specific behavior |
| `code` | — | Shop code |
| `seller_type` | — | Seller classification |

**Source:** [call-get-authorized-shops](https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops)

---

## Request signing (HMAC-SHA256)

Every Open API call includes signed query parameters.

### Required query parameters

| Param | Description |
|-------|-------------|
| `app_key` | App Key from Partner Center |
| `timestamp` | Unix epoch seconds — must be within **5 minutes** of sign creation |
| `access_token` | Current OAuth access token |
| `shop_cipher` | Shop cipher (when endpoint is shop-scoped) |
| `sign` | HMAC-SHA256 signature (computed last) |

### Signature algorithm

Implemented in `sign_request()` (`signing.py`):

1. Exclude `sign` and `access_token` from the canonical param string.
2. Sort remaining params alphabetically by key.
3. Concatenate as `key1value1key2value2...` (no separator).
4. Build sign string: `{app_secret}{path}{canonical}{body}{app_secret}`.
5. HMAC-SHA256 with `app_secret` as key → lowercase hex digest.

POST bodies are JSON with sorted keys, no spaces: `json.dumps(body, separators=(",", ":"), sort_keys=True)`.

**Source:** [sign-your-api-request](https://partner.tiktokshop.com/docv2/page/sign-your-api-request), `signing.py`.

### Common auth failures

| Symptom | Likely cause |
|---------|--------------|
| Auth error (code 100002) | Expired token, bad signature, stale timestamp (>5 min) |
| Permission denied (100003) | Missing scope (common for Affiliate endpoints) |
| Invalid `x-tts-access-token` | Token/header mismatch on versioned GET routes |

---

## Scopes and entity tags

Partner Center groups endpoints by **entity tag** (seller, shop, partner, creator,
asset) indicating authorization boundaries.

**Source:** [api-entity-tags](https://partner.tiktokshop.com/docv2/page/api-entity-tags)

| Juli resource | Scope notes |
|---------------|-------------|
| Orders, Products | Standard shop token — P2 core |
| Affiliate (creators, livestreams) | Per-seller scope approval required |
| Finance / settlements | Shop token; values pending 7–14d |
| Ads | **P2 scope** per `EXECUTION.md` — endpoint paths **UNKNOWN** in current client |

Affiliate `PermissionDeniedError` (100003) should surface re-consent UX, not silent failure.

---

## Credential storage

| Concern | Owner module |
|---------|--------------|
| OAuth URL + code exchange | `TikTokAuth` |
| Encrypted token persistence | `TikTokOAuthService` + `TikTokCredentialRepo` |
| Per-request signing | `TikTokClient` + `sign_request` |

`TikTokAuth` does **not** persist tokens — storage is the identity/persistence layer.

**Env vars:** `TIKTOK_APP_KEY`, `TIKTOK_APP_SECRET`, `TIKTOK_REDIRECT_URI`, `TIKTOK_BASE_URL` (optional override).
