# Architecture Decision Records

| ADR | Title | Status |
|-----|-------|--------|
| [001](001-keep-python-fastapi.md) | Keep Python / FastAPI as backend runtime | Accepted |
| [002](002-supabase-backend-service.md) | Use Supabase as backend-as-a-service | Accepted |
| [003](003-ai-native-cicd-policy.md) | AI-native CI/CD policy (artifact-driven gates) | Accepted |
| [004](004-etl-kafka-consumer.md) | ETL ingest consumer module (handoff → Postgres) | Accepted |
| [005](005-alerts-module.md) | Alerts module with pluggable channel adapters | Superseded by 006 |
| [006](006-matching-pivot.md) | Pivot to Creator ↔ Shop Matching + commerce graph | Superseded by rescope |
| [007](007-ml-north-star-models.md) | North-star ML models + vendor feature ingestion | Superseded by rescope |
| [008](008-alert-vp-ahr-milestones.md) | Alert on VP/AHR milestones — not silent degradation | Accepted |
| [009](009-dual-read-vp-ahr-transition.md) | Dual-read VP + AHR during platform transition (May–July 2026) | Accepted |
| [010](010-vn-regional-platform-config.md) | VN-specific regional platform configuration | Accepted |
| [011](011-buyer-behavior-anomaly-scope.md) | Buyer-behavior anomaly scope — item swap + empty return only; no affiliate fraud ML | Accepted |
| [012](012-entity-centric-data-model.md) | Entity-centric canonical data model — `docs/data-models/` as ML schema authority | Accepted |
| [013](013-phase-15-ml-module-tree.md) | Phase 1.5 ML module tree under `src/modules/ml/` | Accepted |
| [020](020-new-seller-listing-workflow-scope.md) | New Seller listing workflow — P1.6 mock/rules, P2 publish slices | Accepted |
| [021](021-listing-rules-engine.md) | Listing rules engine — deterministic `generateProductDraft` (P1.6-3) | Accepted |
| [022](022-listing-workflow-ui.md) | Listing workflow UI — dual-path state machine from approved `list_products` (P1.6-2) | Accepted |

ADRs 006–007 are **historical**: the product was rescoped from creator↔shop
matching to **seller-money** workflows (New Seller Copilot, Revenue Leakage
Detection, Growth Copilot). The current plan and design live in
[`EXECUTION.md`](../../EXECUTION.md) and [`docs/system-design.md`](../system-design.md).

Referenced from [`docs/architecture/map.md`](../architecture/map.md).
