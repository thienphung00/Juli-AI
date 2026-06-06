# Architecture Map

**As-built source of truth for what is deployed** in the Juli-AI codebase —
modules, polling jobs, API schemas, endpoints. `focus` consults this first to
compute a minimum context-loading set for any task. The `review` skill verifies
that any new module added in a PR is also listed here.

> Update this file whenever you add, rename, remove, or significantly restructure
> a module. For the plan that drives changes see [`../../EXECUTION.md`](../../EXECUTION.md);
> for technical design see [`../system-design.md`](../system-design.md).
>
> **Authority:** `EXECUTION.md` > `system-design.md` > this file. This file describes
> **reality as deployed**, not the target.

## North star

Juli-AI helps TikTok Shop sellers **make and keep more money** through three
agentic workflows — **New Seller Copilot**, **Revenue Leakage Detection**, and
**Growth Copilot**. Built UI-first (Phase 1), then ML (Phase 1.5), then live data
(Phase 2). See [`../../EXECUTION.md`](../../EXECUTION.md).

**What we build:** seller-money workflows — get to first profitable sales, stop
revenue leakage (buyer return anomalies: item swap, empty return; plus policy-driven refunds/disputes), grow ad ROAS.

**What we do _not_ build:** generic analytics dashboards, CRM, inventory/finance/
settlement software, or creator↔shop matching (Phase 3+, see ADR history).

## Code layout (actual)

The backend is a modular monolith under `src/`. **No folder reshaping until Phase
2.5** — `src/apps` + `src/modules` stays as-is.

```
src/
├── apps/                         # Deployable entrypoints (composition only)
│   ├── api_gateway/
│   │   ├── api/                  # FastAPI /v1 routers + app factory
│   │   └── services/webhook/     # TikTok webhook receiver (HMAC → ETL)
│   └── cron_jobs/services/polling/   # Scheduled sync workers
├── modules/                      # Domain modules (business logic)
│   ├── identity/                 # Auth: Supabase phone-OTP, JWT, TikTok OAuth
│   ├── catalog/domain/
│   │   ├── integrations/tiktok/  # TikTok Shop Partner API client
│   │   └── recommendations/      # Decision/recommendation generation
│   └── ordering/                 # Ingestion handoff + ETL (data accumulation)
└── shared/utils/data/            # SQLAlchemy models, repos, DB session
```

Frontends live in `web/` (Next.js) and `ios/` (SwiftUI).

## Module tier policy

| Tier | Definition | MODULE.md required? |
|------|-----------|---------------------|
| **1: Core** | Cross-cutting, frequent change, public API surface | **Yes** (eager) |
| **2: Feature** | Domain modules touched by current/upcoming features | **Yes** (lazy — created on first touch) |
| **3: Utility** | Stable, single-purpose, rarely changed | Optional |

## Current modules

| Module | Tier | Responsibility | Public Surface | Owners |
|--------|------|----------------|----------------|--------|
| [`src/modules/catalog/domain/integrations/tiktok`](../../src/modules/catalog/domain/integrations/tiktok/MODULE.md) | 1 | TikTok Shop Partner API client (auth, signing, rate limiting, resources) | `TikTokClient`, `TikTokAuth`, `RateLimiter`, `CreatorsResource`, `ProductsResource`, `OrdersResource`, `InventoryResource`, `LivestreamsResource`, `SettlementsResource`, `TikTokAPIError` hierarchy | domain: integrations |
| [`src/modules/ordering/api/ingestion`](../../src/modules/ordering/api/ingestion/MODULE.md) | 1 | Ingest handoff contracts and `make_etl_handoff` wiring | `HandoffFn`, `make_etl_handoff` | domain: data |
| [`src/apps/api_gateway/services/webhook`](../../src/apps/api_gateway/services/webhook/MODULE.md) | 1 | Receives TikTok webhooks, verifies HMAC signature, hands validated payloads to ETL | `create_app(..., handoff_fn) -> FastAPI` | domain: integrations |
| [`src/apps/cron_jobs/services/polling`](../../src/apps/cron_jobs/services/polling/MODULE.md) | 2 | Background polling sync workers (seller signal collection) | `sync_creators`, `sync_products`, `sync_orders`, `backfill_shop` | domain: integrations |
| [`src/shared/utils/data`](../../src/shared/utils/data/MODULE.md) | 1 | Persistence layer: SQLAlchemy async models, repos, Alembic migrations | `User`, `Shop`, `Creator`, `Product`, `Recommendation`, … repos, `Base`, `NotFound`, `get_session` | domain: data |
| [`src/modules/identity/infrastructure/auth`](../../src/modules/identity/infrastructure/auth/MODULE.md) | 1 | Supabase phone-OTP login, JWT verification, TikTok OAuth lifecycle, FastAPI auth dependency | `SupabaseAuth`, `TikTokOAuthService`, `verify_supabase_jwt`, `get_current_user`, `Unauthorized` | domain: auth |
| [`src/apps/api_gateway/api`](../../src/apps/api_gateway/api/MODULE.md) | 1 | FastAPI REST API (`/v1/*`): auth, shops, creators, products, recommendations | `create_app`, `get_active_shop`, `GET /v1/shops`, `GET /v1/creators`, `GET /v1/products`, `GET /v1/recommendations` | domain: api |
| [`src/modules/catalog/domain/recommendations`](../../src/modules/catalog/domain/recommendations/MODULE.md) | 2 | Decision generation: seller-action suggestions with justification + CTA | `get_host_product_matching`, `get_product_push_suggestions`, `get_stream_optimization` | domain: recommendations |
| [`src/modules/ordering/use_cases/etl`](../../src/modules/ordering/use_cases/etl/MODULE.md) | 1 | Ingestion consumer: dedup by event_id, transform, persist via data repos, DLQ on failure | `EtlConsumer.ingest`, `IngestRecord`, `ProcessOutcome` | domain: data |
| [`web`](../../web/MODULE.md) | 2 | Next.js web app — UI for the three seller-money workflows (mock data in Phase 1) | `/login`, `/`, workflow pages | domain: web |
| [`ios`](../../ios/MODULE.md) | 2 | Native SwiftUI iOS app: Supabase phone-OTP auth, JWT Keychain storage, shop selection | `AuthService`, `KeychainService`, `APIClient` | domain: ios |
| [`src/modules/ml/dataset`](../../src/modules/ml/dataset/MODULE.md) | 2 | Phase 1.5 backtest parquet assembly: synthetic data, schema validation, manifest | `assemble_backtest_dataset`, `validate_backtest_dataset`, `DatasetValidationError` | domain: ml |
| [`src/modules/ml/features`](../../src/modules/ml/features/MODULE.md) | 2 | Phase 1.5 feature engineering: parquet → per-model feature matrices | `build_seller_stage_features`, `build_anomaly_features`, `build_ad_features`, `FeatureMatrix` | domain: ml |
| [`src/modules/ml/seller_stage`](../../src/modules/ml/seller_stage/MODULE.md) | 2 | Phase 1.5 seller lifecycle classifier: rules baseline, train, rules-vs-ML compare | `classify_seller_stage`, `train_seller_stage`, `predict_seller_stage`, `compare_to_rules_baseline` | domain: ml |

