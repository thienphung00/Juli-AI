# Architecture Map

Single source of truth for all modules in the Juli-AI codebase. `focus` consults
this first to compute a minimum context-loading set for any task. The `review`
skill verifies that any new module added in a PR is also listed here.

> Update this file whenever you add, rename, remove, or significantly
> restructure a module.

## Module Tier Policy

| Tier | Definition | MODULE.md required? |
|------|-----------|---------------------|
| **1: Core** | Cross-cutting, frequent change, public API surface | **Yes** (eager) |
| **2: Feature** | Domain modules touched by current/upcoming features | **Yes** (lazy — created on first touch) |
| **3: Utility** | Stable, single-purpose, rarely changed | Optional |

## Current Modules

| Module | Tier | Responsibility | Public Surface | Owners |
|--------|------|----------------|----------------|--------|
| [`src/integrations/tiktok`](../../src/integrations/tiktok/MODULE.md) | 1 | TikTok Shop Partner API client (auth, signing, rate limiting, resources) | `TikTokClient`, `TikTokAuth`, `RateLimiter`, `OrdersResource`, `ProductsResource`, `InventoryResource`, `CreatorsResource`, `LivestreamsResource`, `SettlementsResource`, `TikTokAPIError` hierarchy | domain: integrations |
| [`src/services/webhook`](../../src/services/webhook/MODULE.md) | 1 | Receives TikTok webhooks, verifies HMAC signature, publishes raw events to Kafka | `create_app(app_key, app_secret, publish_fn) -> FastAPI` | domain: integrations |
| [`src/services/polling`](../../src/services/polling/MODULE.md) | 2 | Background polling sync workers (orders, products, inventory) | `sync_orders`, `sync_products`, `sync_inventory` | domain: integrations |
| [`src/data`](../../src/data/MODULE.md) | 1 | Persistence layer: SQLAlchemy async models, repos, Alembic migrations | `User`, `Shop`, `TikTokCredential`, `Order`, `Product`, `InventoryItem`, `Settlement`, `Creator`, `Livestream`, `AlertConfig`, `AlertHistory`, `Recommendation`, `UsersRepo`, `ShopsRepo`, `TikTokCredentialRepo`, `ShopScopedRepo[T]`, `OrdersRepo`, `ProductsRepo`, `InventoryRepo`, `SettlementsRepo`, `CreatorsRepo`, `LivestreamsRepo`, `AlertConfigsRepo`, `AlertHistoryRepo`, `RecommendationsRepo`, `Base`, `NotFound`, `get_session`, `init_session_factory` | domain: data |
| [`src/auth`](../../src/auth/MODULE.md) | 1 | Supabase phone-OTP login, JWT verification, TikTok OAuth lifecycle, FastAPI auth dependency | `SupabaseAuth`, `TikTokOAuthService`, `verify_supabase_jwt`, `get_current_user`, `Unauthorized` | domain: auth |
| [`src/api`](../../src/api/MODULE.md) | 1 | FastAPI REST API with versioned routing, auth middleware, shop-scoped endpoints | `create_app`, `get_active_shop`, `GET /v1/shops`, `GET /v1/shops/me` | domain: api |
| [`ios`](../../ios/MODULE.md) | 2 | Native SwiftUI iOS app: Supabase phone-OTP auth, JWT Keychain storage, shop selection, daily value loop navigation shell | `AuthService`, `KeychainService`, `APIClient`, `OfflineCacheService`, `DailyLoopTab` | domain: ios |
| [`src/intelligence/scoring`](../../src/intelligence/scoring/MODULE.md) | 2 | Post-stream livestream scoring, anomaly detection, retention curves, Vietnamese comment sentiment | `score_livestream`, `detect_anomalies`, `get_stream_retention`, `analyze_comments`, `LivestreamScore`, `Anomaly`, `RetentionPoint`, `SentimentResult` | domain: intelligence |
| [`src/intelligence/forecasting`](../../src/intelligence/forecasting/MODULE.md) | 2 | SKU inventory depletion forecasting, low-stock risk ranking, velocity change detection | `get_forecast`, `get_low_stock_risks`, `get_velocity_changes`, `ForecastResult`, `LowStockRisk`, `VelocityChange` | domain: intelligence |
| [`src/recommendations`](../../src/recommendations/MODULE.md) | 2 | Rule-based product push suggestions (trend + stock + margin), plain Vietnamese CTAs | `get_product_push_suggestions`, `ProductPushSuggestion` | domain: recommendations |
| [`src/etl`](../../src/etl/MODULE.md) | 1 | Kafka consumer: dedup by event_id, transform, persist via data repos, DLQ on failure | `EtlConsumer.ingest`, `KafkaRecord`, `ProcessOutcome` | domain: data |
| [`src/alerts`](../../src/alerts/MODULE.md) | 2 | Per-shop alert rules, cooldown dedup, pluggable channel delivery (FCM MVP) | `evaluate_rules`, `configure_rules`, `deliver_alert`, `FcmAdapter`, `ChannelAdapter`, `Alert`, `AlertEvent` | domain: alerts |
| [`web`](../../web/MODULE.md) | 2 | Next.js web dashboard: phone-OTP login, homepage, orders management | `/login`, `/`, `/orders` | domain: web |

