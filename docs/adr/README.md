# Architecture Decision Records

> **Tier 2 — decision rationale.** Read [`EXECUTION.md`](../../EXECUTION.md) and the relevant Tier 1 component doc first.  
> **Owns:** why, options considered, consequences. **Does not own:** slices, envelopes, module paths, or schemas.

| ADR | Title | Status |
|-----|-------|--------|
| [001](001-keep-python-fastapi.md) | Keep Python / FastAPI as backend runtime | Accepted |
| [002](002-supabase-backend-service.md) | Use Supabase as backend-as-a-service | Accepted |
| [003](003-ai-native-cicd-policy.md) | AI-native CI/CD policy (artifact-driven gates) | Accepted |
| [004](004-etl-kafka-consumer.md) | ETL ingest consumer module (Phase 3+ Kafka) | Accepted |
| [005](005-alert-vp-ahr-milestones.md) | Alert on VP/AHR milestones — not silent degradation | Accepted |
| [006](006-dual-read-vp-ahr-transition.md) | Dual-read VP + AHR during platform transition | Accepted |
| [007](007-vn-regional-platform-config.md) | VN-specific regional platform configuration | Accepted |
| [008](008-buyer-behavior-anomaly-scope.md) | Buyer-behavior anomaly scope | Accepted |
| [009](009-entity-centric-data-model.md) | Entity-centric canonical data model | Accepted |
| [010](010-ml-module-tree-and-trainers.md) | ML module tree, features, trainers, artifacts | Accepted |
| [011](011-display-grade-analytics-layer.md) | Display-grade analytics layer — T1–T8; layered model | Accepted |
| [012](012-architecture-reconciliation-mvp-vs-target.md) | Postgres MVP, Haiku copy, Railway; polyglot = Phase 3 | Accepted |
| [013](013-operations-pipeline-spine.md) | Operations pipeline spine | Accepted |
| [014](014-decision-copilot-app-structure-and-journey.md) | 3-tab IA + RRAA user journey | Accepted |
| [015](015-design-system-token-foundation.md) | Design system and token foundation | Accepted |
| [016](016-listing-workflow-implementation.md) | Listing workflow implementation | Accepted |
| [017](017-product-monorepo-deployment-architecture.md) | Product monorepo deployment architecture (Phase 2.5) | Accepted |
| [018](018-backend-runtime-migration.md) | Backend runtime migration to `backend/` (Phase 2.5-c) | Accepted |
| [019](019-src-shim-removal.md) | Remove `src/` compatibility shims after deploy entrypoint switch | Accepted |
| [020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) | VPS/SSH continuous delivery + AWS Secrets Manager (supersedes ADR-012 Railway line) | Accepted |
| [021](021-manual-refresh-pipeline-and-action-card-persistence.md) | Manual-refresh pipeline, Postgres-only Action Card persistence, Phase 2 scope reconciliation | Accepted |
| [022](022-intent-review-guardrails-split.md) | Intent-review / Guardrails split and structure authority | Accepted |
| [023](023-four-destination-analytics-ownership.md) | Four-destination IA and exclusive Analytics reporting ownership | Accepted |
| [024](024-phase-2.6-2.7-frontend-resequencing.md) | Phase 2.6/2.7 frontend resequencing, Demo mock/sign-in toggle, app boundaries | Accepted |
| [025](025-demo-workspace-transition.md) | Isolate the Demo dependency graph during workspace transition | Accepted |
| [026](026-phase-2.6-analytics-optional-exit-gate.md) | Analytics becomes a non-blocking Phase 2.6 exit-gate item (mirrors Settings/#405) | Accepted |
| [027](027-database-migration-safety-pipeline.md) | Database migration safety pipeline — local dev gate, DB-identity guard, restore drills | Accepted |
| [028](028-vietnamese-copy-dictionary-and-design-context.md) | Vietnamese copy dictionary + design-context split (no EN↔VI overlap) | Accepted |
| [029](029-phase-2.9-analytics-historical-backfill.md) | Phase 2.9 analytics historical backfill — shared schema, call budget, GMV buckets | Accepted |
| [030](030-operator-cli-in-memory-secrets.md) | Operator CLI in-memory Secrets Manager inject (no on-disk env for backfill path) | Accepted |
| [031](031-integrations-executor-domain.md) | Integrations executor domain (platform-agnostic) + domain skill upgrade shape | Accepted |
| [032](032-fujiwa-t1-gmv-experiment-scope.md) | Fujiwa T1 GMV experiment — single ETS model; defer Product/LIVE driver regression | Accepted |
| [033](033-weekly-secrets-security-check.md) | Weekly secrets-first security check (report + prepare; VPS + website leak paths) | Accepted |
| [034](034-tiktok-business-oauth-redirect-urls.md) | TikTok Business OAuth redirect URL pair (Advertiser + account holder) | Accepted |
