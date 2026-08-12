# Architecture Decision Records

> **Tier 2 — decision rationale.** Read [`EXECUTION.md`](../../EXECUTION.md) and the
> relevant Tier 1 planning doc first ([`MODULES.md`](../architecture/MODULES.md),
> `system-design.md`, …).  
> **Owns:** why, options considered, consequences. **Does not own:** slices, envelopes,
> module goals/paths, or schemas.

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
| [012](012-architecture-reconciliation-mvp-vs-target.md) | Postgres MVP, Haiku copy, Railway; polyglot = Phase 3 | Accepted — Railway line superseded by [020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) |
| [013](013-operations-pipeline-spine.md) | Operations pipeline spine | Accepted |
| [014](014-decision-copilot-app-structure-and-journey.md) | 3-tab IA + RRAA user journey | Partially superseded by [023](023-four-destination-analytics-ownership.md) |
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
| [035](035-public-release-evidence-and-automatic-rollback.md) | Public release evidence contract + automatic rollback | Accepted |
| [036](036-modules-tier1-planning-sot.md) | MODULES.md Tier-1 module planning SoT + doc tier ladder | Accepted |
| [037](037-phase-2.10-demo-real-data-no-auth.md) | Phase 2.10 — Demo real-data KPI wire without auth | Accepted |
| [038](038-phase-2.10-dual-layer-pipeline.md) | Phase 2.10 dual-layer pipeline — precompute + required cache | Accepted |
| [039](039-docp-phase-2.11-openobserve-posthog.md) | DOCP Phase 2.11 — OpenObserve + PostHog thin MVP | Accepted |
| [040](040-pr-safe-tests-lane.md) | PR-safe Tests lane (markers, timeouts, live on merge_group) | Accepted |
| [041](041-vps-redis-ephemeral-cache-and-celery.md) | VPS Redis — ephemeral cache + Celery DB split (Phase 2.10 A11) | Accepted |
| [042](042-module-docs-facade-sync.md) | MODULE.md + map.md sync to enforced facades (MMU-13) | Accepted |
| [043](043-frontend-design-skill-wiring.md) | Frontend design skill wiring — Open Design + Mobbin upstream of ui-ux | Accepted |
| [046](046-cdp-medallion-physical-model.md) | CDP medallion physical model — bronze / silver / gold / ops | Accepted |
| [047](047-cdp-lambda-layers-prd-split.md) | CDP Lambda layers and Phase 3.5 Analytics PRD split (A0 / A1 / A2) | Accepted |
| [048](048-cdp-webhook-first-spine-dual-credential.md) | Webhook-first CDP continuous spine and Demo dual credential model | Accepted |
| [049](049-demo-analytics-main-kpi-override.md) | Demo Analytics Main KPI override (CDP-backed Option B′) | Accepted |
| [050](050-cdp-slice-3-5-c-two-gated-exits.md) | CDP slice 3.5-C — two gated exits (C1 warm Sign-in, C2 cold-start) | Accepted |
| [051](051-tiktok-corpora-catalog-retrieval.md) | TikTok document corpora — catalog retrieval for Architect/Meta | Accepted |
| [052](052-wave-free-merge-deferred-artifact-gate.md) | Wave free-merge + deferred artifact gate | Accepted |
| [053](053-demo-home-activity-summary.md) | Demo Home activity summary — done/running/needs-attention counts above the launcher cards (apps/demo only) | Accepted |
| [054](054-brand-pink-role-separation.md) | Brand pink role separation — `--pink-text` for AA-compliant text, `--chart-neutral` for non-directional series | Accepted |
| [055](055-decision-plan-review.md) | Decision plan review — sectioned agent-proposed plan replaces the five-stage review (apps/demo mobile-web) | Accepted |
| [056](056-brand-asset-package.md) | Brand assets live in `packages/brand` — single owner for logo/photography/renders; no per-app copies | Accepted |
| [057](057-pre-user-delivery-on-single-vps.md) | Pre-user delivery stays on the single VPS — ADR-035's platform superseded, its evidence contract retained; re-entry triggers T1–T5 | Accepted |
| [058](058-release-packaging-shape.md) | Release packaging shape — build output plus a production dependency install, not `output: 'standalone'`; #837 ships both halves | Accepted |
| [059](059-dpr-wave-artifact-waiver.md) | Scoped artifact waiver for `wave-dpr-demo` — evidence unrecoverable, diffs reviewed in its place; not precedent | Accepted |
| [060](060-chart-form-follows-kpi-measurement-type.md) | Chart form follows KPI measurement type — measurement type selects the mark, goal direction selects the tone (apps/demo Analytics) | Proposed |
| [061](061-first-user-security-baseline.md) | First-user security baseline — default-deny data boundary + enforced invariants | Accepted |
| [062](062-security-baseline-wave-artifact-waiver.md) | Scoped artifact waiver for `wave-security-baseline` (six original slices only) | Accepted |
| [063](063-t10-inventory-reorder-engine.md) | T10 Inventory Reorder Engine — promote `ai/forecasting`'s velocity/depletion math into a lazy, per-SKU pre-execution advisory | Accepted |
| [064](064-product-performance-classifier.md) | Product Performance Classifier — real per-product GMV/conversion trend classification (Scale/Fix/Explore) for Optimize/Create Hero Product | Accepted |
| [065](065-finance-statement-fee-mapping-fix.md) | Finance Statement mapping fix — capture real `fee_amount`/`shipping_cost_amount`; drop phantom platform/affiliate commission split | Accepted |
| [066](066-t9-fee-adjusted-price-rule.md) | T9 fee-adjusted price rule — Optimize Product `price_update` gated by a real, shop-level fee floor from corrected `Settlement` data | Accepted |
| [067](067-livestream-script-recommendation.md) | Livestream script recommendation — rule-based 6-stage classification + LLM-personalized script catalog (pre/post-stream) | Accepted |
| [068](068-agent-workflow-execution-boundary.md) | Agent workflow execution — playbook-guided bounded authority, prod-read/sandbox-write boundary, AUTO/CONFIRM/NEVER tool policy, WorkflowRunStatus lifecycle | Proposed |
| [069](069-agent-tool-registry-and-write-path.md) | Agent tool registry — decision-point granularity (6 Optimize Product tools), in-run write path + ToolExecution audit, services/agent/tools ToolSpec module | Proposed |
| [070](070-agent-safe-sanitization-contract.md) | Agent-safe sanitization contract — context-bound IDs, source-role provenance, hard caps, error translation, dual-language banned-pattern guard | Proposed |
| [071](071-llm-service-openai-adapter.md) | LLM service — neutral block interface, stateless OpenAI Responses adapter (GPT-5.4 nano), turn-level blocks, fail-closed key assertion | Proposed |
| [072](072-agent-prompt-architecture.md) | Agent prompt architecture — monolithic versioned workflow prompts, typed Playbook artifact, EN instructions/VI exemplars, immutable versions + composed hash | Proposed |
| [073](073-agent-execution-loop-and-write-path-hardening.md) | Agent execution loop — WorkflowRunner + protocols, stop_reason termination policy, idempotency ledger, basis-hash concurrency control, P-CS/P7 deferral seams | Proposed |
| [074](074-agent-event-streaming-and-relay.md) | Agent event streaming — runner-owned sequences, Postgres-authoritative log + Redis relay, 8-event dual-language union, agent_runs queue + reaper, fetch-streaming SSE | Proposed |
| [075](075-agent-approval-gate-and-security-prerequisites.md) | Agent approval gate — approve-is-run-creation, multi-option decision requests with params-hash consent binding, authenticated demo, boot assertions, inbound limits, injection posture | Proposed |