## Pending cleanup (tracked in EXECUTION.md)

These remain in the tree but are **out of scope** for Phase 1–2 and slated for
removal. Deleting code is sequenced after the docs rescope (not part of the first
PR) to avoid breaking imports/tests:

| Target | Why | Status |
|--------|-----|--------|
| `src/modules/catalog/domain/intelligence/**` | Legacy creator-matching/livestream scoring — not a seller-money workflow | Remove (verify no live callers first) |
| Polling: `sync_inventory`, `sync_settlements`, `sync_livestreams` | Inventory/finance/livestream-ops not in Phase 1–2 scope | Remove from polling workers |

> Already removed in an earlier pass: API routers `analytics`, `settlements`,
> `inventory`, `orders`, `livestreams`, `alerts`; the `catalog/domain/alerts`
> module; matching-specific web pages.

## Key architectural decisions

- **Backend:** Python / FastAPI only ([ADR-001](../decisions/001-keep-python-fastapi.md))
- **Database:** Supabase (managed Postgres + Auth) — source of truth ([ADR-002](../decisions/002-supabase-backend-service.md))
- **Auth:** Supabase Auth (phone-OTP, JWT) — FastAPI validates tokens
- **Data sources:** TikTok Shop Official API only. Unofficial livestream websockets,
  Seller Center scraping, and buyer PII storage are **permanently forbidden**. See
  [`data-sources.md`](data-sources.md).
- **Data model:** Canonical entity schemas and ML features live in
  [`docs/data-models/`](../data-models/README.md). TikTok API docs (`tiktok_api/endpoints.md`)
  are the ingestion layer only ([ADR-012](../decisions/012-entity-centric-data-model.md)).
- **Platform policy:** Seller/creator feature guides and policy center rules live in
  [`docs/tiktok_platform/`](../tiktok_platform/README.md). Implementation hooks
  (`seller/implementation-hooks.md`, `creator/implementation-hooks.md`) define alerts,
  gates, and ETL behavior for Phase 2 workflows.
- **Runtime evolution:** simple daily scheduler in Phase 2; **no** Celery/Kafka
  (Phase 3+, see [`../../EXECUTION.md`](../../EXECUTION.md) → Explicitly out).

> **Platform policy (Phase 2):** [ADR-008](../decisions/008-alert-vp-ahr-milestones.md)
> (milestone alerts), [ADR-009](../decisions/009-dual-read-vp-ahr-transition.md)
> (VP→AHR dual-read), [ADR-010](../decisions/010-vn-regional-platform-config.md)
> (VN regional thresholds).
>
> **Anomaly ML scope (Phase 1.5):** [ADR-011](../decisions/011-buyer-behavior-anomaly-scope.md)
> — buyer return anomalies (`item_swap`, `empty_return`) only; schema in
> [`data-models/canonical-entities.md`](../data-models/canonical-entities.md) § Return, § OrderItem.
>
> **Entity-centric data model:** [ADR-012](../decisions/012-entity-centric-data-model.md)
> — `docs/data-models/` is ML schema authority; `tiktok_api/endpoints.md` is ingestion only.
>
> **Historical decisions:** [ADR-006](../decisions/006-matching-pivot.md) (creator↔shop
> matching pivot) and [ADR-007](../decisions/007-ml-north-star-models.md) (north-star
> ML models) are **superseded** by the seller-money rescope in `EXECUTION.md`. Kept
> as ADR history only.

## Adding / removing a module

When adding: create `<module>/MODULE.md`, add a row above, update any diagrams,
commit together, and link the PR to the driving EXECUTION.md slice. When removing:
delete the row, search for and remove `MODULE.md` references in dependents, and run
`review` to surface stale callers.
