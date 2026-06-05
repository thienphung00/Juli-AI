# Tech Stack & Storage

Recommended boundaries for TikTok integration in Juli-AI.

---

## Client layer

| Component | Module | Notes |
|-----------|--------|-------|
| HTTP transport | `requests` (sync) | `TikTokClient` — consider `httpx` async in future |
| Signing | `signing.sign_request` | HMAC-SHA256 per official algorithm |
| OAuth | `TikTokAuth` | No persistence in client module |
| Rate limiting | `RateLimiter` + Redis | Required for P2 multi-shop |
| Resources | `resources/*.py` | Thin wrappers — no business logic |

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TIKTOK_APP_KEY` | P2 | Partner Center App Key |
| `TIKTOK_APP_SECRET` | P2 | App Secret (signing + webhook verify) |
| `TIKTOK_REDIRECT_URI` | P2 | OAuth callback URL |
| `TIKTOK_BASE_URL` | Optional | Default `https://open-api.tiktokglobalshop.com` |
| `REDIS_URL` | P2 | Rate limiter buckets |

Secrets via env / secrets manager — never commit.

---

## Persistence touchpoints

| Juli model | TikTok source fields | Repo |
|------------|---------------------|------|
| `Shop` | `id`, `cipher`, `name`, `region` | `ShopsRepo` |
| `TikTokCredential` | `access_token`, `refresh_token`, expiry | `TikTokCredentialRepo` |
| `Product` | `products[].id`, audit status, timestamps | Product repo |
| `Order` | order search/detail payloads | Order repo |
| `Creator` | affiliate creator id, metrics | Creator repo |

Encrypt tokens at rest in `TikTokCredentialRepo`. Log only `shop_id` / `request_id` —
never tokens or buyer PII.

---

## Official SDKs (reference only)

Juli implements a Python client; official SDKs useful for path/schema verification:

| SDK | Source |
|-----|--------|
| Java | [integrate-java-sdk](https://partner.tiktokshop.com/docv2/page/integrate-java-sdk) |
| Node.js | [integrate-node-js-sdk](https://partner.tiktokshop.com/docv2/page/integrate-node-js-sdk) |

Do not add Java/Node SDKs to production runtime — Python client is canonical.

---

## DB field mapping (orders — partial)

> Full schema **UNKNOWN** until Partner Center order API reference is extracted.

| TikTok field (illustrative) | Juli field | Notes |
|----------------------------|------------|-------|
| `order_id` | `Order.external_id` | |
| `buyer_id` | masked reference | No PII |
| `update_time` | `Order.updated_at` | Incremental sync key |
| `status` | `Order.status` | Leakage / return detection |
| `total_amount` | GMV signals | Settlement may lag |

---

## Testing

| Suite | Path |
|-------|------|
| OAuth | `tests/unit/test_tiktok_oauth.py` |
| Signing | `tests/unit/test_tiktok_signing.py` (if present) |
| Integration | Mock TikTok responses — no live API in CI |

Phase 2 adds contract tests against recorded fixtures from API Testing Tool.
