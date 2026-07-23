# Juli AI — ubiquitous language

Shared domain language for seller-money workflows across `ios/`, `web/`, and `backend/`.

> Maintained by `grill-with-docs`, `domain-modeling`, and `improve-codebase-architecture`. Do not edit manually unless correcting an error.
> Architectural decisions live in `docs/adr/`.

<!-- Terms are added under ## [Domain area] sections as they are resolved in grilling sessions.
     Format per domain-modeling skill:

     **Term**:
     One or two sentences defining what it IS.
     _Avoid_: rejected alias1, alias2
-->

## Architecture

**Schema-only migration**:
Alembic revisions in `backend/src/juli_backend/database/migrations/` apply **DDL
only** (create/alter/drop tables, indexes, RLS). They do **not** copy, migrate,
or back up existing row data. OAuth tokens in `tiktok_credentials`, commerce ETL
rows, and sync cursors survive an `upgrade head` only if the same Postgres
database already held them — Alembic never transfers data between databases or
projects.
_Avoid_: data migration (when meaning Alembic auto-preserves rows), assuming
`upgrade head` restores OAuth/commerce data after pointing at a new Supabase
project

**Migration safety gate**:
The `pg_dump` backup + row-count invariant + token-decrypt check that wraps every
`alembic upgrade head` — both the VPS production path (`infra/scripts/deploy-release.sh`
→ `safe-alembic-upgrade.sh`) and local dev, via shared helpers in
`safe_alembic_helpers.py` / `safe_alembic_compare.py` ([ADR-027](docs/adr/027-database-migration-safety-pipeline.md)).
Aborts before cutover/continuation on any protected-table row-count regression or
decrypt failure. Includes a weekly VPS-local restore drill that proves the backups it
produces are actually restorable — the drill never transmits a backup off the VPS.
_Avoid_: safe-alembic wrapper (production-only framing — the gate now covers local dev
too), backup script (undersells the row-count/decrypt verification, not just pg_dump)

