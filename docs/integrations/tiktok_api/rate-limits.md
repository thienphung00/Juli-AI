# Rate Limits & Throttling

TikTok enforces request quotas per **(app_key × shop)** pair. Exact numeric limits
are **not publicly documented** — calibrate from `100005` responses and Partner
Center guidance.

**Source:** Developer guide (rate limit concepts); implementation:
`src/modules/catalog/domain/integrations/tiktok/rate_limiter.py`

---

## Model

| Dimension | Behavior |
|-----------|----------|
| Bucket key | `(app_id, shop_id, endpoint)` |
| Storage | Redis token bucket (`RateLimiter`) |
| Exhaustion | `RateLimiter.acquire()` → `False`; polling worker logs and skips |
| API signal | Response code `100005` → `RateLimitError` |

> **UNKNOWN — not in official docs:** Per-endpoint tier quotas (orders vs products vs affiliate).
> Monitor production 429/`100005` rates and adjust bucket sizes.

---

## Response when throttled

| Field | Value |
|-------|-------|
| `code` | `100005` |
| Exception | `RateLimitError` |
| Retry | Exponential backoff + jitter |

Optional response headers (when present — **UNVERIFIED** for all endpoints):

| Header | Meaning |
|--------|---------|
| `X-RateLimit-Limit` | Max requests in window |
| `X-RateLimit-Remaining` | Remaining requests |
| `X-RateLimit-Reset` | Unix timestamp when window resets |

---

## Juli throttling strategy

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Cron worker │────▶│ RateLimiter  │────▶│ TikTokClient    │
│ per shop    │     │ (Redis)      │     │ (signed HTTP)   │
└─────────────┘     └──────────────┘     └─────────────────┘
```

### Rules (P2)

1. **Stagger shops** — never sync all shops in the same second (`data-sources.md`).
2. **Webhooks-first** when registered — reduces poll frequency for hot paths.
3. **Priority** (recommended): orders (leakage) > products > affiliate > ads.
4. **Adaptive polling** — reduce frequency for low-activity shops after baseline sync.
5. **Alert** if `100005` rate exceeds 1% of requests per shop per day.

### Default bucket (implementation starting point)

Tune per endpoint after P2 burn-in:

| Endpoint category | Suggested starting window | Notes |
|-------------------|---------------------------|-------|
| Orders search | Conservative | High-frequency tier per TikTok |
| Products search | Moderate | Daily catalog sync |
| Affiliate creators | Moderate | Scope-gated |
| Token refresh | Low volume | Not per-endpoint limited |

Exact `max_requests` / `window_seconds` — set in polling worker wiring; document
chosen values in `MODULE.md` when P2-1 ships.

---

## Signing timestamp constraint

Separate from rate limits: `timestamp` query param must be within **5 minutes** of
sign generation or requests fail auth.

**Source:** [call-get-authorized-shops](https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops)

---

## Multi-tenant fairness

With N shops under one `app_key`, aggregate traffic shares TikTok's per-app limits.
`RateLimiter` isolates per-shop buckets so one noisy shop does not exhaust others'
local tokens — but TikTok-side app caps may still apply (**UNKNOWN** magnitude).

See [multi-tenant.md](multi-tenant.md).
