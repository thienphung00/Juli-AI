# Purpose

Use when **evaluating or proposing architecture** for Juli-AI: new features, large
refactors, module boundaries, cross-surface contracts (`src/`, `web/`, `ios/`), data
pipeline changes, or phase transitions (mock → ML → live API).

Optimize **MVP-first**: speed to validated learning, lowest justified cost, and
decisions that stay correct under phase gates — not enterprise-scale speculation.

# MVP-first lens

| Priority | Question | Default bias |
|----------|----------|--------------|
| **Speed** | What is the smallest slice that validates the hypothesis? | Mock/fixture before live API; tracer-bullet issue before platform build |
| **Cost** | What can we defer without blocking the current phase gate? | No Celery/Kafka/microservices until EXECUTION.md says so; Ollama + rules fallback before paid LLM at scale |
| **Accuracy** | Does this match deployed reality and phase authority? | `EXECUTION.md` slice + `data-sources.md` row + `map.md` module before coding |

If a design fails phase-fit or adds a seventh workflow, stop and escalate via
`grill-with-docs` — do not paper over with implementation detail.

# Authority chain (read in order)

1. [`EXECUTION.md`](../../../../EXECUTION.md) — phases, slices, gates, in/out scope (**law**)
2. [`docs/system-design.md`](../../../../docs/system-design.md) — subsystem behavior per phase
3. [`docs/architecture/map.md`](../../../../docs/architecture/map.md) — as-built modules
4. [`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md) — allowed/forbidden data per phase
5. [`docs/decisions/`](../../../../docs/decisions/) — settled ADRs (do not re-litigate)
6. [`CONTEXT.md`](../../../../CONTEXT.md) — ubiquitous language (if present)

Layer quick-ref: [`.cursor/skills/standalone/focus/routing-rules.md`](../focus/routing-rules.md) § Layer map

# Current stack (as-built)

| Surface | Path | Role |
|---------|------|------|
| Backend | `src/` | Python 3, FastAPI **modular monolith** (`apps/` entrypoints + `modules/` domain) |
| Web | `web/` | Next.js 14 App Router, mock-first workflows |
| Mobile | `ios/` | SwiftUI, Supabase OTP + Keychain JWT |
| Data | Supabase Postgres | SQLAlchemy async, Alembic (`src/shared/utils/data`) |
| Ingest | In-process handoff | `HandoffFn` → `EtlConsumer` (no Celery in Phase 1–2) |
| External | TikTok Shop Partner API | **Only** approved live source in Phase 2 |
| Copy layer | Ollama (Phase 2) | Summarizes structured signals; rules fallback; never decides |

**Layout invariant:** No folder reshaping (`src/apps` + `src/modules`) until Phase 2.5.

# North star constraints (non-negotiable)

- **Seller money** — Decision Copilot over workflow taxonomy
  ([ADR-013](../../../../docs/decisions/013-operations-pipeline-spine.md)).
- **Decision Copilot** — analyze → recommend → user approves → execute
  ([ADR-014](../../../../docs/decisions/014-decision-copilot-app-structure-and-journey.md)).
- **Forbidden:** Seller Center scraping, unofficial streams, buyer PII storage,
  generic analytics CRM, inventory/finance **management** software, creator↔shop
  matching in the next 13 weeks.
- **Financial PII** (revenue, gmv, roas, ad_spend, …): tier/delta labels in docs
  and LLM prompts; never raw in logs (INFO+), commits, or handoffs (`core-safety.mdc`).

# Architecture review process

## 1. Scope & phase-fit (mandatory first)

- Identify the driving **EXECUTION.md** slice(s) and exit gate.
- State current phase: P1 mock | P1.5 ML | P1.6–1.8 workflow fixtures | P2 live.
- Confirm every proposed data source has a **data-sources.md** row (or draft one).
- Confirm the work maps to an existing validated workflow — not a seventh workflow.

**Red flag:** Live TikTok polling, Redis queues, or new microservices in a P1 UI slice.

## 2. Current state (minimum context)

Load only what the decision touches:

- Affected `MODULE.md` files from `map.md`
- Relevant `system-design.md` subsystem section (phase column)
- Existing ADRs for the domain (auth, ML, operations spine, entities)
- Prior art in codebase (`Grep` / `Read` — do not load full trees)

Document **technical debt** only if it blocks the slice or creates phase regression.

## 3. Design proposal (MVP-shaped)

Produce:

- **Component map** — which module(s) own the change (`map.md` tier 1/2)
- **Data flow** — source → ingest → persist → API → UI (name envelope shapes)
- **API contract** — route, auth (`get_current_user` + shop scope), request/response sketch
- **Cross-surface impact** — does `web/`, `ios/`, or both need the same contract?
- **Phase 2 swap plan** — what stays mock in P1.x and what interface stays stable for live data

Prefer **envelope-stable stages** (operations pipeline) over new ad-hoc shapes per screen.

## 4. Trade-off analysis (keep short)

For each non-obvious decision:

| | |
|---|---|
| **Options** | 2–3 realistic choices for *this phase* |
| **Pros / cons** | One line each |
| **Decision** | Pick + tie to slice gate or ADR |
| **Defer** | What we explicitly are *not* building now |

Propose an ADR only when all three gates from `domain-modeling` pass (hard to reverse,
surprising without context, real trade-off). Otherwise note in issue/handoff only.

# Module placement rules

| Change type | Place under | Notes |
|-------------|-------------|-------|
| HTTP route / app factory | `src/apps/api_gateway/api/` | Thin; delegate to modules |
| TikTok client / signing | `src/modules/catalog/domain/integrations/tiktok/` | No direct calls from `web/` or `ios/` |
| Webhook ingest | `src/apps/api_gateway/services/webhook/` | HMAC → `handoff_fn` |
| Polling workers | `src/apps/cron_jobs/services/polling/` | Shop-scoped, rate-limited |
| ETL / dedup / persist | `src/modules/ordering/use_cases/etl/` | `event_id` idempotency |
| Persistence | `src/shared/utils/data/` | Models + repos + migrations |
| Auth | `src/modules/identity/` | JWT from Supabase; TikTok OAuth lifecycle |
| Recommendations / decisions | `src/modules/catalog/domain/recommendations/` | Structured outputs, not LLM decisions |
| ML training / inference | `src/modules/ml/<suite>/` | Phase 1.5 artifacts; see `mle-agent.md` |
| Post-stream heuristics | `src/modules/catalog/domain/intelligence/` | Legacy; do not expand without ADR |
| Workflow UI (mock) | `web/src/lib/workflows/`, `web/src/components/workflows/` | Fixtures in `web/src/lib/mock-data/` |
| New module | Add row to `map.md` + `MODULE.md` before merge | Tier 1/2 per map policy |

# Operations-system spine (P1.8+)

When touching orchestration, preserve stage envelopes — Phase 2 swaps loaders only:

```
unified_operational_data_model → health_check_results → shop_profile
  → workflow_recommendations → reasoning_summary → approved_workflows
  → workflow_results → workflow_outcome_metrics
```

Every datum must trace to ≥1 validated workflow ([ADR-013](../../../../docs/decisions/013-operations-pipeline-spine.md)).

# Preferred patterns (Juli)

- **Modular monolith** — composition in `apps/`, logic in `modules/`, shared DB layer.
- **Repository + service boundaries** — routes orchestrate; domain stays framework-agnostic
  (see `python-patterns.md`, `patterns.mdc`).
- **Shop scoping** — every query and API path scoped to active shop; AuthZ in service layer.
- **Mock-first envelopes** — JSON fixtures match canonical entities; stable for P2 wiring.
- **Idempotent ingest** — `(shop_id, …)` keys + `event_id` dedup; DLQ on failure.
- **Copy layer** — ML/rules → structured JSON → LLM localize; LLM never chooses actions.
- **Tracer bullets** — one issue per vertical slice; MODULE.md + map row in same PR.

# Avoid (Juli red flags)

| Anti-pattern | Why it hurts MVP |
|--------------|------------------|
| Seventh workflow or new copilot surface | Violates ADR-013 catalog; scope creep |
| Live API in Phase 1 UI work | Wastes rate limits; blocks UX gate |
| Celery / Kafka / event bus now | EXECUTION.md defers to Phase 3+ |
| `src/` folder reshuffle | Forbidden until Phase 2.5 |
| God module / cross-tier imports | Breaks map tiers and test isolation |
| LLM as decision engine | Violates copy-layer boundary |
| Raw financial metrics in prompts/logs | PII policy + audit risk |
| New data source without `data-sources.md` | Phase authority bypass |
| Scraping / unofficial TikTok streams | Forbidden permanently |
| Premature microservices or read replicas | Cost without P2 gate evidence |
| Analysis paralysis | No ADR/issue filed; no slice advanced |

# Evaluation checklist

Before endorsing a design:

**Phase & scope**
- [ ] EXECUTION.md slice identified; in/out scope explicit
- [ ] Phase-appropriate data (mock / parquet / live) confirmed
- [ ] Maps to one of six validated workflows (or docs rescope filed first)

**Structure**
- [ ] Module placement matches `map.md`; new modules have MODULE.md plan
- [ ] `apps/` stays thin; business logic not in route handlers
- [ ] Cross-surface contract defined if `web/` and `ios/` both affected

**Data & security**
- [ ] `data-sources.md` row exists or drafted
- [ ] Shop scoping + JWT auth on all seller data paths
- [ ] No forbidden sources; TikTok secrets stay server-side only
- [ ] Financial fields handled per `core-safety.mdc`

**Operations & ML**
- [ ] Ingest idempotency and failure path documented
- [ ] ML work references `feature-store-schema.md` + promotion gates (if applicable)
- [ ] Copy layer uses structured signals only

**Delivery**
- [ ] Smallest shippable slice named (issue-sized)
- [ ] ADR proposed only if decision is hard to reverse
- [ ] `map.md` / `system-design.md` / EXECUTION updates listed if architecture changes

# Agent instructions

- **Read before recommending** — never invent modules or phases not in canonical docs.
- **Default to the current phase** — propose P2 interfaces as stubs, not full implementations.
- **Quantify deferrals** — name what ships now vs what waits for which gate.
- **One diagram max** — mermaid or ASCII only when it clarifies cross-module flow.
- **No code in the review** unless the user asked for interface sketches; prefer MODULE.md + ADR bullets.
- **Hand off implementation** — architecture output feeds `grill-with-docs` → `to-prd` → `to-issues`; do not skip issue acceptance criteria.
- **Delegate glossary/ADR prose** — use `domain-modeling` for CONTEXT.md and ADR templates.
- **Delegate code patterns** — load `python-patterns`, `postgres-patterns`, `swift-patterns`, `mle-agent`, `data-scientist` when the decision is layer-specific.

# Output format

```markdown
## Architecture evaluation: [topic]

### Verdict
[Approve | Approve with changes | Defer | Reject] — one sentence why

### Phase-fit
- Slice: [P1.x / P2-y from EXECUTION.md]
- Data mode: [mock | backtest | live]
- Workflows touched: [from validated catalog]

### Current state
- Modules: [paths + MODULE.md refs]
- Debt / blockers: [only if relevant]

### Proposed design
- Components & ownership: [...]
- Data flow: [...]
- API / contract notes: [...]
- Phase 2 stability: [what interface stays fixed]

### Trade-offs
| Decision | Choice | Deferred |
|----------|--------|----------|

### Required doc updates
- [ ] EXECUTION.md / system-design.md / map.md / data-sources.md / ADR-NNN

### Next step
[grill-with-docs rescope | to-prd | tracer-bullet issue #… | no change]
```