**Layered model**:
The product's three-layer structure — **visual layer** (Analytics KPI charts + one-line
advisory signals), **ML layer** (T1–T8 advisory techniques), and **execution layer**
(the workflow → action taxonomy a signal links to). Authoritative docs:
`docs/ml/visual_layer.md`, `docs/ml/ml_layer.md`, `docs/product/execution_layer.md`
([ADR-005](docs/adr/011-display-grade-analytics-layer.md) Decision #6).
_Avoid_: 3 Copilots, Copilot surfaces, New Seller / Growth / Revenue Leakage Copilots
(retired UI grouping), "exactly six validated workflows" (closed catalog — retired by ADR-005)

**Workflow taxonomy**:
The domain-organized catalog of workflows (Catalog · Ads · Inventory · Operations ·
Customer Service) and their actions, each action owned by exactly one workflow. Single
source of truth is `docs/product/execution_layer.md`. The shop profile (`NEW_SHOP` vs
`MID_LARGE_SHOP`) selects the **rule set** via the T8 router, not a UI grouping.
_Avoid_: validated workflow catalog (closed "six only" framing — superseded by ADR-005)

**Copy layer**:
The stage that turns structured ML/rules signals into seller-facing Vietnamese copy
for Decisions/cards. Target-state design uses Claude Haiku 3.5 with a deterministic
rules fallback (ADR-012 — corrected citation, was mis-cited as ADR-006). **Phase 2
implementation is rules-only** (deterministic templates, `copy_source: "rules"`) —
Haiku is deferred to Phase 4 per `EXECUTION.md` and `services/scoring/MODULE.md`.
Receives computed signals only, never raw financial PII. Seller-facing wording must
match the **Copy dictionary**; voice/rules come from **Design context**.
_Avoid_: LLM layer, summarizer (when referring to the whole stage), describing Phase 2
copy as LLM-backed (it is not, until Phase 4)

**Design context**:
Design-package authority for Vietnamese *voice and copy rules only* (address form,
naming conventions, money/dates/numbers, error/empty-state patterns, governance).
File: [`docs/product/design/design-context.md`](docs/product/design/design-context.md)
(renamed from `context.md`). **Must not** contain an EN↔VI glossary or reusable
phrases — those live only in the **Copy dictionary** (no overlaps). Focus **required**
load (with `dictionary.md`) for any UI / copy / report / design-surface task
([ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)).
_Avoid_: `context.md` (ambiguous — old design path; rewire refs to design-context.md),
embedding locked product terms here

**Copy dictionary**:
Repo-root [`dictionary.md`](dictionary.md) — sole EN → VI catalog in two keyed
sections: **Keywords** (product terms and words) and **Phrases** (full reusable
sentences). Each entry: stable surface-first key (`nav.home`, `decisions.approve`,
`common.unavailable`) · EN gloss · VI string · optional `_Avoid_`. v1 migrates the
design glossary and harvests chrome/report VI **only where already written** in the
design package; missing strings stay TBD/omitted for human correction. Agents look
up Vietnamese here; they do not invent translations and do not redefine terms in
Design context.
v1 harvests Vietnamese **only** from repo-root `dictionary.md` (migrated glossary) and
existing VI in Screens/Components/Flows; missing chrome stays TBD or omitted for
human correction — do not invent VI from live app strings.
Focus **required** with Design context for UI/copy/report/design work
([ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)).
When a needed string is missing from the dictionary, agents may draft Vietnamese for
UI/frontend, then **immediately add** the new keyed entry to `dictionary.md` so a
human can correct it — never leave orphan invented copy only in code.
_Avoid_: `language.md` (rejected name), `CONTEXT.md` (domain glossary, not VI copy),
duplicating glossary rows inside Design context, unkeyed VI tables, i18n JSON as
authoring SoT, inventing VI from `apps/dashboard` without design authority,
shipping invented VI without a matching dictionary key

**Display-grade analytics**:
The lightweight ML layer that powers the visual layer — a small set of reusable
techniques (T1–T8: ETS forecaster, recycled ads regressor, policy rules,
statistical anomaly, deadline rule, recycled return-fraud detector, weighted
ranker, recycled router classifier) applied across all KPIs. Charts plus one-line
"what changed / risk / action" signals in Analytics; advisory only, never executes
([ADR-005](docs/adr/011-display-grade-analytics-layer.md)).
_Avoid_: per-KPI models (implies ~19 separate trained models)

**Main KPI**:
The representative KPI marked `(main)` for each visual-layer category. Analytics
shows the six Main KPIs—SPS, Net Revenue, ROAS, Inventory Turnover, Fulfillment
Accuracy Rate, and CSAT—as one selected hero plus five selector cards.
_Avoid_: primary KPI, featured metric, headline metric (when referring to this
canonical six-KPI set)

**Decision-grade ML**:
Trained techniques (T2, T6, T8) that must pass backtest promotion gates before
Phase 2.5 artifact load — precision/recall or ROAS MAPE thresholds in
`thresholds.py`, golden fixtures, and `feature_schema_hash` validation. All Home
outputs remain **display-grade** (advisory only); gates vet accuracy, not execute
authority. Former "3 vetted suites" logic is **recycled** into T2/T6/T8 per ADR-005.
_Avoid_: the 3 vetted suites (closed catalog — superseded by ADR-005)

**Manual refresh pipeline**:
Phase 2's execution model for the aggregates → signals → recommendations → copy →
persist chain — triggered on-demand by `POST /v1/action-cards/refresh`, never by
Celery beat, cron, or a scheduler (ADR-021). The pipeline implementation itself
(`services/scoring/pipeline.py::run_daily_scoring_for_shop`) is unchanged; only the
trigger changes. Supersedes the "Daily schedule (UTC)" cron table in the original
`phase-2-mvp.md` — that table is now historical/aspirational for a later phase, not
Phase 2 truth.
_Avoid_: daily batch (implies unattended scheduling), cron pipeline, scheduled scoring

**Phase 3 polyglot target**:
The documented future stack — ClickHouse (OLAP), Amazon S3 (raw landing), AWS SQS
(async ingestion queue) — adopted only when volume/latency/burst justify it. Not
built in MVP/Phase 2, which stays single-store Supabase Postgres
([ADR-012](docs/adr/012-architecture-reconciliation-mvp-vs-target.md) — corrected
citation, was mis-cited as ADR-006).
_Avoid_: target architecture (overloaded term — use Phase 3 polyglot target or `phase-2-mvp.md`)

## Frontend surfaces

**`apps/demo`**:
The public Interactive Demo product (`demo.app-juli.com`), implementing the ADR-023
four-destination IA (Home, Decisions, Analytics, Settings) as one responsive Next.js
codebase covering web + mobile-web breakpoints. Built with mock data in Phase 2.6; wired
to real backend data in Phase 3 ([ADR-024](docs/adr/024-phase-2.6-2.7-frontend-resequencing.md)).
Distinct from `apps/dashboard` (legacy App Review placeholder today; real, authenticated
production app in Phase 3.5).
_Avoid_: the Demo (ambiguous with the retired two-screen Home+Actions IA from the original
`phase-3-landing-demo.md`, superseded by ADR-024)

**`apps/landing`**:
The public marketing site product (`app-juli.com`, replacing the legacy App Review
placeholder once deployed), one responsive Next.js codebase covering web + mobile-web
breakpoints. Own IA defined per its Phase 2.7 PRD — not part of `docs/product/design`'s
scope (that package's root authorities cover the four-destination app only); reuses its
visual tokens and brand voice for consistency.
_Avoid_: Landing Page IA living inside `docs/product/design/Screens/`

**Mock/Sign-in mode toggle**:
`apps/demo`'s UI switch between **Mock mode** (default, no auth required, hardcoded/mock
data — shipped Phase 2.6) and **Sign-in mode** (real TikTok OAuth connect + real backend
data for one pre-connected reference shop — enabled Phase 3). The Sign-in entry point
exists in the UI from Phase 2.6 onward but is a disabled stub until Phase 3 implements it.
_Avoid_: assuming Sign-in mode requires per-visitor onboarding/multi-tenant account
management (that stays Phase 3.5 scope)

**Phase 2.6 optional stretch scope**:
A Phase 2.6 issue that ships inside the phase's timeline but is explicitly exempted from
the exit gate — a truthful placeholder (never fabricated data) is sufficient for launch
if the issue slips. Applies to Settings (#405, [ADR-024](docs/adr/024-phase-2.6-2.7-frontend-resequencing.md))
and Analytics (#404, [ADR-026](docs/adr/026-phase-2.6-analytics-optional-exit-gate.md)).
Home's four-destination shell (ADR-023) is unaffected — the destination stays
discoverable; only its full content depth is optional.
_Avoid_: assuming "stretch" means the issue is deferred to a later phase (it ships in
2.6 if time allows; it just doesn't block sign-off)

**`packages/contracts`**:
Shared TypeScript fixture/type package consumed by `apps/demo` (and later `apps/landing`,
`apps/dashboard`) for Decision/Action Card, execution, and KPI mock-data shapes. Kept
structurally aligned with `docs/api/data-models/` by hand — not code-generated from it —
so Phase 3's swap to a live API client is a data-source change, not a type rewrite.
_Avoid_: `data-models/` (that folder owns canonical ML/entity schemas, not
Demo-ready fixture types); assuming these types are auto-generated

**Reference shop**:
The one pre-connected TikTok shop (already authenticated via Phase 2's pipeline
validation, e.g. Fujiwa/SANDBOX_VN) whose real data powers `apps/demo`'s Sign-in mode in
Phase 3. Phase 3 does not add per-visitor/self-serve TikTok shop connection — that is
Phase 3.5 scope.
_Avoid_: implying Phase 3 opens self-serve TikTok OAuth to arbitrary public visitors

**Operator Backfill Launcher**:
The thin #472 wrapper that loads `juli/api/production` from AWS Secrets Manager into the
child process only (no durable `/etc/juli/*.env` write for this path), optionally defaults
`--shop-id` from the Fujiwa **production_read credential**, force-refreshes access tokens,
and invokes the analytics historical backfill CLI. See [ADR-030](docs/adr/030-operator-cli-in-memory-secrets.md).
_Avoid_: sourcing api.env for backfill; pasting TikTok/DB secrets into the shell; treating
systemd `EnvironmentFile` fetch as the operator path

**production_read credential**:
The `tiktok_credentials` row for Fujiwa Partner Section A reads — merchant
`7658073774813611784` + capability `production_read`. Required by analytics backfill and
Fujiwa poll; distinct from `seller_connect` OAuth rows (open_id-style merchant ids).
_Avoid_: using `seller_connect` as a silent fallback for production analytics reads

## Seller workspace

**Decision**:
The seller-facing primary object — a ranked recommendation envelope wrapping one
validated workflow plus reasoning, required inputs, status, and impact estimate
(ADR-014 — corrected citation, was mis-cited as ADR-007). What sellers review and
approve on the `/decisions` tab (product/UI-facing term).
_Avoid_: AI Action Card, recommendation card (UI renderings of a Decision, not a
separate concept) — but see **Action Card (backend)** below for the one deliberate,
documented exception to this rule.

**Action Card (backend)**:
The Postgres persistence/API-layer name for the row that backs a **Decision** —
`action_cards` table, `ActionCardsRepo`, `POST /v1/action-cards/refresh` (grill
2026-07-13, Phase 2 completion). This is a **layer-boundary naming split, not a
competing synonym**: every `ActionCard` row corresponds 1:1 to exactly one `Decision`
shown to the seller. Product copy, UI components, and `web/` code always say
"Decision." Backend model/table/route/repo names always say "Action Card." Never use
"Action Card" in seller-facing copy; never use "Decision" as a SQLAlchemy model or
table name.
_Avoid_: using this term outside `backend/` code and its docs/issues; conflating with
the unrelated `Recommendation` model (`models.py`), which powers a different feature
(AI product-push / host-product matching, `juli_backend.ai.recommendations`) — not
the rules-pipeline output this term describes.

## Inventory

**Phase 2 FBS-only fulfillment**:
Phase 2 executors, Action Cards, and sandbox write chains assume **Fulfillment by
Seller (FBS)** only — seller warehouse `warehouse_id`, Product API Inventory Search,
and `Update Inventory`. FBT paths (inbound shipment, FBT MCF order processing, FBT
restock via webhook) are **deferred to Phase 5** (Full Launch). Do not remove working
webhook catalog entries or ingestion — ACK, verify, log, and ETL continue. Missing FBT
**REST** endpoints stay `TBD` in `contract-collection.md`; FBT **webhook** payloads are
sanitized in `webhook-contract-collection.md` (promote rows to verified when confirmed).
Webhook **#24** `FBT_INVENTORY_UPDATE` is confirmed (grill 2026-07-13); intake only in
Phase 2 — no FBT executor dispatch until Phase 5.

**Clear Excess Inventory (workflow 4)**:
FBS executor workflow — Product API price markdown, Promotion API activity lifecycle,
and `Update Inventory` (step 6a). `execution_layer.md` also documents step 6b (FBT
inventory webhook monitor) as the FBT branch of the same workflow; **do not remove or
split** catalog mappings. Webhook #24 may list `clear_excess_4` alongside FBT keys;
the **executor** remains FBS-only in Phase 2. FBT branch automation deferred Phase 5.
_Avoid_: removing `clear_excess_4` from webhook #24, treating 6b as a separate workflow,
implementing FBT clearance writes in Phase 2

**Request Cancellation / Request Return / Request Refund (workflows 8a / 8b / 8c)**:
Post-sales workflows that help the seller **process buyer requests** — surface
eligibility and reject reasons from the Return/Refund API, then execute an explicit
**approve** or **reject** decision (`decision` required in payload; no silent default).
Retired display name: "Prevent *". 8b Phase 2 executor: FBS chain + optional step **7a**
`Update Inventory`; step **7b** (FBT webhook) stays in `execution_layer.md`, deferred Phase 5.
_Avoid_: Prevent Cancellation, Prevent Return, Prevent Refund, defaulting approve/reject
without seller or rules layer setting `decision`

**Supplier-sourced replenishment**:
Restocking inventory by creating and tracking a purchase order through an external
supplier integration (`Replenish via Supplier` workflow). Terminal step always
syncs available quantity to TikTok via Product API (`update inventory` operation).
_Avoid_: Supplier Sourcing (informal — use workflow name or this term), dropship
(when meaning ERP/self-managed stock)

**ERP-sourced replenishment**:
Restocking inventory by recording a purchase request and inbound receipt in the
seller's ERP (`Replenish via ERP` workflow). Juli does not operate a warehouse
system; ERP is the seller's stock ledger. Terminal step syncs to TikTok via Product API
(`update inventory` operation).
_Avoid_: ERP-sourced replenishment (when meaning supplier path), Warehouse System, Inventory System (phantom executors)

**Customer Service execution**:
Approval-gated workflow actions for Resolve Recurring Customer Complaints (Phase 3
deferred) and live Post-sales workflows **Request Return (8b)**, **Request Cancellation
(8a)**, **Request Refund (8c)**. Phase 2 CSAT is advisory-only with **no live workflow key**.
_Avoid_: Prevent Cancellation/Return/Refund (retired names), Prevent Product Returns,
Workflow Engine, Monitoring Engine, Messaging API (use Customer Service API in execution tables)

## Scoring

**Computed KPI**:
A visual-layer KPI whose value is derived from joins or rollups across two or more
synced Postgres sources (orders, order_items, products, inventory_items, returns, etc.)
— not a single API field or one-table aggregate. Phase 2 computes these in
`services/aggregates/` (extended `FeatureAggregateSnapshot` + builder); `signals.py`
applies thresholds and `visual_layer.md` one-liners only. Techniques are deterministic
rules (`rules_proxy`, T3/T4/T5-style thresholds per `ml_layer.md`); trained T1/T2 remain
Phase 4. P2-B3 scope (grill 2026-07-12): all 13 KPIs still emitting `unavailable` in
#303 — Inventory (3), Operations (3), Revenue (2), Ads (3), CSAT + After-Sales Handling
Time (2). Ads KPIs remain `unavailable` until Promotion API ETL lands; CSAT uses a
deterministic proxy (see **CSAT proxy** below).
_Avoid_: derived metric (generic), calculated field (DB jargon), multi-source KPI (ambiguous — use this term)

**CSAT proxy**:
Phase 2 stand-in for CSAT when no buyer review/chat text exists: score =
`clamp(100 × (1 − return_rate_30d), 0, 100)` from synced returns/orders; technique
`rules_proxy`; **no workflow_keys** (Resolve Recurring Customer Complaints deferred Phase 3).
Real CSAT replaces this when a legal text source exists (ADR-011).
_Avoid_: CSAT score (when meaning the Phase 3 model), customer satisfaction (generic)

## Execution

**Action executor**:
The `System` column in an execution action table — must name a real integration
surface: TikTok Partner API family (Product, Order, Fulfillment, Promotion, etc.),
Third-Party connector (Supplier API, ERP API), Juli AI LLM, or User-provided input.
Phantom labels (Validation Engine, Warehouse System, Workflow Engine,
Monitoring Engine, Logistics API as a separate executor) are forbidden.
Fulfillment ship/label/tracking actions use **Fulfillment API**; order reads use **Order API**.
**Promotion API** (`open-api.tiktokglobalshop.com`) for seller promotions; **Marketing API**
(`business-api.tiktok.com`) for Shop Ads campaign/budget/bid writes — not interchangeable.
_Avoid_: "Ads API" on Shop Partner host (no campaign writes); Internal engine names with no implemented client or ADR

**Ads KPI workflow routing**:
Analytics Ads KPIs (ROAS, CAC, CTR) link to **Promotion** workflows from
`execution_layer.md` — Create Activity (7a), Update Activity (7c), Delete Activity (7b)
— not Shop Ads Marketing API budget/bid writes (out of Phase 2 Partner scope).
_Avoid_: Increase Ad Budget, Reduce Ad Spend, Budget Optimization (P1.8 catalog labels — retired)

**Product bundle routing**:
Multi-SKU / bundle listing optimization is a capability inside **Optimize Product (2)** —
not a standalone workflow in `execution_layer.md`.
_Avoid_: Create Product Bundle (phantom workflow — use Optimize Product (2))

**Shop Status KPI routing**:
SPS / AHR / Violation Points render in Analytics from mock/fixture data in Phase 2 because
Partner API shop-health fields are not available to retrieve. They emit advisory
display only — **no execution_layer workflow mapping** until a live source exists.
_Avoid_: mapping Shop Status KPIs to Process Order / Prevent Cancellation / Resolve
Recurring Customer Complaints while data remains mock

## GMV impact measurement

**Fujiwa T1 GMV experiment**:
A disposable, offline calibration experiment that fits a single **T1 ETS**
(`statsmodels` Holt-Winters) on Fujiwa daily shop GMV (A-36 from Phase 2.9
backfill) to produce observed-vs-counterfactual incremental GMV with wide
intervals and an explicit rough `data_confidence` badge. **Design A:** walk-forward
/ holdout on A-36 only — no intervention date, no parallel launch-date research.
Default split: earliest ~70% fit / latest ~30% holdout (CLI-overridable). Quality
bar is **soft**: report holdout MAPE + beat-vs-naive/mean baseline — not a hard
promotion threshold; worse-than-naive → reconsider. Pathfinder for Phase 4 T1 —
not a promoted decision-grade artifact; may be abandoned if forecast quality is
poor. Lives under `ai/forecasting/shop_gmv` beside inventory depletion. Writes
**local offline artifacts only** (CLI `--output-dir`: parquet/CSV + `metrics.json`)
— not product Supabase tables, not `models/` promotion layout. See
[ADR-032](docs/adr/032-fujiwa-t1-gmv-experiment-scope.md).
_Avoid_: Prophet counterfactual, dual Stage-2+Stage-3 as first ship, inventing a
Product/LIVE or Juli launch date for this experiment, hard MAPE ≤ X% gate for
this experiment, treating outputs as decision-grade, persisting experiment rows
into Analytics product tables

**Mediated Juli GMV impact**:
The intended future way to estimate Juli’s effect on client GMV: compose two
hops — (1) **Juli → Product/LIVE mediators** (e.g. CTR would have grown ~0.2 pp/month
without Juli; with Juli it grows ~0.4 pp/month → Juli lift on CTR) and
(2) **mediators → GMV** via Product/LIVE driver regression (elasticity of GMV to
CTR/CVR/impressions/live quality). Overall Juli ΔGMV ≈ Juli lift on mediators ×
mediator→GMV elasticities. Requires shipped end-to-end workflows plus enough
history for both hops; still calibration-grade until promotion gates exist.
_Avoid_: direct Juli→GMV as the only story, treating either hop alone as full
Juli ROI, Value calculator Inventory/CS assumption tabs as measured Juli impact

**Juli → mediator lift**:
The first hop of mediated Juli GMV impact — how much Product/LIVE metrics
(CTR, CVR, impressions, live-session quality) change because Juli is deployed,
versus each metric’s no-Juli baseline trend. Treatment is Juli usage (workflows /
approved Action Cards), not OAuth-connect alone.
_Avoid_: attributing all CTR movement to Juli, conflating with mediator→GMV
elasticity

**Product/LIVE driver regression**:
The second hop — associates Δ Product/LIVE funnel metrics with ΔGMV/ΔOrders
(elasticity). Necessary for mediated Juli GMV impact, but **not** Juli impact by
itself. Deferred until the Fujiwa T1 GMV experiment shows usable forecast quality;
then revisited as its own model. CTR→GMV pairs must follow **matched CTR–GMV grain**.
_Avoid_: calling this Juli ROI alone, skipping the Juli→mediator hop, regressing
product CTR directly onto shop GMV without a grain bridge

**Matched CTR–GMV grain**:
The rule that a CTR (or click-through) mediator is paired only with GMV at the
same analytics grain — never cross-wired as if “CTR” were shop-universal. Verified
Partner shapes (Fujiwa): **A-34** product `ctr` ↔ product `gmv`; **A-28** session
`click_through_rate` ↔ session `gmv`; **A-29** daily LIVE `click_through_rate` ↔
daily LIVE `gmv` (aligns with A-36 LIVE breakdown). **A-36 shop performance has
shop GMV but no shop-level CTR** (traffic is visitors / page views / conversation
rate). Shop GMV remains the composed headline / T1 sanity ceiling, not the direct
regression target for product or session CTR.
_Avoid_: one undifferentiated “CTR”, using A-36 as a CTR source, product CTR → shop
GMV as the primary elasticity

**Primary mediator→GMV elasticities (target-state hop 2)**:
When Product/LIVE driver regression is built (after the Fujiwa T1 experiment),
run **two parallel matched models** — not one blended CTR: (1) A-34 product `ctr`
→ product `gmv` (listing optimization path); (2) A-29 daily LIVE
`click_through_rate` → LIVE `gmv` (live path; daily grain preferred over A-28
session for the first LIVE elasticity). Compose both into shop-level Juli ΔGMV;
use A-36 overall GMV as sanity check only. A-28 remains available for session
diagnostics, not the primary monthly elasticity.
_Avoid_: single shop-level CTR regression, A-28 as the first LIVE elasticity target,
summing Inventory/CS assumptions into the composed total

**Forecasting package (multi-model)**:
`backend/src/juli_backend/ai/forecasting/` hosts **more than one forecast model**,
each with a distinct purpose, algorithm, inputs, outputs, and public API — never
one overloaded `get_forecast` for unrelated jobs. **Inventory depletion** (SKU
velocity from orders → stockout horizon; linear / moving-average) stays as-is.
**T1 shop GMV** (Fujiwa experiment) lands in the same package as a separate
`shop_gmv` module (ETS counterfactual + short-series fallback), separate result
types and CLI; shared helpers only for generic series math. See
[ADR-032](docs/adr/032-fujiwa-t1-gmv-experiment-scope.md).
_Avoid_: one generic ForecastResult for inventory + GMV, teaching ETL/backfill to
train, conflating intelligence-track depletion with display-grade T1

## Agent runtime (Executor domains)

**Domain executor skill**:
A Meta-assigned primary skill under `.cursor/skills/domain/<name>/` that steers
implementation for one Executor run. Each domain uses progressive disclosure:
short `SKILL.md` (Juli recipes + load map) plus optional `REFERENCE.md` (deeper
repo recipes and Context7-backed framework guidance). Shared test idioms stay in
`domain/testing-patterns/`. Harness `executorDomain` must match the skill name.
_Avoid_: stuffing all guidance into one SKILL.md, treating marketplace plugin skills
as domain executors

**Integrations domain**:
Platform-agnostic Executor domain for code that talks to external commerce
platforms: vendor HTTP clients (auth/signing/rate limits/retries), inbound
webhooks (verify + ETL handoff), polling/scheduled sync (cursors, shop isolation),
and analytics fetch/partition backfill. Not vendor-branded — TikTok/Shopee/etc.
docs are issue-specific loads under `docs/integrations/`. Does **not** own Juli
product API routes, scoring/copy, or JWT session auth (those are **backend**);
does **not** own schema/migrations/ETL consumer durability (**data-platform**).
_Avoid_: TikTok domain, connector skill (vague), overlapping ownership with backend
for `/v1/*` product routes

**Context7 CLI**:
Focus/Meta-selected docs fetch via `npx ctx7@latest` for **technical and domain
implementation** (library/framework/SDK APIs, domain `REFERENCE.md` framework
recipes). Not an MCP; not always-on (`alwaysApply: false` on
`.cursor/rules/context7-cli.mdc`). Catalog: skill-catalog `catalog.cliDocs`.
_Avoid_: Context7 MCP, context7-mcp plugin skill (as required load), always-on
Context7 for every chat

## Security operations

**Weekly Secrets Security Check**:
The scheduled secrets-first audit (ADR-033): inventory and leak paths across repo,
VPS, and website; report + prepare rotation or delivery fixes; no live rotate until
a human has successfully run that rotate path once. Memory family
`Juli-AI-v2---flagged-secret-findings*.json`; weekly GitHub rollup issue for new
findings only.
_Avoid_: weekly full AppSec pentest; auto-rotating prod secrets in phase 1;
posting secret findings to Slack by default; dumping live secret values into
issues or memory

