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
apps/          # Product deployables (landing, demo, dashboard, mobile)
packages/      # Shared UI, types, api-client, utils
backend/       # API, workers, AI, integrations, database
infra/         # CI/CD, deploy config, env templates
docs/
```

See [`migration-plan.md`](migration-plan.md) for full path mapping and migration sequence.

### Current layout (as-built)

The backend is a modular monolith under `backend/`. Frontends live in `web/` and
`ios/`. **`backend/api/` and `backend/workers/` are backend entrypoints — not top-level `apps/`.**

```
backend/
├── api/                          # FastAPI /v1 routers + app factory + webhook service
│   ├── api/
│   └── services/webhook/
├── workers/services/polling/       # Scheduled sync workers
├── integrations/                 # Domain modules (business logic)
│   ├── identity/infrastructure/auth/   # JWT verification, TikTok OAuth
│   ├── catalog/domain/
│   │   ├── integrations/tiktok/  # TikTok Shop Partner API client
│   │   └── recommendations/      # Decision/recommendation generation
│   └── ordering/                 # Ingestion handoff + ETL (data accumulation)
├── ai/                           # ML trainers, features, artifacts
└── database/                     # SQLAlchemy models, repos, Alembic migrations
```

Frontends (legacy, pre-ecosystem):

| Path | Product role | Future target |
|------|--------------|---------------|
| `web/` | Seller dashboard (3-tab IA, ADR-014) | `apps/dashboard` (Phase 3.5) |
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
| [`backend/integrations/catalog/domain/integrations/tiktok`](../../backend/integrations/catalog/domain/integrations/tiktok/MODULE.md) | 1 | TikTok Shop Partner API client (auth, signing, rate limiting, resources) | `TikTokClient`, `TikTokAuth`, `RateLimiter`, `CreatorsResource`, `ProductsResource`, `OrdersResource`, `InventoryResource`, `LivestreamsResource`, `SettlementsResource`, `TikTokAPIError` hierarchy | domain: integrations |
| [`backend/integrations/ordering/api/ingestion`](../../backend/integrations/ordering/api/ingestion/MODULE.md) | 1 | Ingest handoff contracts and `make_etl_handoff` wiring | `HandoffFn`, `make_etl_handoff` | domain: data |
| [`backend/api/services/webhook`](../../backend/api/services/webhook/MODULE.md) | 1 | Receives TikTok webhooks, verifies HMAC signature, hands validated payloads to ETL | `create_app(..., handoff_fn) -> FastAPI` | domain: integrations |
| [`backend/workers/services/polling`](../../backend/workers/services/polling/MODULE.md) | 2 | Background polling sync workers (P2-A1 read sync) | `sync_creators`, `sync_products`, `sync_orders`, `sync_returns`, `backfill_shop` | domain: integrations |
| [`backend/database`](../../backend/database/MODULE.md) | 1 | Persistence layer: SQLAlchemy async models, repos, Alembic migrations | `User`, `Shop`, `Creator`, `Product`, `Recommendation`, … repos, `Base`, `NotFound`, `get_session` | domain: data |
| [`backend/integrations/identity/infrastructure/auth`](../../backend/integrations/identity/infrastructure/auth/MODULE.md) | 1 | JWT verification, TikTok OAuth lifecycle, FastAPI auth dependency | `TikTokOAuthService`, `verify_supabase_jwt`, `get_current_user`, `Unauthorized` | domain: auth |
| [`backend/api/api`](../../backend/api/api/MODULE.md) | 1 | FastAPI REST API (`/v1/*`): auth, shops, orders, products, creators, recommendations, outcomes | `create_app`, `get_active_shop`, `GET /v1/shops`, `GET /v1/orders`, `GET /v1/products`, `GET /v1/creators`, `GET /v1/recommendations` | domain: api |
| [`backend/integrations/catalog/domain/recommendations`](../../backend/integrations/catalog/domain/recommendations/MODULE.md) | 2 | Decision generation: seller-action suggestions with justification + CTA | `get_host_product_matching`, `get_product_push_suggestions`, `get_stream_optimization` | domain: recommendations |
| [`backend/integrations/ordering/use_cases/etl`](../../backend/integrations/ordering/use_cases/etl/MODULE.md) | 1 | Ingestion consumer: dedup by event_id, transform, persist via data repos, DLQ on failure | `EtlConsumer.ingest`, `IngestRecord`, `ProcessOutcome` | domain: data |
| [`web`](../../web/MODULE.md) | 2 | Next.js web app — UI for the three seller-money workflows (mock data in Phase 1) | `/login`, `/`, workflow pages | domain: web |
| [`ios`](../../ios/MODULE.md) | 2 | Native SwiftUI iOS app: demo auth, JWT Keychain storage, shop selection | `AuthService`, `KeychainService`, `APIClient` | domain: ios |
| [`backend/ai/dataset`](../../backend/ai/dataset/MODULE.md) | 2 | Phase 1.5 backtest parquet assembly: synthetic data, schema validation, manifest | `assemble_backtest_dataset`, `validate_backtest_dataset`, `DatasetValidationError` | domain: ml |
| [`backend/ai/features`](../../backend/ai/features/MODULE.md) | 2 | Phase 1.5 feature engineering: parquet → per-model feature matrices | `build_seller_stage_features`, `build_anomaly_features`, `build_ad_features`, `FeatureMatrix` | domain: ml |
| [`backend/ai/seller_stage`](../../backend/ai/seller_stage/MODULE.md) | 2 | Phase 1.5 seller lifecycle classifier: rules baseline, train, rules-vs-ML compare | `classify_seller_stage`, `train_seller_stage`, `predict_seller_stage`, `compare_to_rules_baseline` | domain: ml |
| [`backend/ai/anomaly`](../../backend/ai/anomaly/MODULE.md) | 2 | Phase 1.5 buyer-behavior anomaly detector: item_swap / empty_return training + inference | `train_anomaly`, `predict_anomaly`, `build_anomaly_training_frame` | domain: ml |
| [`backend/ai/ad_performance`](../../backend/ai/ad_performance/MODULE.md) | 2 | Phase 1.5 ad performance analyzer: ROAS prediction + scale/cut/hold ranking | `train_ad_performance`, `predict_ad_action`, `build_ad_training_frame` | domain: ml |
| [`backend/ai/artifacts`](../../backend/ai/artifacts/MODULE.md) | 2 | Phase 1.5 model artifact publisher: joblib serialization, metadata, promotion gate, smoke tests | `publish_model`, `load_model`, `run_smoke_test`, `evaluate_promotion_status` | domain: ml |

## Phase 1.6 modules (deployed — listing workflow)

Tracked by [ADR-016](../decisions/016-listing-workflow-implementation.md) and
`EXECUTION.md` slices P1.6-1…P1.6-5.

| Module | Tier | Responsibility | Public Surface | Owners |
|--------|------|----------------|----------------|--------|
| [`web/src/lib/mock-data/listing-workflow`](../../web/src/lib/mock-data/listing-workflow/MODULE.md) | 2 | Listing workflow mock fixtures: ProductDraft, Distributor, Opportunity | `loadDistributors`, `loadOpportunities`, `loadProductDrafts`, `validateListingFixtures` | domain: web |
| [`web/src/lib/workflows/new-seller/listing`](../../web/src/lib/workflows/new-seller/listing/MODULE.md) | 2 | Listing generation + export: rules engine, CSV/JSON serialize, state machine | `generateProductDraft`, `exportProductDraft`, `useListingWorkflow` | domain: web |
| [`web/src/lib/workflows/new-seller/shop-progress`](../../web/src/lib/workflows/new-seller/shop-progress/MODULE.md) | 2 | Session-scoped listing milestone + widget states | `loadShopProgress`, `recordExportCompleted`, `useShopProgress` | domain: web |
| [`web/src/components/workflows/new-seller/listing`](../../web/src/components/workflows/new-seller/listing/ListingWorkflowPanel.tsx) | 2 | Modal listing workflow from approved `list_products` | `ListingWorkflowPanel` | domain: web |
| [`web/src/components/workflows/new-seller/ListingProgressWidget`](../../web/src/components/workflows/new-seller/ListingProgressWidget.tsx) | 2 | Copilot home listing progress widget | `ListingProgressWidget` | domain: web |

## Planned modules (Phase 1.7 / 1.8 / Phase 2 — not yet deployed)

Tracked by [ADR-013](../decisions/013-operations-pipeline-spine.md),
[ADR-013](../decisions/013-operations-pipeline-spine.md) and `EXECUTION.md`
slices P1.7-1…P1.7-5, P1.8-1…P1.8-7, P2-7…P2-15. Add rows here when code lands.

| Module (planned) | Target phase | Responsibility |
|------------------|--------------|----------------|
| `web/src/lib/mock-data/leakage-workflow/` | P1.7 | Leakage workflow fixtures: `LeakageWorkflowTask`, evidence bundles, execution plans |
| `web/src/lib/workflows/leakage/state-machine.ts` + `use-leakage-workflow.ts` | P1.7 | Leakage step graph, session resume, `canAdvance` |
| `web/src/components/workflows/leakage/LeakageWorkflowPanel.tsx` | P1.7 | Modal leakage workflow from approved leakage tasks; four task-type step renderers |
| `web/src/lib/mock-data/operations/` | P1.8 | `unified_operational_data_model` fixtures + datum→workflow traceability map (P1.8-2) |
| `web/src/lib/operations/classification.ts` | P1.8 | Rules-based `shop_profile` classification + profile→workflow catalog mapping (P1.8-1) |
| `web/src/lib/operations/health-check.ts` | P1.8 | `health_check_results` indicators from mock operational data (P1.8-3) |
| `web/src/lib/operations/recommendations.ts` + `use-operations-pipeline.ts` | P1.8 | `workflow_recommendations` ranking + pipeline orchestration hook (P1.8-4) |
| `web/src/components/workflows/operations/` | P1.8 | Operations pipeline shell: reasoning panel, unified approval gate + routing, outcome tracking views (P1.8-5…P1.8-7) |
| `web/src/app/decisions/` + `web/src/components/decisions/` | P1.8-9 | Decisions tab: Recommended / In Progress / Workflow Templates sub-tabs; decision detail 5-step flow; approval gate host ([ADR-014](../decisions/014-decision-copilot-app-structure-and-journey.md)) |
| `web/src/components/home/todays-report/` | P1.8-9 | Today's Report domain cards (Revenue Growth, Revenue Protection, Product Listings, Advertising, Refunds) with animated domain switcher on Home |
| `web/src/lib/decisions/` | P1.8-9 | Decision view-model: map `workflow_recommendations` → Decision envelopes + lifecycle status (`recommended` / `needs_input` / `executing` / `completed`) |
| `backend/integrations/catalog/domain/listing/` *(TBD)* | P2 | ProductDraft persistence, approval queue (P2-7), Products API publish (P2-8) |
| `backend/integrations/catalog/domain/leakage/` *(TBD)* | P2 | Leakage task persistence, approval queue (P2-9), live executors (P2-10) |
| `backend/integrations/catalog/domain/operations/` *(TBD)* | P2 | Live operations pipeline (P2-11): real classification, health, ranking, outcome tracking |
| `backend/integrations/catalog/domain/inventory/` *(TBD)* | P2 | Scoped inventory signals (level, velocity, lead time) for Stockout/Product Scaling (P2-12) — signals only, not inventory management |

## Cleanup status (2026-07 aggressive cleanup)

| Target | Status |
|--------|--------|
| Polling: `sync_inventory`, `sync_settlements`, `sync_livestreams` | **Removed** |
| API routers: `analytics`, `settlements`, `inventory`, `livestreams`, `alerts` | **Removed** |
| Web pages: `/inventory`, `/livestreams`, `/alerts` | **Removed** (legacy redirects remain) |
| `docs/features/mvp_1.*` | **Archived** to `docs/handoffs/archive/features/` |
| `backend/integrations/catalog/domain/intelligence/**` | **Deferred** — still wired to recommendations engine |

## Key architectural decisions

- **Backend:** Python / FastAPI only ([ADR-001](../decisions/001-keep-python-fastapi.md))
- **Database:** Supabase (managed Postgres + Auth) — source of truth ([ADR-002](../decisions/002-supabase-backend-service.md))
- **Auth:** Demo login on frontend; JWT validation on protected FastAPI routes
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
- **Runtime evolution:** simple daily scheduler in Phase 2; Celery for execution in Phase 2
  (see [`../../EXECUTION.md`](../../EXECUTION.md)); Kafka/streams deferred to Phase 4.5.

> **Platform policy (Phase 2):** [ADR-008](../decisions/008-alert-vp-ahr-milestones.md)
> (milestone alerts), [ADR-009](../decisions/009-dual-read-vp-ahr-transition.md)
> (VP→AHR dual-read), [ADR-010](../decisions/010-vn-regional-platform-config.md)
> (VN regional thresholds).
>
> **Anomaly ML scope (Phase 1.5):** [ADR-011](../decisions/011-buyer-behavior-anomaly-scope.md)
> — buyer return anomalies (`item_swap`, `empty_return`) only; schema in
> [`data-models/canonical-entities.md`](../data-models/canonical-entities.md) § Return, § OrderItem.
>
> **Executable leakage workflow (Phase 1.7):** [ADR-013](../decisions/013-operations-pipeline-spine.md)
> — modal workflow from approved leakage tasks; mock execute only until P2-9/P2-10.
>
> **Operations-system orchestration (Phase 1.8):** [ADR-013](../decisions/013-operations-pipeline-spine.md)
> — mock pipeline (classify → health check → ranked recs → reasoning → approval →
> outcome tracking) + 2 shop profiles + validated workflow catalog; narrow inventory
> signals approved for P2+ (Stockout/Product Scaling only).
>
> **Decision Copilot app structure (Phase 1.8):** [ADR-014](../decisions/014-decision-copilot-app-structure-and-journey.md)
> — 3-tab IA (Home / Decisions / Juli Chat); Decision as primary UI object; Home
> read-only; approval and templates on Decisions tab only.
>
> **Entity-centric data model:** ADR-009 — `docs/data-models/` is ML schema authority.

## Target architecture (Phase 2 MVP)

Forward-looking stack diagram and daily schedule: [`phase-2-mvp.md`](../phases/phase-2-mvp.md).  
This file (`map.md`) is **as-built only**.

## Adding / removing a module

When adding: create `<module>/MODULE.md`, add a row above, update any diagrams,
commit together, and link the PR to the driving EXECUTION.md slice. When removing:
delete the row, search for and remove `MODULE.md` references in dependents, and run
`review` to surface stale callers.
