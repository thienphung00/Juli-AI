# Architecture Map

> **Tier 1 — as-built registry.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** deployed module paths, endpoints, jobs. **Does not own:** subsystem envelopes (`system-design.md`), data phase gates (`data-sources.md`), MVP target diagram (`phase-2-mvp.md`).

Update this file when you add, rename, remove, or restructure a module.

**Authority:** `EXECUTION.md` > `system-design.md` > this file.

## Code layout

### Target layout (Phase 2.5+)

Product-oriented monorepo — `backend/` holds runtime Python services (ADR-019:
`src/` shim tree removed).

```
apps/          # Product deployables (dashboard, demo)
backend/       # API, workers, AI, integrations, database
infra/         # CI/CD, deploy config, env templates
docs/
```

See [`migration-plan.md`](migration-plan.md) for full path mapping and migration sequence.

### Current layout (as-built)

The backend is a modular monolith under `backend/`. Frontends live in
`apps/dashboard/`, `apps/demo/`, and `ios/`. **`backend/api/` and
`backend/workers/` are backend entrypoints — not top-level `apps/`.**

```
backend/src/juli_backend/
├── api/                          # FastAPI /v1 routes, app factory, dependencies
│   ├── routes/                   # Versioned REST routers
│   ├── app.py                    # create_app factory
│   └── main.py                   # ASGI entrypoint (uvicorn)
├── services/                     # Domain services (webhook, ETL, alerts, TikTok OAuth)
├── core/                         # Config, JWT auth, credential resolution
├── models/                       # SQLAlchemy ORM models
├── repositories/                 # Data access repositories
├── integrations/tiktok/          # TikTok Shop Partner API client
├── workers/services/polling/     # Scheduled sync workers
├── ai/                           # ML trainers, features, artifacts
└── database/                     # Engine/session, Alembic migrations
```

Frontends (as-built):

| Path | Product role | Future target |
|------|--------------|---------------|
| `apps/dashboard/` | Seller dashboard (3-tab IA, ADR-014) | — (consolidated Phase 3) |
| `apps/demo/` | Phase 2.6 mock Demo shell and sparse Home (ADR-023) | Phase 3 real-data upgrade |
| `ios/` | SwiftUI mobile app | `apps/mobile` (Phase 4) |

## Module tier policy

| Tier | Definition | MODULE.md required? |
|------|-----------|---------------------|
| **1: Core** | Cross-cutting, frequent change, public API surface | **Yes** (eager) |
| **2: Feature** | Domain modules touched by current/upcoming features | **Yes** (lazy — created on first touch) |
| **3: Utility** | Stable, single-purpose, rarely changed | Optional |

## Current modules

