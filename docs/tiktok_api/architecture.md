# Integration Architecture

How TikTok Shop Open API data flows into Juli-AI, mapped to deployed `backend/` modules.

**Authority:** [`EXECUTION.md`](../../EXECUTION.md) Phase 2 for live wiring; Phase 1
uses mock fixtures only.

---

## Data flow

```
┌──────────────────────┐
│ TikTok Shop Open API │
└──────────┬───────────┘
           │ OAuth + signed REST
           ▼
┌──────────────────────────────────────────────────────────┐
│ backend/integrations/catalog/domain/integrations/tiktok/ │
│   TikTokAuth, TikTokClient, RateLimiter, *Resource       │
└──────────┬─────────────────────────────┬─────────────────┘
           │ polling                     │ webhooks (optional)
           ▼                             ▼
┌──────────────────────────┐   ┌─────────────────────────────┐
│ backend/workers/services/│   │ backend/api/services/       │
│   polling/               │   │   webhook/                  │
│   sync_orders,           │   │   POST /webhooks/tiktok     │
│   sync_products,         │   └──────────────┬──────────────┘
│   sync_creators          │                  │
└──────────┬───────────────┘                  │
           │ handoff_fn(channel, shop_id, bytes)
           ▼
┌──────────────────────────────────────────────────────────┐
│ backend/integrations/ordering/use_cases/etl/             │
│   EtlConsumer.ingest — dedup, transform, DLQ             │
└──────────┬───────────────────────────────────────────────┘
           ▼
┌──────────────────────────────────────────────────────────┐
│ backend/database/ — Shop-scoped repos                    │
└──────────┬───────────────────────────────────────────────┘
           ▼
┌──────────────────────────────────────────────────────────┐
│ Daily rules pipeline (P2, 08:00 UTC) + rules copy      │
│ web/ — three seller-money workflows                      │
└──────────────────────────────────────────────────────────┘
```

---

## Module map

| Concern | Path | Responsibility |
|---------|------|----------------|
| API client | `backend/integrations/catalog/domain/integrations/tiktok/` | Auth, signing, rate limit, resources |
| OAuth persistence | `backend/integrations/identity/infrastructure/auth/tiktok_oauth.py` | Token encrypt/store/refresh |
| Webhook receiver | `backend/api/services/webhook/` | HMAC verify, ACK, handoff |
| Polling workers | `backend/workers/services/polling/` | Scheduled sync per shop |
| Ingest handoff | `backend/integrations/ordering/api/ingestion/handoff.py` | `make_etl_handoff` wiring |
| ETL consumer | `backend/integrations/ordering/use_cases/etl/` | Dedup, persist, DLQ |
| Persistence | `backend/database/` | `Shop`, `Product`, `Order`, `Creator` repos |
| REST API | `backend/api/api/` | `/v1/*` seller-facing reads |

---

## P2 polling scope (EXECUTION.md)

| Worker | Resource | Phase | Workflow |
|--------|----------|-------|----------|
| `sync_orders` | `OrdersResource` | P2 | Revenue Leakage Detection |
| `sync_products` | `ProductsResource` | P2 | Growth Copilot / catalog context |
| `sync_creators` | `CreatorsResource` | P2 | Affiliate fraud signals |
| Ads polling | **TBD** | P2 | Growth Copilot — not implemented |

**Out of P2 / pending removal** (`map.md`): `sync_inventory`, `sync_settlements`,
`sync_livestreams`.

---

## Retry strategy

| Error | Action |
|-------|--------|
| `RateLimitError` (100005) | Backoff; skip cycle if bucket empty |
| `TikTokSystemError` (100006) | Retry with jitter (max 3) |
| `AuthenticationError` (100002) | Refresh token; re-auth if refresh fails |
| `PermissionDeniedError` (100003) | Affiliate: surface re-consent; do not retry blindly |

---

## Idempotency

| Layer | Key |
|-------|-----|
| ETL | `event_id` dedup |
| DB writes | Upsert on `external_id` + `update_time` |
| Webhooks | Duplicate delivery expected |
| Polling | `update_time_from` incremental windows |

---

## Caching

| Data | Cache | TTL |
|------|-------|-----|
| Access token | Postgres (`TikTokCredential`) | Until `access_token_expire_in` |
| Rate limit buckets | Redis | Per `RateLimiter` window |
| API responses | None in MVP client | Raw JSONB optional in ETL |

Phase 3+ Redis pub/sub for UI refresh is **Later** — not P2.

---

## Phase gating

| Phase | TikTok integration |
|-------|-------------------|
| P1 | `TikTokClient` must not be called from production UI paths — mock only |
| Phase 2 MVP Milestone A | Offline parquet only |
| P2 | Enable polling + daily inference |

CI should fail if real API calls are introduced before Phase 2 gate passes.
