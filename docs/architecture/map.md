# Architecture Map

> **Tier 2 — as-built registry.** Read [`EXECUTION.md`](../../EXECUTION.md) and
> [`MODULES.md`](MODULES.md) first.  
> **Owns:** deployed module paths, endpoints, jobs, `MODULE.md` links.  
> **Does not own:** module goals/feature progression (`MODULES.md`), subsystem envelopes
> (`system-design.md`), data phase gates (`data-sources.md`), MVP target diagram
> (`phase-2-mvp.md`).

Update this file when you add, rename, remove, or restructure a **code** module path.

**Authority:** `EXECUTION.md` > `MODULES.md` > `system-design.md` > this file.  
When purpose/goals conflict with [`MODULES.md`](MODULES.md), MODULES wins; this file
wins on live paths until MODULES is updated.

**Authority (legacy note):** Older docs said Tier 1 for this file — superseded by
[ADR-036](../adr/036-modules-tier1-planning-sot.md) (map is Tier 2 as-built).

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
├── api/                          # FastAPI /v1 routes — thin adapters (MMU-8)
│   ├── routes/                   # Versioned REST routers
│   ├── app.py                    # create_app factory
│   └── main.py                   # ASGI entrypoint (uvicorn)
├── services/
│   ├── action_cards/             # Decision refresh + persistence facade
│   ├── aggregates/               # Feature aggregates / shop profile
│   ├── alerts/                   # Rule engine + delivery channels
│   ├── analytics_backfill/       # Phase 2.9 historical partitions
│   ├── etl/                      # Ingest consumer + transform
│   ├── execution/                # Approved tool dispatch + Celery ports
│   ├── feedback/                 # Campaign outcome ingest
│   ├── ingestion/                # ETL handoff contracts
│   ├── operations/               # Workflow outcome tracking (partial)
│   ├── scoring/                  # Rules scoring pipeline
│   ├── tiktok/                   # OAuth, webhook catalog, signature (domain)
│   └── webhook/                  # Webhook sub-app + material compute handoff
├── core/security/                # JWT, TikTok OAuth, credential resolver
├── database/                     # Session factory, lazy model/repo facade
├── models/ · repositories/       # Shared ORM + repos (domain split deferred)
├── integrations/tiktok/          # Partner API client package facade (MMU-5)
├── workers/
│   ├── celery_app.py             # Broker wiring only
│   ├── tasks/                    # Thin Celery wrappers → domain modules
│   └── services/polling/         # Scheduled TikTok sync
└── ai/                           # ML trainers, features, artifacts
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

## Modular monolith boundary registry ([#550](https://github.com/thienphung00/Juli-AI/issues/550))

