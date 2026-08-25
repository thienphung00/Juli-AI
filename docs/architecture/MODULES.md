# MODULES.md — Module planning SoT

> **Tier 1 — module catalog & progression.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** what each **planning module** is for; near-term **goals**; **feature** backlog
> (shipped / in progress / planned); out-of-scope; links into as-built and Tier-3 specs.  
> **Does not own:** phase/slice law (`EXECUTION.md`); pipeline envelopes (`system-design.md`);
> data-source phase gates (`data-sources.md`); as-built paths/endpoints (`map.md`);
> ADR rationale (`docs/adr/`); per-folder implementation stubs (`**/MODULE.md`).

**Audience:** Architect Agent + Developer (planning).  
**Authority:** `EXECUTION.md` > **this file** > `system-design.md` > `map.md`.  
**Decision:** [ADR-036](../adr/036-modules-tier1-planning-sot.md).

When MODULES and `map.md` disagree on **purpose / goals**, this file wins.  
When they disagree on **where code lives today**, `map.md` wins until this file is updated.

---

## How to use this file

| Need | Use |
|------|-----|
| What is the **codebase** doing this phase (multi-module)? | [`EXECUTION.md`](../../EXECUTION.md) |
| What should **this module** refine or add next? | **This file** |
| Pipeline stage shapes / JSON envelopes | [`system-design.md`](system-design.md) |
| Allowed / forbidden data sources | [`data-sources.md`](data-sources.md) |
| Deployed paths, public surfaces, `MODULE.md` links | [`map.md`](map.md) |
| Table / task / Redis / integration owners | [`ownership-registry.yml`](ownership-registry.yml) |
| Import contract + deep-import policy | [`import-boundaries.md`](import-boundaries.md) |
| Boundary audit baseline score | [modular-monolith-boundary-audit.html](../handoffs/modular-monolith-boundary-audit.html) · [#550](https://github.com/thienphung00/Juli-AI/issues/550) |
| Why a constraint exists | [`docs/adr/`](../adr/README.md) |
| Precise implementation contracts | Tier 3: issue AC, `**/MODULE.md`, `docs/api/`, curated `tiktok_api/` |

**Phase vs module progression**

- **EXECUTION.md** = phase/slice progression of the **whole codebase**. One phase may
  implement **several modules in parallel**.
- **MODULES.md** = **per-module** progression — refinement + new features — independent
  of whether an EXECUTION slice currently touches that module.

**Entry schema** (every top-level module)

- **Status:** `as-built` | `partial` | `planned` | `reference`
- **Path:** primary code/docs path(s)
- **Purpose:** what the module is for
- **Goals:** near-term outcomes (refinement + capability)
- **Features:** Shipped / In progress / Planned
- **Related EXECUTION slices:** optional cross-links (do not duplicate slice text)
- **Out of scope**
- **Links:** map · MODULE.md · key ADRs

Nested children use a short form when their backlog differs from the parent.

---

## Documentation tier ladder

Higher tiers cover **more of the system with less detail** (planning SoT).  
Lower tiers add **specs and precision** for implementation.

| Tier | Role | Primary files |
|------|------|----------------|
| **0** | Phase law — multi-module codebase progression | `EXECUTION.md` |
| **1** | System / module planning SoT | **MODULES.md**, `system-design.md`, `data-sources.md` |
| **2** | Rationale + as-built registry | `docs/adr/*`, `map.md`, phase PRDs / runbooks as needed |
| **3** | Implementation precision | `**/MODULE.md`, issue AC, `docs/api/*`, curated integrations docs |

**Architect / Developer planning read order:** EXECUTION → MODULES → system-design (if envelopes) → map (paths only).  
**Executor read order:** issue AC + `MODULE.md` + contracts; load MODULES for goals / out-of-scope only.

---

## Modular monolith upgrade ([#550](https://github.com/thienphung00/Juli-AI/issues/550))

Parent epic for hardening module boundaries without splitting deployables. Baseline
**5.5 / 10** modular-monolith score from the
[boundary audit](../handoffs/modular-monolith-boundary-audit.html)
(2026-07-28); target **~9 / 10** when ownership and import contracts are
enforceable — falsifiable exit criteria tracked in MMU-15 (#565).

| Artifact | Role |
|----------|------|
| [Boundary audit](../handoffs/modular-monolith-boundary-audit.html) | Static-import graph + runtime write-path narrative (baseline score) |
| [`modular-monolith-audit-data.json`](../handoffs/modular-monolith-audit-data.json) | Machine-readable modules, edges, enforcement snapshot |
| [`ownership-registry.yml`](ownership-registry.yml) | Table / Celery task / Redis namespace / integration owners (MMU-1) |
| [`import-boundaries.md`](import-boundaries.md) · [`.importlinter.toml`](../../.importlinter.toml) | Allowed dependency matrix + deep-import policy (MMU-2) |
| [Modular Monolith Upgrade PRD](../product/phases/modular-monolith-upgrade/PRD.md) | Problem, slices, CI mindset |

**Landings through MMU-8 (2026-07-28):** ownership registry; import-linter contract
(warn-capable until MMU-3 #556); TikTok package facade (MMU-5); Celery dispatcher
ports in Action Cards + Execution (MMU-6); one-way Execution → Operations outcome
contract (MMU-7); thin webhook/TikTok-auth API adapters (MMU-8). Same wave also
shipped decision-persistence centralization (MMU-11), ETL ingest-table ownership
clarity (MMU-9), and Redis key namespace registry (MMU-12).

**Cross-module rule:** callers import published package facades (`__init__.py`
`__all__` / MODULE.md Public Interface) only — see
[`ownership-registry.yml`](ownership-registry.yml) `boundaryGuidance.doNotImport`
and `.cursor/rules/patterns.mdc`. The `workers` package owns Celery app wiring;
domain modules own task semantics via thin `workers/tasks/*` wrappers listed in the
registry.

---

## Module index

| Module | Status | Path (primary) |
|--------|--------|----------------|
| [Frontend](#1-frontend) | as-built | `apps/` · `packages/` · `ios/` |
| [Backend API](#2-backend-api) | as-built | `backend/src/juli_backend/api/` |
| [Auth & Security](#3-auth--security) | as-built | `core/security` · OAuth routes |
| [Database](#4-database) | as-built | `database/` · `models/` · `repositories/` |
| [Data Pipeline](#5-data-pipeline) | as-built | `services/{webhook,ingestion,etl,aggregates,analytics_backfill}` |
| [Integrations](#6-integrations) | as-built | `integrations/tiktok/` (+ adhoc doc crawlers) |
| [Intelligence](#7-intelligence) | partial | `services/scoring` · `ai/*` |
| [Workers & Async](#8-workers--async) | as-built | `workers/` · `services/execution` |
| [Edge / Gateway](#9-edge--gateway) | as-built | `infra/nginx` · `infra/systemd` |
| [Cross-cutting](#10-cross-cutting) | partial | scattered primitives |
| [Agent Runtime](#11-agent-runtime) | partial | `agent-runtime/` · `.cursor/skills/` |
| [CI/CD & Infra](#12-cicd--infra) | as-built | `.github/workflows` · `infra/scripts` |
| [Docs & Governance](#13-docs--governance) | as-built | `docs/` · `EXECUTION.md` · `CONTEXT.md` |
| [Testing](#14-testing) | as-built | `tests/` · `agent-runtime/scripts/validate` |

**Omitted from this catalog:** Sentry/APM (not a planning module yet); empty
`integrations/{identity,catalog,ordering}/` stubs (no source — cleanup later; not modules).

---

## 1. Frontend

- **Status:** as-built
- **Path:** `apps/demo`, `apps/dashboard`, `packages/{theme,ui,utils,contracts}`, `ios/`
- **Purpose:** Seller-facing and public UI surfaces (web + iOS) over shared design tokens
  and contracts.
- **Goals:**
  - Keep Demo as the public Interactive Demo product; Dashboard as authenticated seller path.
  - Preserve four-destination IA (Home / Decisions / Analytics / Settings) on Demo.
  - Share theme/ui/utils/contracts without duplicating design language.
  - Phase 2.10: wire Analytics then Decisions to masked precomputed envelopes (Mock mode).
- **Features:**
  - **Shipped:** Demo shell + destinations; Dashboard App Review / workflow surfaces;
    shared packages; iOS auth + shop select baseline.
  - **In progress:** Phase 2.10-A/B Demo real-data wire (Architect/EXECUTION).
  - **Planned:** Phase 3 Sign-in/Login hybrid; Phase 3.5 production web app; iOS deepen
    when EXECUTION schedules it.
- **Related EXECUTION slices:** Phase 2.6 / 2.7 / 2.10 / 3 / 3.5 frontend themes
- **Out of scope:** Backend scoring logic; TikTok HTTP client internals; Seller Center scraping UI.
- **Links:** [`map.md`](map.md) · [`apps/demo/MODULE.md`](../../apps/demo/MODULE.md) ·
  [`apps/dashboard/MODULE.md`](../../apps/dashboard/MODULE.md) · ADR-014, ADR-023, ADR-024,
  ADR-025, ADR-037, ADR-038

### 1.1 Demo (`apps/demo`)

- **Status:** as-built · **Path:** `apps/demo`
- **Purpose:** Public Interactive Demo (`demo.app-juli.com`) — mock in 2.6; masked real
  data in Phase 2.10 (no auth); Sign-in in Phase 3.
- **Goals:** Public HTTPS story + Mock/Sign-in toggle; Fake Demo Refresh in Mock;
  dry-run Decision execution in 2.10-B.
- **Features:** Shipped four-destination shell; **Planned:** 2.10-A Analytics wire;
  2.10-B Decisions wire (Home/Settings stay mock); Phase 3 Sign-in.

### 1.2 Dashboard (`apps/dashboard`)

- **Status:** as-built · **Path:** `apps/dashboard`
- **Purpose:** Seller dashboard / App Review web surface; workflows and decision UI heritage.
- **Goals:** TBD (Architect) relative to Demo consolidation in later phases.
- **Features:** Shipped workflow panels + App Review paths; Planned Phase 3.5 production app role.

### 1.3 Shared packages

- **Status:** as-built · **Path:** `packages/{theme,ui,utils,contracts}`
- **Purpose:** Cross-app design tokens, primitives, formatters, shared TS contracts.
- **Goals:** Single design language; contracts stay aligned with backend envelopes.
- **Features:** Shipped theme/ui/utils/contracts baseline; Planned contract expansion as APIs harden.

### 1.4 iOS (`ios/`)

- **Status:** as-built · **Path:** `ios/`
- **Purpose:** Native SwiftUI client (auth, Keychain JWT, shop selection).
- **Goals:** TBD (Architect) for Phase 4 sync / deepen.
- **Features:** Shipped demo auth baseline; Planned Web ↔ Mobile sync (Phase 4 theme).

---

## 2. Backend API

- **Status:** as-built
- **Path:** `backend/src/juli_backend/api/`
- **Purpose:** Versioned FastAPI REST surface (`/v1/*`) and ASGI entry for the modular monolith.
- **Goals:**
  - Keep HTTP handlers thin — enqueue Celery; do not run scoring/tools inline.
  - **MMU-8:** routers delegate to one owning application service; no leaf
    `integrations/tiktok.*` or inline ETL/TikTok assembly in routes.
  - Stable shop-scoped envelopes for Frontend and iOS.
  - TBD (Architect): route surface cleanup vs legacy recommendation paths.
- **Features:**
  - **Shipped:** shops, orders, products, creators, recommendations, action_cards,
    executions, outcomes, workflow_outcomes, TikTok auth + webhook mounts, `/health`, CORS;
    MMU-8 thin adapters for webhook + TikTok OAuth routes.
  - **In progress:** TBD per active API issues.
  - **Planned:** Public Demo read APIs (masked envelopes, server-bound shop) for Phase 2.10;
    Login-mode routes in Phase 3.
- **Related EXECUTION slices:** Phase 2 pipeline validation API work; Phase 2.10
- **Out of scope:** Vendor signing/rate-limit internals (Integrations); Celery task bodies (Workers).
- **Links:** [`api/MODULE.md`](../../backend/src/juli_backend/api/MODULE.md) ·
  [`ownership-registry.yml`](ownership-registry.yml) · [`import-boundaries.md`](import-boundaries.md) ·
  ADR-001, ADR-038

---

## 3. Auth & Security

- **Status:** as-built
- **Path:** `backend/src/juli_backend/core/security/`, TikTok OAuth routes, `services/tiktok`
- **Purpose:** Identity at the edge of Juli — Supabase JWT, TikTok OAuth lifecycle,
  encrypted credential storage, webhook HMAC verification.
- **Goals:**
  - AuthZ at service layer (not only routers).
  - Safe secret handling; no secrets in git.
  - **Registry:** sole write owner for `users`, `shops`, `tiktok_credentials`
    ([`ownership-registry.yml`](ownership-registry.yml)); dual-writer debt on
    `shops` / `tiktok_credentials` (`core/security` OAuth vs `services/tiktok`) —
    collapse tracked in MMU-10 (#562).
  - TBD (Architect): production auth UX beyond Demo/App Review patterns.
- **Features:**
  - **Shipped:** JWT verify · TikTok Shop OAuth · Business holder/advertiser auth routes ·
    token crypto · webhook HMAC.
  - **In progress:** TBD.
  - **Planned:** **First-user security baseline ([ADR-061](../adr/061-first-user-security-baseline.md))** —
    a startup assertion making `SUPABASE_JWT_SECRET` required (it currently defaults to `""`,
    so auth fails open when the var is unset); a route-auth CI invariant asserting every `/v1/*`
    route carries `get_current_user` / `get_active_shop`; closing the unauthenticated
    `/debug/tiktok/verify-connection` cross-tenant probe; gating `docs_url` / `redoc_url` on a new
    `ENVIRONMENT` discriminator (none exists today). Then Phase 3 Demo Sign-in OAuth;
    Phase 3.5 full web auth.
- **Related EXECUTION slices:** App Review / Phase 3 auth themes
- **Out of scope:** Buyer PII stores; Seller Center scrape auth.
- **Links:** [`core/security/MODULE.md`](../../backend/src/juli_backend/core/security/MODULE.md) ·
  [`ownership-registry.yml`](ownership-registry.yml) · ADR-002, ADR-034, ADR-061

---

## 4. Database

- **Status:** as-built
- **Path:** `backend/src/juli_backend/database/`, `models/`, `repositories/`
- **Purpose:** Supabase Postgres as the operational source of truth — schema, repos,
  migration safety.
- **Goals:**
  - Schema-only Alembic + migration safety gate on every upgrade.
  - Clear tenancy (shop-scoped) and decisioning tables for Action Cards / executions.
  - **Registry:** Supabase Postgres session + Alembic infra owner; table-level
    stewards live in [`ownership-registry.yml`](ownership-registry.yml) (logical
    owners — physical `models/` / `repositories/` split deferred).
  - **Facade:** lazy PEP 562 re-exports on `juli_backend.database` avoid import
    cycles with `repositories.repos` at startup.
  - Plan polyglot only when volume/latency justify it.
- **Features:**
  - **Shipped:** SQLAlchemy models/repos; Alembic; users/shops/credentials; commerce;
    ingestion ledgers; action_cards / tool_executions / outcomes; safe-alembic pipeline.
  - **In progress:** Analytics historical schema usage (Phase 2.9 themes).
  - **Planned:** KPI / intelligence precompute tables for Phase 2.10 read model;
    Polyglot target (ClickHouse / S3 / SQS) — **rejected for Phase 3.5** by
    [ADR-046](../adr/046-cdp-medallion-physical-model.md) and
    [ADR-047](../adr/047-cdp-lambda-layers-prd-split.md) in favour of Postgres medallion
    schemas (`bronze`/`silver`/`gold`/`ops`) in the existing Supabase project. Revisit only
    if volume/latency justifies it; **default-deny `public` boundary ([ADR-061](../adr/061-first-user-security-baseline.md))** —
    extend migration 021's `ALTER DEFAULT PRIVILEGES` revoke to `public` so new tables are born
    closed (thirteen tables carry no RLS today, two of which landed in the last week), and treat
    the ten `current_setting('app.current_user_id')` policies as **non-functional** until they are
    rewritten onto `auth.uid()` for `gold` at 3.5-C.
- **Related EXECUTION slices:** Phase 2 data plane; 2.9 backfill; 2.10 precompute; later polyglot
- **Out of scope:** Treating Alembic as a data migration/backup tool; buyer CDP as current mandate.
- **Links:** [`database/MODULE.md`](../../backend/src/juli_backend/database/MODULE.md) ·
  ADR-002, ADR-027, ADR-029, ADR-038, ADR-046, ADR-061

---

## 5. Data Pipeline

- **Status:** as-built
- **Path:** `services/webhook`, `ingestion`, `etl`, `aggregates`, `analytics_backfill`;
  polling under `workers/services/polling`
- **Purpose:** Official TikTok → normalize → persist → aggregate spine that feeds scoring.
- **Goals:**
  - Idempotent ingest (`processed_events` — ETL exclusive per registry); reliable handoff contracts.
  - Keep polling + webhooks within rate budgets.
  - Phase 2.10: material-webhook enqueue → transform/compute → precompute; hourly Mock
    reconciliation for reference shop; #68 15‑min coalesce.
  - **Registry:** sole write owner for commerce ingest tables, webhook audit tables,
    and material-analytics Redis mutex/coalesce keys
    ([`ownership-registry.yml`](ownership-registry.yml)).
  - Improve DLQ durability / replay semantics over time (refinement).
- **Features:**
  - **Shipped:** Webhook verify→handoff; polling sync (orders/products/returns/…);
    ETL dedup/transform; aggregates; analytics backfill with call budget.
  - **In progress:** Historical analytics backfill partitions (Phase 2.9).
  - **Planned:** Phase 2.10 material compute triggers + KPI precompute T/L; stronger
    DLQ/replay; event-stream path only when EXECUTION reaches real-time phases.
- **Related EXECUTION slices:** P2 pipeline; P2.9 backfill; P2.10 dual-layer wire
- **Out of scope:** Unofficial livestream websockets; Seller Center scraping
  (see `data-sources.md` Forbidden).
- **Links:** webhook / ingestion / etl MODULE.md files · ADR-021, ADR-029, ADR-038

---

## 6. Integrations

- **Status:** as-built (client) · partial (doc corpora)
- **Path:** `backend/src/juli_backend/integrations/tiktok/`; OAuth/webhook domain
  services under `services/tiktok/`; adhoc crawlers under
  `.worktrees/adhoc/scripts/{academy,partner,business}_crawler/`
- **Purpose:** Vendor I/O boundary — TikTok Partner API client (auth, signing, rate limit,
  resources) plus OAuth/webhook domain services and documentation corpora for agent knowledge.
- **Goals:**
  - **MMU-5:** import HTTP client only via package-root facade
    (`from juli_backend.integrations.tiktok import …`); leaf modules stay internal.
  - Keep `integrations/tiktok/` a leaf HTTP client (no DB / business rules inside).
  - `services/tiktok/` owns webhook catalog, signature verify, OAuth infrastructure —
    API routes delegate (MMU-8).
  - Process Academy / Partner / Business crawled docs → promote curated subset → agent context
    (and later RAG).
  - Do not resurrect empty `identity/` / `catalog/` / `ordering/` folders as modules.
- **Features:**
  - **Shipped:** TikTok client package facade (`__all__` re-exports auth, client,
    rate limiter, resources, factories, mapping, exceptions); Redis `ratelimit:*`
    namespace (registry); resource modules; merchant/capability guards; webhook
    catalog mapping in `services/tiktok`.
  - **In progress:** Adhoc crawls (~2.4k markdown) local-only; curated
    `docs/integrations/tiktok_api` + `tiktok_platform` on main.
  - **Planned:** Normalize/promote corpora via `api-docs` / `platform-docs`; optional RAG
    over adhoc corpora; Marketing API curated docs when product scope needs them.
- **Related EXECUTION slices:** Integrations / TikTok slices; doc work may be adhoc-parallel
- **Out of scope:** Runtime Seller Center scraping; treating stale DDD folder names as live modules.
- **Links:** [`integrations/tiktok/MODULE.md`](../../backend/src/juli_backend/integrations/tiktok/MODULE.md) ·
  ADR-031

---

## 7. Intelligence

- **Status:** partial
- **Path:** `services/scoring`, `services/action_cards`, `backend/src/juli_backend/ai/*`, `docs/ml/`
- **Purpose:** Display-grade advisory — signals, ranked workflow recommendations, copy —
  plus trained artifact pipelines for later production inference.
- **Goals:**
  - Phase 2: rules scoring + rules copy; (refresh trigger evolved in 2.10 — ADR-038).
  - Preserve visual / ML / execution layer separation (advisory never auto-executes).
  - Phase 2.10: shared precompute feeds Analytics + Decisions; emission budget +
    threshold config; Demo dry-run only.
  - **Registry:** sole write owner for `action_cards`, legacy `recommendations`,
    `analytics_kpi_envelopes`, `campaigns`, `graph_edges`; Redis
    `analytics:kpi_envelope:*` cache namespace.
  - **Facades:** `services/scoring` and `services/action_cards` publish package-root
    APIs; refresh enqueues via dispatcher port (MMU-6), not direct `workers.tasks` import.
  - Promote trained techniques only through gates; live ML inference per EXECUTION phase.
- **Features:**
  - **Shipped:** Manual refresh pipeline; rules signals/recs/copy; Phase 1.5 trainers
    (dataset, features, seller_stage, anomaly, ad_performance, artifacts); recommendations helpers.
  - **Decision persistence (MMU-11):** `services/action_cards` is the sole write owner for
    `action_cards` and retained legacy `recommendations`; API routes delegate, scoring +
    legacy persist stay in the owning module.
  - **In progress:** Fujiwa T1 experiment / backtest pathfinders as scheduled.
  - **Planned:** Phase 2.10-A KPI envelopes; 2.10-B rules wire + emission budget;
    Haiku copy (Phase 4); production inference schedule.
- **Related EXECUTION slices:** Phase 2 scoring; 2.9-B T1; 2.10-A/B; Phase 4 ML/LLM
- **Out of scope:** Autonomous execution without approval; inventing KPIs without ETL fields;
  net-new classifier stack in 2.10.
- **Links:** [`services/scoring/MODULE.md`](../../backend/src/juli_backend/services/scoring/MODULE.md) ·
  ADR-011, ADR-021, ADR-032, ADR-038

---

## 8. Workers & Async

- **Status:** as-built
- **Path:** `backend/src/juli_backend/workers/`, `services/execution`
- **Purpose:** Celery-backed async work — scoring refresh, approved tool execution, polling orchestration.
- **Goals:**
  - HTTP never runs tools or scoring inline.
  - Idempotent tool executions with clear status/outcome records.
  - **Registry:** write owner for `tool_executions`, `workflow_outcome_records`,
    `tiktok_sync_state`; Celery broker key space.
  - **MMU-6:** domain modules enqueue via dispatcher ports (`enqueue_approved_tool`,
    `enqueue_action_card_refresh`); `workers/tasks/*` are thin wrappers only.
  - **MMU-7:** Execution records workflow outcomes; Operations reads via one-way
    public contract — no execution ↔ operations import cycle.
  - Expand tool handlers as execution-layer workflows go live.
- **Features:**
  - **Shipped:** Celery app + Redis broker; `refresh_action_cards`; `execute_approved_tool`;
    listing handlers; rate-limit backoff in polling.
  - **In progress:** TBD tool surface vs EXECUTION execution slices.
  - **Planned:** Phase 2.10 material-webhook / hourly compute tasks; Demo dry-run
    execution path; Login-mode real refresh tasks in Phase 3; broader live executors
    when EXECUTION schedules them.
- **Related EXECUTION slices:** P2-B execution / tool slices; P2.10; Phase 3 Sign-in
- **Out of scope:** Inline tool runs from FastAPI handlers; Mock Demo using merchant
  credentials for Partner writes.
- **Links:** [`services/execution/MODULE.md`](../../backend/src/juli_backend/services/execution/MODULE.md) ·
  ADR-038

---

## 9. Edge / Gateway

- **Status:** as-built
- **Path:** `infra/nginx/`, `infra/systemd/`
- **Purpose:** Public edge — TLS termination and reverse proxy to loopback app processes
  (Nginx is the API gateway; no separate gateway product).
- **Goals:**
  - Independent Demo vs App Review vs API vhosts.
  - Health-friendly proxy paths for smoke and release evidence.
- **Features:**
  - **Shipped:** `app-juli.com` → :3000; `demo.app-juli.com` → :3001; `api.app-juli.com` → :8000;
    systemd units; secrets-refresh / restore-drill timers.
  - **In progress:** Public release evidence / rollback automation refinements (ADR-035).
  - **Planned:** **Inbound rate limiting ([ADR-061](../adr/061-first-user-security-baseline.md))** — `limit_req`
    zones per location (strict on `/webhooks/tiktok`, `/v1/demo/*`, `/v1/auth/*`); the edge is the
    only layer that can defend a `--workers 1` uvicorn, and no inbound throttling exists anywhere
    today. Also `--proxy-headers` so access logs carry the real client IP rather than `127.0.0.1`.
    Then TBD (Architect) if multi-host topology ever replaces single-VPS edge.
- **Related EXECUTION slices:** Phase 2.5+ deploy; Demo deploy
- **Out of scope:** Kong/AWS API Gateway unless an ADR supersedes VPS edge.
- **Links:** `infra/README.md` · ADR-020, ADR-035, ADR-057, ADR-061

---

## 10. Cross-cutting

- **Status:** partial
- **Path:** primitives across backend + infra (no single package root)
- **Purpose:** Shared resilience and safety mechanisms used by many modules.
- **Goals:**
  - Keep rate limiting, idempotency, and migration safety as named capabilities
    developers reuse instead of reinventing.
  - **Registry:** `alert_configs` / `alert_history` write owner; Redis infra
    consumer map; future app caches use `juli:<module>:` prefix (MMU-12) with
    grandfathered allowlist for legacy keys — see [`ownership-registry.yml`](ownership-registry.yml).
  - Improve DLQ durability and observability deliberately (not via drive-by APM).
- **Features:**
  - **Shipped:** Redis TikTok rate limiter; ingest + tool idempotency keys; CORS;
    secrets fetch/refresh; safe-alembic; `/health` + smoke scripts.
  - **In progress:** Release evidence / rollback automation.
  - **Planned:** **Required** Redis read-through cache for Analytics/Decision envelopes
    (Phase 2.10 — ADR-038); stronger DLQ persistence/replay;
    **security logging baseline ([ADR-061](../adr/061-first-user-security-baseline.md))** — root `dictConfig`
    JSON logging (none is configured today, so every `logger.info` is discarded and every
    `logger.warning` loses its `extra` context), `request_id` middleware, and coverage of webhook
    signature rejections and auth failures. A vendor-free floor beneath DOCP (ADR-039), not a
    replacement for it.
- **Related EXECUTION slices:** infra / reliability slices; Phase 2.10
- **Out of scope:** Sentry/APM as a required module until product adopts it explicitly;
  Redis as system of record.
- **Links:** ADR-027, ADR-033, ADR-035, ADR-038, ADR-061

---

## 11. Agent Runtime

- **Status:** partial *(gates strong; Agentic Version 1 measured loop complete on #513; Version 2+ remaining)*
- **Path:** `agent-runtime/`, `.cursor/skills/`, `reference/hermes-agent/`
- **Purpose:** HITL agentic development harness — phases, artifacts, validate gates —
  that builds the product (not a seller-facing runtime service).
- **Goals:**
  - Architect plans from EXECUTION + **MODULES** (ADR-036); Meta routes; Executor TDD;
    Review validates — Focus must load MODULES for planning/module tasks.
  - Keep prompt caches and artifact schemas honest; record workflow-cache outcomes in
    validation `checks[]`.
  - Close **Agentic Version 1**: at least one live proposed → applied → measured harness
    loop (not fixture-only); **measured complete** on issue **#513** (C4c).
  - Enforce intent-review artifact presence in CI (parity with Guardrails contract).
  - Maintain canonical doc paths (`agent-runtime/docs/agent-runtime.md`; no `web/` or
    `decisions/` drift).
  - Use hermes-agent as **reference** only.
- **Features:**
  - **Shipped:** Four agent phases; Focus router; five domain executors; 26 validate
    checkers; workflow-cache Meta gate; ADR-003 CI on `issue-<N>`; public-release plan
    chain (ADR-035); quickCommitSkip; L0–L5 context hierarchy; intent-review/guardrails
    split (ADR-022); MODULES Tier-1 in Focus (ADR-036); canonical doc path hygiene
    (Candidates 1–3 on this branch).
  - **In progress:** Public-release evidence habit; Meta optimization artifacts (mostly
    `proposed`); Agentic Version 1 measured loop **complete** on **#513** (C4c).
  - **Planned:** Habitual harness_optimizer apply/measure after Version 1 exit; product-dev-opt
    → Architect backlog cadence; intent-review CI check; validation artifact completeness for
    workflow-cache gates.
- **Related EXECUTION slices:** N/A as product phase — always-on for issue branches
- **Out of scope:** Auto-shipping without human/PR gates; Meta implementing features;
  Sentry as harness dependency.
- **Links:** [`agent-runtime/docs/agent-runtime.md`](../../agent-runtime/docs/agent-runtime.md) ·
  [`agent-runtime-migration.md`](../../agent-runtime/docs/agent-runtime-migration.md) ·
  evaluation canvas (IDE) · ADR-003, ADR-022, ADR-035, ADR-036

### 11.1 Hermes reference

- **Status:** reference · **Path:** `reference/hermes-agent/`
- **Purpose:** Research code for prompt building, context compression, prompt caching.
- **Goals:** Inform agent-runtime improvements; do not import as a product dependency casually.
- **Features:** Shipped reference sources; Planned selective pattern adoption via harness ADRs.

### 11.2 Quality snapshot (2026-07-27)

| Area | Assessment |
|------|------------|
| Issue-branch CI gates | Strong |
| Meta → Executor hard gate | Strong |
| Review-phase intent-review CI | Weak (~49 vs ~159 review artifacts) |
| Agentic Version 1 optimization loop | Measured complete on #513 (C4c) — `context.max_files` 25→20; evaluate improved |
| MODULES Tier-1 in Focus | Wired (this branch) |
| Canonical doc path hygiene | Improved (path drift fixed on this branch) |

**Eval checklist:** see IDE canvas `agentic-workflow-evaluation` (12 checks) before
declaring this module healthy for heavier Phase 3+ reliance.

---

## 12. CI/CD & Infra

- **Status:** as-built
- **Path:** `.github/workflows/`, `infra/scripts/`, `infra/deploy/`
- **Purpose:** Validate, deploy, rollback, and provision the VPS continuous-delivery path.
- **Goals:**
  - PR green = product tests + agent-runtime gates when applicable.
  - Safe release cutover with evidence; independent Demo deploy where required.
- **Features:**
  - **Shipped:** `pr.yml`, `release.yml`, rollback/uptime/architecture-audit workflows;
    deploy/rollback/smoke/provision scripts; Demo independent deploy path.
  - **In progress:** Public release evidence + automatic rollback (ADR-035).
  - **Planned:** **Security invariants suite ([ADR-061](../adr/061-first-user-security-baseline.md))** — a
    data-boundary assertion hung off the existing `migration-check` job (creating the
    `anon`/`authenticated` roles there also gives ADR-046's medallion revokes their first real test
    coverage, since its `IF EXISTS` guards skip on every CI run today), a route-auth walk, a
    debug-surface check, a credentials-in-query-string lint, and an Nginx `limit_req` conf lint.
    Then TBD (Architect) for staging topology if EXECUTION ever requires it.
- **Related EXECUTION slices:** Phase 2.5 deployment architecture onward
- **Out of scope:** Railway/Vercel as primary App Review runtime (superseded by VPS ADRs).
- **Links:** `infra/README.md` · ADR-017, ADR-020, ADR-035, ADR-061

---

## 13. Docs & Governance

- **Status:** as-built
- **Path:** `docs/`, `EXECUTION.md`, `CONTEXT.md`, `dictionary.md`
- **Purpose:** Canonical planning memory — phase law, module goals, envelopes, ADRs,
  product/ML docs, Vietnamese copy authority.
- **Goals:**
  - Keep Tier ladder honest: planning SoTs stay broad; Tier 3 stays precise.
  - Curate TikTok API + platform docs for agents; promote from crawlers carefully.
- **Features:**
  - **Shipped:** EXECUTION, architecture Tier 1 set, ADRs, integrations docs, ML/product
    docs, CONTEXT, dictionary, design-context; MMU-1 `ownership-registry.yml`;
    MMU-2 `import-boundaries.md` + `.importlinter.toml`.
  - **In progress:** MMU-15 exit scorecard vs boundary audit; MMU-3 required PR architecture gates.
  - **Planned:** Promote Academy/Partner/Business corpus subsets; close Seller Feature Guide gaps.
- **Related EXECUTION slices:** documentation updates ride with phase work
- **Out of scope:** Inventing Vietnamese copy outside `dictionary.md` governance.
- **Links:** [`docs/README.md`](../README.md) · [`ownership-registry.yml`](ownership-registry.yml) ·
  [boundary audit](../handoffs/modular-monolith-boundary-audit.html) · ADR-028, ADR-036

---

## 14. Testing

- **Status:** as-built
- **Path:** `tests/`, `agent-runtime/scripts/validate/`
- **Purpose:** Product correctness (pytest/turbo) plus harness validate gates for
  agent-produced work.
- **Goals:**
  - Deterministic unit/integration coverage for critical spines.
  - Issue branches prove TDD evidence, artifacts, and release-evidence when required.
- **Features:**
  - **Shipped:** unit/integration/fixtures/harness tests; ruff/mypy/pytest in CI;
    validate checkers (TDD, module boundaries, ADR, release evidence, …); deploy config tests;
    smoke runbooks; import-boundary AST checker (`check_import_boundaries.py`).
  - **In progress:** Public-release verification depth.
  - **Planned:** TBD (Architect) E2E browser depth vs smoke balance.
- **Related EXECUTION slices:** all implementation slices
- **Out of scope:** Weakening flaky tests to go green.
- **Links:** ADR-003 · validate scripts under `agent-runtime/scripts/validate/`

---

## 16. Agent Execution

- **Status:** partial *(W1–W4 landed and deployed; W5–W10 remaining — see
  [PLAN.md](../product/agent-workflow-execution/PLAN.md))*
- **Path:** `backend/src/juli_backend/services/agent/` (`tools/`, `llm/`, `sanitize/`,
  `prompts/`, `playbooks/`, `runner/`, `events/`), `workers/tasks/agent_workflow.py`,
  `workers/tasks/reaper.py`, `workers/tasks/credential_refresh_beat.py`,
  `api/routes/agent_runs.py`, `packages/contracts/src/agent-events.ts`
- **Purpose:** The **seller-facing agent** that executes a workflow end to end — LLM loop,
  guarded tool dispatch, write-path ledger, event stream, approval pause.
- **Not to be confused with §11 Agent Runtime**, which is the HITL *harness that builds the
  product*. §11 is `agent-runtime/` and `.cursor/skills/`; §16 is the product runtime a seller
  actually triggers. The two were conflated until #1136 because §16 did not exist, and §11 was
  never in `planningModules` either — so every agent-era table was filed under a neighbouring
  module by per-table judgment rather than by rule.
- **Goals:**
  - One `WorkflowRunner` loop with a **total** `stop_reason` → `WorkflowRunStatus` mapping,
    asserted in both directions. `worker_lost` stays distinct from `tool_error_unrecoverable`
    so infrastructure death never corrupts the execution-quality metric (ADR-073/074).
  - The LLM never sees vendor endpoints, credentials, raw payloads or basis hashes. Tool
    results reach the conversation only through the inbound guard; agent output leaves only
    through the outbound guard (ADR-070).
  - Writes go to the **sandbox** shop only. The production capability flip is an ADR-068
    unlock item, gated on W7, not a runtime toggle.
  - Postgres is the replay authority; Redis is best-effort delivery. Anything a client sees
    exists as a `workflow_run_events` row first (ADR-074).
  - **Registry:** sole write owner for `workflow_runs`, `workflow_run_events`,
    `tool_executions`, and the `run_agent_workflow` / `resume_agent_workflow` /
    `reap_abandoned_workflow_runs` tasks.
  - **Target NFRs (ADR-083 — out of scope for current W-slices):** queue-based acceptance
    (100 requests/shop < 5 s, per-shop slot pool of 10), one agent per
    `(shop, category, product)` (= one active run per subject-scoped card; same product
    concurrently only across different categories), polled-overview + per-run-SSE progress
    surface. Current slices must not foreclose these; nothing is gated on them.
  - **Boundary:** `services/agent/composition.py` is the sanctioned seam for reaching deep
    collaborators — `workers` may not deep-import `services.agent.tools` (import depth cap 2).
- **Features:**
  - **Shipped:** tool registry + schemas (ADR-069) · LLM service over the OpenAI Responses
    adapter (ADR-071) · agent-safe sanitization with source-role provenance (ADR-070) ·
    versioned prompts + typed Playbook (ADR-072) · `WorkflowRunner`, termination policy,
    idempotent write ledger, basis-hash concurrency (ADR-073) · event union, `PersistingEventSink`,
    SSE with `Last-Event-ID` replay, five-minute reaper (ADR-074) · impact measurement reads
    (ADR-077) · credential refresh lifecycle (ADR-081).
  - **In progress:** approval gate + security prerequisites (ADR-075, W5 — merged and deployed;
    gate #1226 observation 1 at six of seven steps, observation 2 blocked by owner decision) ·
    demo execution experience (ADR-076 as amended by ADR-084, W6 — PRD #1308, filed 2026-08-25).
  - **Planned:** concurrency & progress target NFRs (ADR-083, out-of-scope design targets) · production-write unlock (W7) ·
    observability rollup (W8) · structured output contract (W9) · remaining ten workflows (W10).
- **Related EXECUTION slices:** the agent workflow execution waves W1–W10
- **Out of scope:** the harness that builds the product (§11) · ingest fan-out and
  multi-merchant rollout (P13) · seller-facing copy register, which is governed by
  `dictionary.md` and the shared banned-pattern source.
- **Links:** ADR-068 · ADR-069 · ADR-070 · ADR-071 · ADR-072 · ADR-073 · ADR-074 · ADR-075 ·
  ADR-076 · ADR-077 · ADR-080 · ADR-081 · ADR-082 · ADR-083 · ADR-084 · [PLAN.md](../product/agent-workflow-execution/PLAN.md)

> **§15 is deliberately skipped.** It is reserved for **Observability (DOCP)** by
> `CONTEXT.md` and `docs/product/phases/phase-2.11/PRD.md`, which reference it by number
> although the section is not yet written. Taking §15 here would have created exactly the
> silent numbering conflict this module exists to prevent.

---

## Maintenance

1. **Adding a planning module:** add an index row + full schema A section; link `map.md`
   when code lands; create Tier-3 `MODULE.md` on first code touch (map tier policy).
2. **Feature progression:** move items Shipped ← In progress ← Planned; do not delete
   history without a one-line note if Architects need audit trail.
3. **Phase work:** update EXECUTION slices for multi-module phase goals; update **this
   file** for the module’s own refinement/feature backlog.
4. **Conflicts:** purpose/goals → MODULES; live paths → map; envelopes → system-design;
   allowed sources → data-sources; why → ADR.

**Last seeded:** 2026-07-28 (MMU-13 — sync to post-MMU-1..8 facades + ownership registry). 