| Module | Tier | Responsibility | Public Surface | Owners |
|--------|------|----------------|----------------|--------|
| [`backend/src/juli_backend/integrations/tiktok`](../../backend/src/juli_backend/integrations/tiktok/MODULE.md) | 1 | TikTok Shop Partner API client (auth, signing, rate limiting, resources) | `TikTokClient`, `TikTokAuth`, `RateLimiter`, `CreatorsResource`, `ProductsResource`, `OrdersResource`, `InventoryResource`, `LivestreamsResource`, `SettlementsResource`, `TikTokAPIError` hierarchy | domain: integrations |
| [`backend/src/juli_backend/services/ingestion`](../../backend/src/juli_backend/services/ingestion/MODULE.md) | 1 | Ingest handoff contracts and `make_etl_handoff` wiring | `HandoffFn`, `make_etl_handoff` | domain: data |
| [`backend/src/juli_backend/services/webhook`](../../backend/src/juli_backend/services/webhook/MODULE.md) | 1 | Receives TikTok webhooks, verifies HMAC signature, hands validated payloads to ETL. Deployed via `api/routes/webhook_tiktok.py` mount on `api/app.py` (#381); `create_app` remains for standalone/isolated testing | `build_webhook_service`, `create_app(..., handoff_fn) -> FastAPI` | domain: integrations |
| [`backend/src/juli_backend/workers/services/polling`](../../backend/src/juli_backend/workers/services/polling/MODULE.md) | 2 | Background polling sync workers (P2-A1 read sync) | `sync_creators`, `sync_products`, `sync_orders`, `sync_returns`, `backfill_shop` | domain: integrations |
| [`backend/src/juli_backend/database`](../../backend/src/juli_backend/database/MODULE.md) | 1 | Persistence layer: SQLAlchemy async models, repos, Alembic migrations | `User`, `Shop`, `Creator`, `Product`, `Recommendation`, … repos, `Base`, `NotFound`, `get_session` | domain: data |
| [`backend/src/juli_backend/core/security`](../../backend/src/juli_backend/core/security/MODULE.md) | 1 | JWT verification, TikTok OAuth lifecycle, FastAPI auth dependency | `TikTokOAuthService`, `verify_supabase_jwt`, `get_current_user`, `Unauthorized` | domain: auth |
| [`backend/src/juli_backend/api`](../../backend/src/juli_backend/api/MODULE.md) | 1 | FastAPI REST API (`/v1/*`): auth, shops, orders, products, creators, recommendations, outcomes | `create_app`, `get_active_shop`, `GET /v1/shops`, `GET /v1/orders`, `GET /v1/products`, `GET /v1/creators`, `GET /v1/recommendations` | domain: api |
| [`backend/src/juli_backend/ai/recommendations`](../../backend/src/juli_backend/ai/recommendations/MODULE.md) | 2 | Decision generation: seller-action suggestions with justification + CTA | `get_host_product_matching`, `get_product_push_suggestions`, `get_stream_optimization` | domain: recommendations |
| [`backend/src/juli_backend/services/etl`](../../backend/src/juli_backend/services/etl/MODULE.md) | 1 | Ingestion consumer: dedup by event_id, transform, persist via data repos, DLQ on failure | `EtlConsumer.ingest`, `IngestRecord`, `ProcessOutcome` | domain: data |
| [`apps/dashboard`](../../apps/dashboard/MODULE.md) | 2 | Next.js web app — UI for the three seller-money workflows (mock data in Phase 1) | `/login`, `/`, workflow pages | domain: web |
| [`apps/demo`](../../apps/demo/MODULE.md) | 2 | Standalone Next.js mock Demo; four-destination shell and sparse Home foundation | `/`, `/decisions`, `/analytics`, `/settings` | domain: web |
| [`packages/theme`](../../packages/theme/MODULE.md) | 1 | Framework-independent semantic product tokens | `@juli/theme/tokens.css` | domain: web |
| [`packages/ui`](../../packages/ui/MODULE.md) | 1 | Accessible shared React primitives | `DestinationCard`, `PrimaryNavigation` | domain: web |
| [`packages/utils`](../../packages/utils/MODULE.md) | 1 | Vietnamese money, number, date, and date-time formatters | `formatVND`, `formatNumber`, `formatDate`, `formatDateTime` | domain: web |
| [`ios`](../../ios/MODULE.md) | 2 | Native SwiftUI iOS app: demo auth, JWT Keychain storage, shop selection | `AuthService`, `KeychainService`, `APIClient` | domain: ios |
| [`backend/ai/dataset`](../../backend/ai/dataset/MODULE.md) | 2 | Phase 1.5 backtest parquet assembly: synthetic data, schema validation, manifest | `assemble_backtest_dataset`, `validate_backtest_dataset`, `DatasetValidationError` | domain: ml |
| [`backend/ai/features`](../../backend/ai/features/MODULE.md) | 2 | Phase 1.5 feature engineering: parquet → per-model feature matrices | `build_seller_stage_features`, `build_anomaly_features`, `build_ad_features`, `FeatureMatrix` | domain: ml |
| [`backend/ai/seller_stage`](../../backend/ai/seller_stage/MODULE.md) | 2 | Phase 1.5 seller lifecycle classifier: rules baseline, train, rules-vs-ML compare | `classify_seller_stage`, `train_seller_stage`, `predict_seller_stage`, `compare_to_rules_baseline` | domain: ml |
| [`backend/ai/anomaly`](../../backend/ai/anomaly/MODULE.md) | 2 | Phase 1.5 buyer-behavior anomaly detector: item_swap / empty_return training + inference | `train_anomaly`, `predict_anomaly`, `build_anomaly_training_frame` | domain: ml |
| [`backend/ai/ad_performance`](../../backend/ai/ad_performance/MODULE.md) | 2 | Phase 1.5 ad performance analyzer: ROAS prediction + scale/cut/hold ranking | `train_ad_performance`, `predict_ad_action`, `build_ad_training_frame` | domain: ml |
| [`backend/ai/artifacts`](../../backend/ai/artifacts/MODULE.md) | 2 | Phase 1.5 model artifact publisher: joblib serialization, metadata, promotion gate, smoke tests | `publish_model`, `load_model`, `run_smoke_test`, `evaluate_promotion_status` | domain: ml |

## Phase 1.6 modules (deployed — listing workflow)

Tracked by [ADR-016](../adr/016-listing-workflow-implementation.md) and
`EXECUTION.md` slices P1.6-1…P1.6-5.

| Module | Tier | Responsibility | Public Surface | Owners |
|--------|------|----------------|----------------|--------|
| [`apps/dashboard/src/lib/mock-data/listing-workflow`](../../apps/dashboard/src/lib/mock-data/listing-workflow/MODULE.md) | 2 | Listing workflow mock fixtures: ProductDraft, Distributor, Opportunity | `loadDistributors`, `loadOpportunities`, `loadProductDrafts`, `validateListingFixtures` | domain: web |
| [`apps/dashboard/src/lib/workflows/new-seller/listing`](../../apps/dashboard/src/lib/workflows/new-seller/listing/MODULE.md) | 2 | Listing generation + export: rules engine, CSV/JSON serialize, state machine | `generateProductDraft`, `exportProductDraft`, `useListingWorkflow` | domain: web |
| [`apps/dashboard/src/lib/workflows/new-seller/shop-progress`](../../apps/dashboard/src/lib/workflows/new-seller/shop-progress/MODULE.md) | 2 | Session-scoped listing milestone + widget states | `loadShopProgress`, `recordExportCompleted`, `useShopProgress` | domain: web |
| [`apps/dashboard/src/components/workflows/new-seller/listing`](../../apps/dashboard/src/components/workflows/new-seller/listing/ListingWorkflowPanel.tsx) | 2 | Modal listing workflow from approved `list_products` | `ListingWorkflowPanel` | domain: web |
| [`apps/dashboard/src/components/workflows/new-seller/ListingProgressWidget`](../../apps/dashboard/src/components/workflows/new-seller/ListingProgressWidget.tsx) | 2 | Copilot home listing progress widget | `ListingProgressWidget` | domain: web |

## Planned modules (Phase 1.7 / 1.8 / Phase 2 — not yet deployed)

Tracked by [ADR-013](../adr/013-operations-pipeline-spine.md),
[ADR-013](../adr/013-operations-pipeline-spine.md) and `EXECUTION.md`
slices P1.7-1…P1.7-5, P1.8-1…P1.8-7, P2-7…P2-15. Add rows here when code lands.

| Module (planned) | Target phase | Responsibility |
|------------------|--------------|----------------|
| `apps/dashboard/src/lib/mock-data/leakage-workflow/` | P1.7 | Leakage workflow fixtures: `LeakageWorkflowTask`, evidence bundles, execution plans |
| `apps/dashboard/src/lib/workflows/leakage/state-machine.ts` + `use-leakage-workflow.ts` | P1.7 | Leakage step graph, session resume, `canAdvance` |
| `apps/dashboard/src/components/workflows/leakage/LeakageWorkflowPanel.tsx` | P1.7 | Modal leakage workflow from approved leakage tasks; four task-type step renderers |
| `apps/dashboard/src/lib/mock-data/operations/` | P1.8 | `unified_operational_data_model` fixtures + datum→workflow traceability map (P1.8-2) |
| `apps/dashboard/src/lib/operations/classification.ts` | P1.8 | Rules-based `shop_profile` classification + profile→workflow catalog mapping (P1.8-1) |
| `apps/dashboard/src/lib/operations/health-check.ts` | P1.8 | `health_check_results` indicators from mock operational data (P1.8-3) |
| `apps/dashboard/src/lib/operations/recommendations.ts` + `use-operations-pipeline.ts` | P1.8 | `workflow_recommendations` ranking + pipeline orchestration hook (P1.8-4) |
| `apps/dashboard/src/components/workflows/operations/` | P1.8 | Operations pipeline shell: reasoning panel, unified approval gate + routing, outcome tracking views (P1.8-5…P1.8-7) |
| `apps/dashboard/src/app/decisions/` + `apps/dashboard/src/components/decisions/` | P1.8-9 | Decisions tab: Recommended / In Progress / Workflow Templates sub-tabs; decision detail 5-step flow; approval gate host ([ADR-014](../adr/014-decision-copilot-app-structure-and-journey.md)) |
| `apps/dashboard/src/components/home/todays-report/` | P1.8-9 | Today's Report domain cards (Revenue Growth, Revenue Protection, Product Listings, Advertising, Refunds) with animated domain switcher on Home |
| `apps/dashboard/src/lib/decisions/` | P1.8-9 | Decision view-model: map `workflow_recommendations` → Decision envelopes + lifecycle status (`recommended` / `needs_input` / `executing` / `completed`) |
| `backend/src/juli_backend/services/listing/` *(TBD)* | P2 | ProductDraft persistence, approval queue (P2-7), Products API publish (P2-8) |
| `backend/src/juli_backend/services/leakage/` *(TBD)* | P2 | Leakage task persistence, approval queue (P2-9), live executors (P2-10) |
| `backend/src/juli_backend/services/operations/` *(TBD)* | P2 | Live operations pipeline (P2-11): real classification, health, ranking, outcome tracking |
| `backend/src/juli_backend/services/inventory/` *(TBD)* | P2 | Scoped inventory signals (level, velocity, lead time) for Stockout/Product Scaling (P2-12) — signals only, not inventory management |

## Cleanup status (2026-07 aggressive cleanup)

| Target | Status |
|--------|--------|
| Polling: `sync_inventory`, `sync_settlements`, `sync_livestreams` | **Removed** |
| API routers: `analytics`, `settlements`, `inventory`, `livestreams`, `alerts` | **Removed** |
| Web pages: `/inventory`, `/livestreams`, `/alerts` | **Removed** (legacy redirects remain) |
| `docs/product/features/mvp_1.*` | **Archived** to `docs/handoffs/archive/features/` |
| `backend/src/juli_backend/ai/forecasting/**` | **Deferred** — still wired to recommendations engine |

## Key architectural decisions

- **Backend:** Python / FastAPI only ([ADR-001](../adr/001-keep-python-fastapi.md))
- **Database:** Supabase (managed Postgres + Auth) — source of truth ([ADR-002](../adr/002-supabase-backend-service.md))
- **Auth:** Demo login on frontend; JWT validation on protected FastAPI routes
- **Data sources:** TikTok Shop Official API only. Unofficial livestream websockets,
  Seller Center scraping, and buyer PII storage are **permanently forbidden**. See
  [`data-sources.md`](data-sources.md).
- **Data model:** Canonical entity schemas and ML features live in
  [`docs/api/data-models/`](../api/data-models/README.md). TikTok API docs (`tiktok_api/endpoints.md`)
  are the ingestion layer only ([ADR-012](../adr/012-entity-centric-data-model.md)).
- **Platform policy:** Seller/creator feature guides and policy center rules live in
  [`docs/integrations/tiktok_platform/`](../tiktok_platform/README.md). Implementation hooks
  (`seller/implementation-hooks.md`, `creator/implementation-hooks.md`) define alerts,
  gates, and ETL behavior for Phase 2 workflows.
- **Runtime evolution:** simple daily scheduler in Phase 2; Celery for execution in Phase 2
  (see [`../../EXECUTION.md`](../../EXECUTION.md)); Kafka/streams deferred to Phase 4.5.

> **Platform policy (Phase 2):** [ADR-008](../adr/008-alert-vp-ahr-milestones.md)
> (milestone alerts), [ADR-009](../adr/009-dual-read-vp-ahr-transition.md)
> (VP→AHR dual-read), [ADR-010](../adr/010-vn-regional-platform-config.md)
> (VN regional thresholds).
>
> **Anomaly ML scope (Phase 1.5):** [ADR-011](../adr/011-buyer-behavior-anomaly-scope.md)
> — buyer return anomalies (`item_swap`, `empty_return`) only; schema in
> [`data-models/canonical-entities.md`](../api/data-models/canonical-entities.md) § Return, § OrderItem.
>
> **Executable leakage workflow (Phase 1.7):** [ADR-013](../adr/013-operations-pipeline-spine.md)
> — modal workflow from approved leakage tasks; mock execute only until P2-9/P2-10.
>
> **Operations-system orchestration (Phase 1.8):** [ADR-013](../adr/013-operations-pipeline-spine.md)
> — mock pipeline (classify → health check → ranked recs → reasoning → approval →
> outcome tracking) + 2 shop profiles + validated workflow catalog; narrow inventory
> signals approved for P2+ (Stockout/Product Scaling only).
>
> **Decision Copilot app structure (Phase 1.8):** [ADR-014](../adr/014-decision-copilot-app-structure-and-journey.md)
> — 3-tab IA (Home / Decisions / Juli Chat); Decision as primary UI object; Home
> read-only; approval and templates on Decisions tab only.
>
> **Entity-centric data model:** ADR-009 — `docs/api/data-models/` is ML schema authority.

## Target architecture (Phase 2 MVP)

Forward-looking stack diagram and daily schedule: [`phase-2-mvp.md`](../product/phases/phase-2-mvp.md).  
This file (`map.md`) is **as-built only**.

## Adding / removing a module

When adding: create `<module>/MODULE.md`, add a row above, update any diagrams,
commit together, and link the PR to the driving EXECUTION.md slice. When removing:
delete the row, search for and remove `MODULE.md` references in dependents, and run
`review` to surface stale callers.