## Dependency Graph

```
┌──────────────────────────────────────────────────────────────┐
│                 src/integrations/tiktok                       │
│  ┌─────────┐  ┌────────┐  ┌──────────┐  ┌──────────────┐    │
│  │ signing │  │  auth  │  │  client  │  │ rate_limiter │    │
│  └─────────┘  └────────┘  └────┬─────┘  └──────────────┘    │
│       │           │            │                 │            │
│       └───────────┴────────────┘                 │            │
│                                │                 │            │
│                       ┌────────┴────────┐        │            │
│                       │   resources/    │        │            │
│                       │  orders         │        │            │
│                       │  products       │        │            │
│                       │  inventory      │        │            │
│                       └─────────────────┘        │            │
└──────────────────────────────────────────────────┼───────────┘
                                                   │
                  ┌────────────────────────────────┴────────┐
                  │                                          │
        ┌─────────▼──────────┐              ┌───────────────▼──────────┐
        │ src/services/      │              │  src/services/polling    │
        │     webhook        │              │  (sync_orders,           │
        │  (FastAPI receiver)│              │   sync_products,         │
        │                    │              │   sync_inventory)        │
        └─────────┬──────────┘              └───────────────┬──────────┘
                  │                                          │
                  └──────────────┬───────────────────────────┘
                                 │
                          ┌──────▼──────┐
                          │    Kafka    │
                          │ (raw topics)│
                          └──────┬──────┘
                                 │
                          ┌──────▼──────┐
                          │  src/etl    │
                          │ (consumer)  │
                          └──────┬──────┘
                                 │
                          ┌──────▼──────┐
                          │  src/data   │◄─── src/auth
                          │ (Supabase)  │◄─── src/api
                          └──────┬──────┘◄─── src/intelligence/scoring
                                 │          ◄─── src/intelligence/forecasting
                                 │          ◄─── src/recommendations
                                 │          ◄─── src/alerts
                                 │
                          ┌──────▼──────┐
                          │   src/api   │◄─── ios (HTTP)
                          │  (FastAPI)  │◄─── web (HTTP)
                          └─────────────┘
```

## Layer Reference

| Layer | Purpose | Current Modules | Stack |
|-------|---------|-----------------|-------|
| Integrations | External API clients, OAuth, signing | `src/integrations/*` | Python / httpx |
| Services | Long-running processes (receivers, workers, APIs) | `src/services/*` | Python / FastAPI / Celery |
| Intelligence | Post-stream scoring, forecasting, anomaly detection, sentiment analysis | `src/intelligence/scoring`, `src/intelligence/forecasting` | Python / SQLAlchemy (read-only) |
| Data | Supabase Postgres, migrations, query layer | `src/data` | Supabase / SQLAlchemy / asyncpg / Alembic |
| Interface | Web dashboard + iOS app | `web`, `ios` | Next.js (web) / SwiftUI (iOS) |
| Alerts | Multi-channel alert delivery | `src/alerts` | FCM (MVP); Zalo OA (#40) |
| Infrastructure (planned) | Deployment configs, CI/CD | _none yet_ | Railway / Vercel / GitHub Actions |

### Key Architectural Decisions

- **Backend:** Python / FastAPI only — no Node.js/NestJS (see [ADR-001](../decisions/001-keep-python-fastapi.md))
- **Database:** Supabase (managed Postgres + Auth + Realtime + Storage) (see [ADR-002](../decisions/002-supabase-backend-service.md))
- **Auth:** Supabase Auth (phone-OTP, JWT) — FastAPI validates tokens via middleware
- **iOS:** Native Swift / SwiftUI alongside web dashboard
- **Data Sources:** TikTok Shop Official API is the only authoritative
  source in MVP. Unofficial livestream websockets and Seller Center
  scraping are explicitly forbidden. The full source-by-source matrix
  with MVP / v1.5 / out-of-scope status lives in
  [`data-sources.md`](data-sources.md) — `discover`, `focus`, and
  `review` must consult it before proposing work that depends on any
  external data.

## Adding a New Module

When `build-feature` introduces a new module:

1. Create `<module-path>/MODULE.md` following the template in
   [focus/SKILL.md](../../.cursor/skills/standalone/focus/SKILL.md)
2. Add a row to the "Current Modules" table above
3. Update the dependency graph if it changes
4. Commit all three changes together with the feature

## Removing a Module

When deleting a module:

1. Remove the row from "Current Modules"
2. Update the dependency graph
3. Search for and remove `MODULE.md` references in dependent modules
4. Run `review` to surface any callers that still depend on it