Baseline modular-monolith score **5.5 / 10** from the
[boundary audit](../handoffs/modular-monolith-boundary-audit.html) (2026-07-28);
target **~9 / 10** per the [Modular Monolith Upgrade PRD](../product/phases/modular-monolith-upgrade/PRD.md)
— MMU-15 (#565) will publish the exit scorecard.

| Artifact | Role |
|----------|------|
| [`ownership-registry.yml`](ownership-registry.yml) | Runtime owners: Postgres tables, Celery tasks, Redis namespaces, integrations |
| [`import-boundaries.md`](import-boundaries.md) · [`.importlinter.toml`](../../.importlinter.toml) | Allowed import edges + deep-import policy (MMU-2) |
| [`modular-monolith-audit-data.json`](../handoffs/modular-monolith-audit-data.json) | Audit snapshot (modules, edges, enforcement) |

**Facade rule:** cross-module callers import package-root `__all__` surfaces only
(documented in each `MODULE.md`). Post-MMU-1..8 landings include TikTok integration
facade (MMU-5), Celery dispatcher ports (MMU-6), Execution→Operations one-way
contract (MMU-7), and thin API adapters (MMU-8). See [`MODULES.md`](MODULES.md) §
Modular monolith upgrade.

**Owners column** below uses Tier-1 planning module names aligned with
[`ownership-registry.yml`](ownership-registry.yml).

## Current modules

| Module | Tier | Responsibility | Public Surface | Owner |
|--------|------|----------------|----------------|-------|
| [`backend/src/juli_backend/integrations/tiktok`](../../backend/src/juli_backend/integrations/tiktok/MODULE.md) | 1 | TikTok Shop Partner API client — auth, signing, rate limiting, resources, factories, mapping | Package facade: `TikTokClient`, `TikTokAuth`, `RateLimiter`, resource types, `TikTokAPIError` hierarchy, factories, mapping helpers — import `juli_backend.integrations.tiktok` only (MMU-5) | Integrations |
| [`backend/src/juli_backend/services/tiktok`](../../backend/src/juli_backend/services/tiktok/__init__.py) | 1 | TikTok OAuth infrastructure, webhook catalog, signature verify, dispatcher | `TikTokOAuthInfrastructureService`, `TikTokWebhookService`, `TikTokWebhookSignatureVerifier`, `TikTokWebhookDispatcher`, `EVENT_CATEGORY_ROUTES`, `PHASE2_CATALOG` | Integrations |
| [`backend/src/juli_backend/services/ingestion`](../../backend/src/juli_backend/services/ingestion/MODULE.md) | 1 | Ingest handoff contracts and `make_etl_handoff` wiring | `HandoffFn`, `DlqHandoffFn`, `make_etl_handoff` | Data Pipeline |
| [`backend/src/juli_backend/services/webhook`](../../backend/src/juli_backend/services/webhook/MODULE.md) | 1 | Receives TikTok webhooks, verifies HMAC, hands validated payloads to ETL. API mount via `api/routes/webhook_tiktok.py` (MMU-8 thin adapter) | `build_webhook_service`, `create_app`, `WEBHOOK_PATH`, `HandoffFn`, `EVENT_CATEGORY_ROUTES` | Data Pipeline |
| [`backend/src/juli_backend/services/etl`](../../backend/src/juli_backend/services/etl/MODULE.md) | 1 | Ingestion consumer: dedup by event_id, transform, persist, DLQ on failure | `EtlConsumer`, `IngestRecord`, `ProcessOutcome`, `transform_for_channel`, `transform_for_topic`, `RAW_CHANNELS`, `DLQ_CHANNEL` | Data Pipeline |
| [`backend/src/juli_backend/services/aggregates`](../../backend/src/juli_backend/services/aggregates/MODULE.md) | 2 | Rules-only feature aggregates and shop profile signals over synced Postgres | `build_feature_aggregates`, `classify_shop_profile`, `compute_all_kpis`, `resolve_health_snapshot` | Data Pipeline |
| [`backend/src/juli_backend/services/analytics_backfill`](../../backend/src/juli_backend/services/analytics_backfill/MODULE.md) | 2 | Phase 2.9 analytics historical backfill partitions + coverage | `backfill_analytics_history`, `run_catalog_partition`, `generate_coverage_report`, `CallBudgetGovernor` | Data Pipeline |
| [`backend/src/juli_backend/workers/services/polling`](../../backend/src/juli_backend/workers/services/polling/MODULE.md) | 2 | Background polling sync workers (P2-A1 read sync) | `sync_creators`, `sync_products`, `sync_orders`, `sync_returns`, `sync_analytics`, `backfill_shop`, `run_fujiwa_poll_cycle` | Workers & Async |
| [`backend/src/juli_backend/database`](../../backend/src/juli_backend/database/MODULE.md) | 1 | Persistence layer: SQLAlchemy async session, lazy model/repo facade, Alembic migrations | `Base`, `NotFound`, `get_session`, lazy `Shop`, `User`, … repos via PEP 562 | Database |
| [`backend/src/juli_backend/core/security`](../../backend/src/juli_backend/core/security/MODULE.md) | 1 | JWT verification, TikTok OAuth lifecycle, FastAPI auth dependency | `TikTokOAuthService`, `verify_supabase_jwt`, `get_current_user`, `Unauthorized` | Auth & Security |
| [`backend/src/juli_backend/api`](../../backend/src/juli_backend/api/MODULE.md) | 1 | FastAPI REST API (`/v1/*`) — thin adapters to owning services | `create_app`, `get_active_shop`; routes for shops, orders, products, creators, recommendations, action_cards, executions, outcomes | Backend API |
| [`backend/src/juli_backend/services/scoring`](../../backend/src/juli_backend/services/scoring/MODULE.md) | 1 | Rules-based scoring pipeline: aggregates → signals → recommendations → copy | `run_daily_scoring_for_shop`, `compute_scoring_signals`, `rank_workflow_recommendations`, `DailyScoringResult` | Intelligence |
| [`backend/src/juli_backend/services/action_cards`](../../backend/src/juli_backend/services/action_cards/MODULE.md) | 1 | Action card refresh orchestration + sole decision persistence writer | `run_action_card_refresh`, `persist_scoring_result`, `enqueue_action_card_refresh`, dispatcher ports | Intelligence |
| [`backend/src/juli_backend/services/execution`](../../backend/src/juli_backend/services/execution/MODULE.md) | 1 | Celery-backed approved tool dispatch | `enqueue_approved_tool`, `run_tool`, `run_tool_async`, `ExecutionStatus`, dispatcher ports | Workers & Async |
| [`backend/src/juli_backend/services/operations`](../../backend/src/juli_backend/services/operations/MODULE.md) | 2 | Workflow outcome tracking (partial — live pipeline deferred) | `record_workflow_outcome`, `load_workflow_outcome_metrics`, `build_workflow_outcome_metrics` | Workers & Async |
| [`backend/src/juli_backend/services/alerts`](../../backend/src/juli_backend/services/alerts/MODULE.md) | 2 | Multi-channel seller alerts: rule engine + delivery | `configure_rules`, `evaluate_rules`, `deliver_alert`, `FcmAdapter`, `ZaloOaAdapter` | Cross-cutting |
| [`backend/src/juli_backend/services/feedback`](../../backend/src/juli_backend/services/feedback/MODULE.md) | 2 | Campaign outcome ingest for calibration | `ingest_campaign_outcome`, `compute_calibration_weight` | Intelligence |
| [`backend/src/juli_backend/ai/recommendations`](../../backend/src/juli_backend/ai/recommendations/MODULE.md) | 2 | Decision generation: seller-action suggestions with justification + CTA | `get_host_product_matching`, `get_product_push_suggestions`, `get_stream_optimization` | Intelligence |
| [`apps/dashboard`](../../apps/dashboard/MODULE.md) | 2 | Next.js web app — UI for the three seller-money workflows (mock data in Phase 1) | `/login`, `/`, workflow pages | Frontend |
| [`apps/demo`](../../apps/demo/MODULE.md) | 2 | Standalone Next.js mock Demo; four-destination shell and sparse Home foundation | `/`, `/decisions`, `/analytics`, `/settings` | Frontend |
| [`packages/theme`](../../packages/theme/MODULE.md) | 1 | Framework-independent semantic product tokens | `@juli/theme/tokens.css` | Frontend |
| [`packages/ui`](../../packages/ui/MODULE.md) | 1 | Accessible shared React primitives | `DestinationCard`, `PrimaryNavigation` | Frontend |
| [`packages/utils`](../../packages/utils/MODULE.md) | 1 | Vietnamese money, number, date, and date-time formatters | `formatVND`, `formatNumber`, `formatDate`, `formatDateTime` | Frontend |
| [`packages/contracts`](../../packages/contracts/MODULE.md) | 1 | Shared TS contracts for execution lifecycle and review stages | `ExecutionRecord`, `ReviewStage`, `ExecutionTimelineStep`, workflow input descriptors | Frontend |
| [`ios`](../../ios/MODULE.md) | 2 | Native SwiftUI iOS app: demo auth, JWT Keychain storage, shop selection | `AuthService`, `KeychainService`, `APIClient` | Frontend |
| [`backend/ai/dataset`](../../backend/ai/dataset/MODULE.md) | 2 | Phase 1.5 backtest parquet assembly: synthetic data, schema validation, manifest | `assemble_backtest_dataset`, `validate_backtest_dataset`, `DatasetValidationError` | Intelligence |
| [`backend/ai/features`](../../backend/ai/features/MODULE.md) | 2 | Phase 1.5 feature engineering: parquet → per-model feature matrices | `build_seller_stage_features`, `build_anomaly_features`, `build_ad_features`, `FeatureMatrix` | Intelligence |
| [`backend/ai/seller_stage`](../../backend/ai/seller_stage/MODULE.md) | 2 | Phase 1.5 seller lifecycle classifier: rules baseline, train, rules-vs-ML compare | `classify_seller_stage`, `train_seller_stage`, `predict_seller_stage`, `compare_to_rules_baseline` | Intelligence |
| [`backend/ai/anomaly`](../../backend/ai/anomaly/MODULE.md) | 2 | Phase 1.5 buyer-behavior anomaly detector: item_swap / empty_return training + inference | `train_anomaly`, `predict_anomaly`, `build_anomaly_training_frame` | Intelligence |
| [`backend/ai/ad_performance`](../../backend/ai/ad_performance/MODULE.md) | 2 | Phase 1.5 ad performance analyzer: ROAS prediction + scale/cut/hold ranking | `train_ad_performance`, `predict_ad_action`, `build_ad_training_frame` | Intelligence |
| [`backend/ai/artifacts`](../../backend/ai/artifacts/MODULE.md) | 2 | Phase 1.5 model artifact publisher: joblib serialization, metadata, promotion gate, smoke tests | `publish_model`, `load_model`, `run_smoke_test`, `evaluate_promotion_status` | Intelligence |

## Phase 1.6 modules (deployed — listing workflow)

Tracked by [ADR-016](../adr/016-listing-workflow-implementation.md) and
`EXECUTION.md` slices P1.6-1…P1.6-5.

| Module | Tier | Responsibility | Public Surface | Owners |
|--------|------|----------------|----------------|--------|
| [`apps/dashboard/src/lib/mock-data/listing-workflow`](../../apps/dashboard/src/lib/mock-data/listing-workflow/MODULE.md) | 2 | Listing workflow mock fixtures: ProductDraft, Distributor, Opportunity | `loadDistributors`, `loadOpportunities`, `loadProductDrafts`, `validateListingFixtures` | Frontend |
| [`apps/dashboard/src/lib/workflows/new-seller/listing`](../../apps/dashboard/src/lib/workflows/new-seller/listing/MODULE.md) | 2 | Listing generation + export: rules engine, CSV/JSON serialize, state machine | `generateProductDraft`, `exportProductDraft`, `useListingWorkflow` | Frontend |
| [`apps/dashboard/src/lib/workflows/new-seller/shop-progress`](../../apps/dashboard/src/lib/workflows/new-seller/shop-progress/MODULE.md) | 2 | Session-scoped listing milestone + widget states | `loadShopProgress`, `recordExportCompleted`, `useShopProgress` | Frontend |
| [`apps/dashboard/src/components/workflows/new-seller/listing`](../../apps/dashboard/src/components/workflows/new-seller/listing/ListingWorkflowPanel.tsx) | 2 | Modal listing workflow from approved `list_products` | `ListingWorkflowPanel` | Frontend |
| [`apps/dashboard/src/components/workflows/new-seller/ListingProgressWidget`](../../apps/dashboard/src/components/workflows/new-seller/ListingProgressWidget.tsx) | 2 | Copilot home listing progress widget | `ListingProgressWidget` | Frontend |

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
- **Modular monolith:** runtime ownership in [`ownership-registry.yml`](ownership-registry.yml);
  import contract in [`import-boundaries.md`](import-boundaries.md); baseline score
  **5.5 / 10** in [boundary audit](../handoffs/modular-monolith-boundary-audit.html)
  ([#550](https://github.com/thienphung00/Juli-AI/issues/550)); post-MMU-1..8 facades
  documented in [`MODULES.md`](MODULES.md).

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
This file (`map.md`) is **as-built only**. Module goals and feature progression:
[`MODULES.md`](MODULES.md).

## Adding / removing a module

When adding: create `<module>/MODULE.md`, add a row above, update any diagrams,
commit together, and link the PR to the driving EXECUTION.md slice. When removing:
delete the row, search for and remove `MODULE.md` references in dependents, and run
`review` to surface stale callers.
