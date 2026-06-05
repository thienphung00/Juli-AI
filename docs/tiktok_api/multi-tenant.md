# Multi-Tenant Architecture

Juli is multi-shop: one ISV app (`app_key`) serves many seller shops, each with
isolated credentials, rate-limit buckets, and data scope.

---

## Identity model

```
User (Supabase phone-OTP)
  └── Shop (1..N per user)
        ├── tiktok_shop_id   ← TikTok `shops[].id`
        ├── shop_cipher      ← TikTok `shops[].cipher`
        ├── region           ← market-specific rules
        └── TikTokCredential (encrypted access + refresh tokens)
```

**OAuth:** One authorization may return multiple shops ([get authorized shops](https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops)).
`TikTokOAuthService` provisions a `Shop` row per authorized shop.

---

## Request scoping

Every signed API call includes:

| Param | Source |
|-------|--------|
| `app_key` | Juli ISV app (env) |
| `access_token` | Per-shop credential |
| `shop_cipher` | Per-shop field |

`TikTokClient(shop_cipher=...)` injects cipher into query params.

---

## Isolation rules

| Layer | Enforcement |
|-------|-------------|
| API (`/v1/*`) | `get_active_shop` — JWT user → active shop only |
| Repos | `shop_id` filter on all queries (`src/shared/utils/data`) |
| Polling | One worker context per `(app_id, shop_id)` |
| Rate limiter | Bucket per `(app_id, shop_id, endpoint)` |
| ETL handoff | `shop_id` = TikTok shop id for partition key |
| Webhooks | `shop_id` in payload routes to correct shop partition |

---

## Cross-region

Shops carry a `region` field (e.g. US, UK, SEA markets). API behavior and policy
may vary by region (**REGION-VARIANT** — confirm via `platform-docs` skill).

Juli stores region on `Shop` but does not route to different base URLs in the
current client — single `open-api.tiktokglobalshop.com` endpoint.

---

## Deauthorization

When a seller revokes app access:

1. Stop polling jobs for that `shop_id`.
2. Mark credential invalid in `TikTokCredentialRepo`.
3. Surface re-auth banner in `web/`.

Webhook event name for deauthorization — **UNKNOWN** until confirmed in Partner
Center webhook docs. Handle `AuthenticationError` on sync as fallback detection.

---

## Staggered sync

Never enqueue all shops at the same cron second. Recommended:

```
shop_index * stagger_seconds  (e.g. 2–5s between shops)
```

Prevents correlated `100005` storms and respects TikTok per-app aggregate limits.
