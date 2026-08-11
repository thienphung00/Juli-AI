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

**Doc SoT pointers**:
Tier-1 module catalog → [`MODULES.md`](docs/architecture/MODULES.md) ([ADR-036](docs/adr/036-modules-tier1-planning-sot.md)). Product phase law → [`EXECUTION.md`](EXECUTION.md). As-built paths → [`map.md`](docs/architecture/map.md). Planning tier ladder → [ADR-036](docs/adr/036-modules-tier1-planning-sot.md).
_Avoid_: conflating MODULES with map.md, EXECUTION slices as the only module backlog

**Product phases**:
The product/codebase progression timeline owned by [`EXECUTION.md`](EXECUTION.md) (Phases 1–5 completed product work, then 2.5, 2.6, 2.9, **2.10**, **2.11**, 3, …). Describes what the **seller product** ships (plus eng-facing phases like DOCP when listed in EXECUTION). Distinct from **Agentic versions** and from historical **Agent Runtime migration** Phases 1–5 (harness bootstrap).
_Avoid_: Agent Runtime Phase N (when meaning product delivery), Agentic Version N (when meaning seller-product delivery)

**Phase 2.10**:
Product phase after 2.9 and before full Phase 3 — webhook/API ingest → raw Postgres → transform → compute → precomputed Postgres + Redis read-through cache → Analytics and Decisions on public Demo (no login / no OAuth). Slice checklists: [ADR-037](docs/adr/037-phase-2.10-demo-real-data-no-auth.md), [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md).
_Avoid_: calling this “Phase 3”, visitor TikTok OAuth, Redis as system of record

**Phase 2.11**:
Product phase after 2.10 and before Phase 3 — ships the thin **DOCP** MVP (OpenObserve + PostHog) so runtime and UX reliability signals exist before Landing deploy and Demo Sign-in. Planned on a `2.11` planning branch; does not replace Phase 3 Landing/Sign-in. Strips PostHog from Phase 3’s exit once 2.11 owns wiring. **In scope:** structured logs + RED metrics + Slack alerts, Demo PostHog (`reliability.*`) with sampled replay, deploy SHA markers; vendor UIs only; hot retention policy (OO logs 14d / metrics 90d / PostHog 30d) documented — S3 archive pipeline not required to exit. **Deferred to Phase 2.11-B:** full traces/DB APM, Landing `product.*`, custom unified dashboard, automated change→deploy→user correlation, **hot→S3 cold archive export** (policy locked in 2.11).
_Avoid_: calling DOCP Phase 3.1, folding DOCP into Phase 3 exit, requiring full change→deploy→user correlation in 2.11, requiring S3 archive to exit 2.11

**Phase 2.11-B**:
Follow-on DOCP deepening after the 2.11 thin MVP — fuller traces/APM, broader PostHog surfaces, cross-system correlation (code change → deploy → runtime → user impact), and **AWS S3 cold archive** of OO/PostHog telemetry after hot retention (not discard). Not a Phase 3 prerequisite.
_Avoid_: treating 2.11-B as blocking Landing/Sign-in, merging 2.11 and 2.11-B into one exit gate

**DOCP (Developer Observability Control Plane)**:
Internal eng/ops observability module — OpenObserve for runtime (logs, metrics, traces, deploy/health) and PostHog for app UX reliability (sessions, flows, funnels, replay). Not seller-facing; must not duplicate Demo **Analytics** KPIs or product BI. Phase 3 engagement PostHog reuses one PostHog project with `reliability.*` vs `product.*` namespaces. First ship phase: **Phase 2.11**. **MODULES:** new top-level **§15 Observability (DOCP)**; ADR-035 / #498 ECS lives under **§12 CI/CD & Infra** as child **12.1 Public release platform** (not under DOCP). **Hosting (2.11):** OpenObserve Cloud + PostHog Cloud as the live query/alert plane — not CloudWatch as primary for VPS apps; not self-hosted on the product VPS. **Hot retention then cold archive:** OO logs 14d, OO metrics 90d, PostHog events/replay 30d; S3 archive in **2.11-B**. **Alerts (2.11):** Slack (existing uptime webhook + OpenObserve rules for API 5xx / health). **Correlation (2.11):** `request_id` on API logs/responses + best-effort PostHog attach on API failures; `release_sha` deploy markers on OO and PostHog. Secrets Manager holds OO/PostHog keys; CloudWatch for AWS-native compute stays under §12.1.
_Avoid_: seller observability UI, cloning Analytics into PostHog, Sentry-as-DOCP, custom unified dashboard as v1 requirement, self-hosting OpenObserve on the Juli product VPS in 2.11, CloudWatch as primary app log/metrics/replay store, putting DOCP backlog under §12 or ECS under §15, PagerDuty in 2.11

**Demo dual-layer read model**:
Durable shop-scoped precomputed KPI/intelligence envelopes (Postgres SoT) plus mandatory Redis read-through cache — shared by Analytics and Decisions after transform→compute. See [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md).
_Avoid_: mock fixtures as Decision input after 2.10-A, separate ingest pipelines per layer, optional Redis for 2.10+ product reads

**VPS Redis (ephemeral)**:
Co-located Redis on the product VPS (loopback only) used as cache, TikTok rate-limit buckets, material coalesce gate, and Celery broker/result DBs — never product SoT; no RDB/AOF for Phase 2.10. Logical DBs: app `/0`, Celery broker `/1`, results `/2`. See [ADR-041](docs/adr/041-vps-redis-ephemeral-cache-and-celery.md).
_Avoid_: Redis as durable store, public bind of 6379, treating App Review “skip Redis” as the 2.10 prod stance

**Product Intelligence Layer**:
The computed outputs that feed **Analytics Layer** (“what is happening?”) and **Decision Layer** (“what should happen next?”). Not a third UI destination — the shared intelligence stage after transform/compute.
_Avoid_: conflating with Copy layer, treating Analytics and Decisions as separate ingest pipelines

**Decision emission budget**:
The product policy that caps how many new/changed Decisions a shop is shown per day/week (and per-workflow cooldowns after approve/dismiss/execute), so optimization has time to move KPIs and clients are neither under- nor over-prompted. Distinct from KPI compute frequency. See [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md).
_Avoid_: unlimited realtime Decision spam on every webhook, treating config defaults as immutable product law

**Agentic versions**:
The HITL harness maturity timeline for the Agent Runtime module. Uses **Version** numbering (not Phase — Phase is reserved for **Product phases** in EXECUTION.md). **SoT:** `agent-runtime/docs/agent-runtime-migration.md` (timeline + legacy “Agent Runtime Phase 6” → **Agentic Version 1** rename) and MODULES §11. Exit gates and delivery slices live in the migration doc — not here.
_Avoid_: Agentic Phase N, Phase 6 (legacy label), Agentic rows in EXECUTION.md, renumbering bootstrap 1–5 as Agentic Version 1–5

**Schema-only migration**:
Alembic revisions in `backend/src/juli_backend/database/migrations/` apply **DDL only** (create/alter/drop tables, indexes, RLS). They do **not** copy, migrate, or back up existing row data. OAuth tokens and commerce ETL rows survive `upgrade head` only if the same Postgres database already held them.
_Avoid_: data migration (when meaning Alembic auto-preserves rows), assuming `upgrade head` restores OAuth after pointing at a new Supabase project

**Migration safety gate**:
The `pg_dump` backup + row-count invariant + token-decrypt check wrapping every `alembic upgrade head` — VPS production and local dev via shared helpers ([ADR-027](docs/adr/027-database-migration-safety-pipeline.md)). Aborts on protected-table row-count regression or decrypt failure.
_Avoid_: safe-alembic wrapper (production-only framing), backup script (undersells row-count/decrypt verification)

**Layered model**:
The product's three-layer structure — **visual layer** (Analytics KPI charts + one-line advisory signals), **ML layer** (T1–T8 advisory techniques), and **execution layer** (workflow → action taxonomy a signal links to). Authoritative docs: `docs/ml/visual_layer.md`, `docs/ml/ml_layer.md`, `docs/product/execution_layer.md` ([ADR-011](docs/adr/011-display-grade-analytics-layer.md) Decision #6).
_Avoid_: 3 Copilots, Copilot surfaces, "exactly six validated workflows" (retired by ADR-011)

**Workflow taxonomy**:
The domain-organized catalog of workflows (Catalog · Ads · Inventory · Operations · Customer Service) and their actions, each action owned by exactly one workflow. SoT: `docs/product/execution_layer.md`. Shop profile selects the **rule set** via the T8 router, not a UI grouping.
_Avoid_: validated workflow catalog (closed "six only" framing — superseded by ADR-011)

**Copy layer**:
The stage that turns structured ML/rules signals into seller-facing Vietnamese copy for Decisions/cards. Phase 2 is rules-only (`copy_source: "rules"`); Haiku deferred to Phase 4. Receives computed signals only, never raw financial PII. Wording must match the **Copy dictionary**; voice/rules from **Design context**.
_Avoid_: LLM layer, describing Phase 2 copy as LLM-backed

**Design context**:
Design-package authority for Vietnamese *voice and copy rules only* — [`docs/product/design/design-context.md`](docs/product/design/design-context.md). Must not contain an EN↔VI glossary; those live only in the **Copy dictionary**. Focus **required** load for UI/copy/report/design work ([ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)).
_Avoid_: `context.md` (old design path), embedding locked product terms here

**Copy dictionary**:
Repo-root [`dictionary.md`](dictionary.md) — sole EN → VI catalog (Keywords + Phrases). Stable surface-first keys; agents look up Vietnamese here and do not invent translations. v1 harvests from migrated glossary and existing design-package VI only; missing chrome stays TBD. Focus **required** with Design context ([ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)).
_Avoid_: `CONTEXT.md` (domain glossary), duplicating glossary rows in Design context, shipping invented VI without a dictionary key

**Display-grade analytics**:
The lightweight ML layer powering the visual layer — reusable techniques (T1–T8) applied across KPIs. Charts plus one-line advisory signals in Analytics; advisory only, never executes ([ADR-011](docs/adr/011-display-grade-analytics-layer.md)).
_Avoid_: per-KPI models (implies ~19 separate trained models)

**Main KPI**:
The representative KPI marked `(main)` for each visual-layer category. `apps/demo` Analytics ships the **Demo Main KPI set (Option B′)** — **exactly five**: GMV (TikTok), AOV, CTOR (click→đơn), LIVE hours, Cancellation rate — as one hero plus four selector cards ([ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md)). SPS, ROAS, CSAT, inventory turnover, fulfillment accuracy, and Bestselling are removed from the Demo selector until envelope-backed; the fuller visual-layer catalog may still live in backend/docs. Adding a sixth requires an explicit ADR/catalog change.
_Avoid_: primary KPI, featured metric, headline metric; the superseded six-KPI list (SPS / Net Revenue / ROAS / Inventory Turnover / Fulfillment Accuracy / CSAT); showing removed KPIs as empty placeholders

**KPI measurement type**:
What a KPI *measures mathematically*, declared per KPI and the **sole driver of its chart form** — `flow` (sum-able quantity), `average`, `rate`, `bounded-ratio`, `count`. Form follows deterministically: `flow` → filled line; `average`/`rate` → unfilled line; `count` → bars; `bounded-ratio` → threshold band against a target. Distinct from the KPI's **business category** (`Doanh thu`, `LIVE Shopping`), which groups KPIs for navigation and never selects a mark — two revenue KPIs can need different marks, which is exactly how GMV (a total) and AOV (an average) came to render identically.
The `ChartKind` union it replaces is retired: `health-bar` was declared by no KPI, and `gauge` was permanently starved because the envelope mapper hardcoded its value to `undefined`, so Cancellation rate rendered no chart at all on live data. The `HealthBar` component in `packages/ui` survives the rename — it is a **meter** primitive (segmented fill + target tick, severity-toned), distinct from a chart form.
_Avoid_: choosing a chart per KPI by hand, category-driven chart form, area fill on a non-cumulative measure (an area under a rate reads as a total), `health-bar`/`gauge` as chart kinds, confusing the retired `health-bar` kind with the live `HealthBar` meter component, using the `HealthBar` meter for a KPI whose question is "is this getting worse" (a meter shows state, not trajectory)

**KPI goal direction**:
Whether a KPI is `higher-is-better` (GMV, AOV, CTOR, LIVE hours) or `lower-is-better` (Cancellation rate), declared per KPI alongside [KPI measurement type]. **Semantic tone is a function of delta sign *and* goal direction** — never the sign alone. Deriving tone from the sign alone painted a rising Cancellation rate green and labelled it `positive`, i.e. more cancelled orders read as good news.

**Chart colour policy**: a KPI's trend mark wears a **stable hue tied to the metric**, not to how it happened to move — identity must not flicker between periods or ranges. Direction is carried by the delta chip, which pairs tone with an arrow and a number so status never travels by colour alone. The **status palette is reserved** for genuine goal breaches, principally the `bounded-ratio` tolerance band.
_Avoid_: tone from delta sign alone, trend-coloured trend lines, repainting a metric when the range filter changes, spending success/destructive colours on ordinary movement

**Chart scrub readout**:
Touch equivalent of a desktop hover layer on Analytics charts: dragging along the plot moves a scrub line, and the scrubbed point's value and date replace the **hero value and freshness line above the chart**, reverting on release. The readout never floats over the plot — at phone width a tooltip occludes the data it explains. Below roughly ten points (the 7-day range) per-point dots suffice and no scrub is needed.
_Avoid_: hover-only affordances on a mobile-web surface, tooltips overlaying the plot, tap-a-point targets on a dense series (30 points at phone width give ~17px per point)

**Decision-grade ML**:
Trained techniques (T2, T6, T8) that must pass backtest promotion gates before Phase 2.5 artifact load. All Home outputs remain **display-grade** (advisory only); gates vet accuracy, not execute authority. Former "3 vetted suites" logic is **recycled** into T2/T6/T8 per ADR-011.
_Avoid_: the 3 vetted suites (closed catalog — superseded by ADR-011)

**Manual refresh pipeline**:
Phase 2's on-demand execution model for aggregates → signals → recommendations → copy → persist — triggered by `POST /v1/action-cards/refresh`, never by Celery beat or cron ([ADR-021](docs/adr/021-manual-refresh-pipeline-and-action-card-persistence.md)).
_Avoid_: daily batch, cron pipeline, scheduled scoring

**Phase 3 polyglot target**:
Documented future stack — ClickHouse, S3, SQS — adopted only when volume/latency/burst justify it. MVP/Phase 2 stays single-store Supabase Postgres ([ADR-012](docs/adr/012-architecture-reconciliation-mvp-vs-target.md)).
_Avoid_: target architecture (overloaded — use Phase 3 polyglot target)

## Frontend surfaces

**`apps/demo`**:
The public Interactive Demo (`demo.app-juli.com`) — ADR-023 four-destination IA (Home, Decisions, Analytics, Settings). Home additionally shows a summary-only activity strip (done/running/needs-attention counts) above its two launcher cards ([ADR-053](docs/adr/053-demo-home-activity-summary.md)). Phase 2.6 mock data; **Phase 2.10** swaps agreed destinations to masked reference-shop KPIs without auth ([ADR-037](docs/adr/037-phase-2.10-demo-real-data-no-auth.md)). Sign-in/OAuth and Landing remain Phase 3 ([ADR-024](docs/adr/024-phase-2.6-2.7-frontend-resequencing.md)).
_Avoid_: the Demo (ambiguous with retired two-screen Home+Actions IA)


**Commerce data pipeline (CDP)**:
The production commerce-data path — TikTok webhooks + targeted Partner fetch → raw Postgres → transform/aggregate → compute → precomputed envelopes (+ Redis read-through) — shared by Analytics and Decisions. **Continuous wire sequencing is Analytics-first, then Decisions next.** “CDP” here means Juli’s **commerce data pipeline**, not a third-party customer-data platform product. Physical Postgres layout: **CDP medallion model** ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md)). See [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md), [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md).
_Avoid_: marketplace CDP SaaS products, treating Demo mock fixtures as Decision SoT after continuous wire

**CDP medallion physical model**:
Phase 3.5-A Postgres layout — four schemas in one Supabase project: **`bronze.*`** append-only raw, **`silver.*`** idempotent domain upserts, **`gold.*`** precomputed forks, **`ops.*`** pipeline checkpoints (not customer data). One-way deps bronze→silver→gold; **one writer per table**; shop-scoped **Shared Compute Orchestrator** (not Postgres materialized views). Supabase clients see **gold only** (views/RPC + RLS). **Per-domain cutover**; Demo/Mock stays green via serving gold or a short-lived compat view; **no long-term dual-write**. Serving **`gold.kpi_envelopes`** uses flexible **`payload.kpis`**. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md).

**Bronze layer**:
Append-only raw landing in Postgres — webhook payloads, targeted Partner fetch rows, reconcile snapshots, cold-start backfill pages. Ingest never upserts over history. Feeds silver via orchestrator jobs only. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md).

**Silver layer**:
Idempotent domain upserts after dedupe/normalize — canonical one row per domain key. ML **feature sources** read silver only. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md).

**Gold layer**:
Precomputed outputs forked from silver — not refreshed via Postgres materialized views. **Serving gold:** `gold.kpi_envelopes` for Analytics/Decisions/Demo/Redis. **ML gold (optional/stub):** `gold.ml_feature_snapshots`. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md).

**Ops schema**:
Pipeline and orchestration state — e.g. `analytics_backfill_partitions`, shop/domain checkpoints. Not seller-facing; service-role only. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md).

**One writer per table**:
Each medallion table has exactly **one owning writer** (service/module). Downstream layers may read upstream; no reverse writes. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md).

**Serving vs ML gold fork**:
**Serving** (`gold.kpi_envelopes`) powers product reads and Redis; **ML gold** may persist promoted snapshots later. **ML reads silver, never serving gold**. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md).

**Serving KPI envelope contract**:
Locked shape for `gold.kpi_envelopes`: `shop_id` with `computed_at`, `envelope_version`, and **`payload` jsonb** containing **`kpis`** keyed by stable `metric_id`. [ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md) B′ **five** are **initial catalog keys**, not frozen DB columns. See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md) (Q3).

**Shared Compute Orchestrator**:
Shop-scoped job runner — **one job per material trigger** — bronze append → silver upsert → gold envelope write (idempotent stages). Same trigger serves Analytics-first then Decisions ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)). See [ADR-046](docs/adr/046-cdp-medallion-physical-model.md) (Q4).

**Speed / Batch / Serving layers**:
Freshness architecture **orthogonal to medallion schemas** ([ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md)) — **Speed** (webhook → targeted fetch → Shared Compute → gold), **Batch** (daily staggered reconcile → same gold), **Serving** (`gold.kpi_envelopes` + Redis).

**Serving layer**:
Product read model — **`gold.kpi_envelopes`** plus required Redis read-through. Established in **3.5-A0**; populated by Speed (**A1**) and healed by Batch (**A2**). See [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).

**Phase 3.5-A (Analytics CDP split)**:
**A0 Foundation** — medallion schemas, serving gold contract, per-domain cutover ([#598](https://github.com/thienphung00/Juli-AI/issues/598)); **A1 Speed** — material handoff, targeted fetch, five Demo KPIs ([#601](https://github.com/thienphung00/Juli-AI/issues/601)); **A2 Batch** — daily staggered reconcile ([#602](https://github.com/thienphung00/Juli-AI/issues/602)). **3.5-B** (#599) blocked on **A1**, not A2. See [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).

**Webhook-first continuous spine**:
Material TikTok webhooks enqueue ETL handoff and shop-scoped fetch-then-precompute; polling is gap reconciliation. See [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md).

**Targeted fetch**:
Post-webhook or post-reconcile Partner reads limited to resources implicated by the triggering event or gap. See [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md).

**Daily staggered reconcile**:
Multi-shop gap-reconciliation scheduler — one shop-scoped window per day, staggered across the fleet. See [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md).

**Demo Main KPI set (B′)**:
Five CDP-envelope-backed Main KPIs for **`apps/demo` Analytics**: GMV (TikTok), AOV, CTOR, LIVE hours, and Cancellation rate — exactly five. Each maps to a **`metric_id`** in `gold.kpi_envelopes.payload.kpis`. See [ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md).

**Demo dual credential model**:
**Mock mode (default):** shared masked reference-shop precompute via **`production_read`**; webhook-first material events + reconcile. **Login mode (3.5-C):** session-bound shop reads via **`seller_connect`**. See [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md), [ADR-050](docs/adr/050-cdp-slice-3-5-c-two-gated-exits.md).

**seller_connect credential**:
Per-shop TikTok Shop OAuth credential rows for Sign-in shops — must not cross-mix with **`production_read`**. See [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md).

**TikTok document corpora**:
Large local markdown archives (Business / Academy / Partner) for **Architect/Meta** vendor-depth verification only — catalog → Grep → selective Read. Executor/Review use curated `tiktok_api` / `tiktok_platform` only. See [ADR-051](docs/adr/051-tiktok-corpora-catalog-retrieval.md).

**Durable design skill stack**:
Focus/Meta routing for frontend design work — **Open Design** + **Mobbin** upstream for references; **`ui-ux-design`** + **`ui-ux` executor** for Next.js implementation; **`shadcn`** for atom-level registry primitives only, folded into `@juli/ui`. Open Design sits above `ui-ux-design` and does not replace it. See [ADR-043](docs/adr/043-frontend-design-skill-wiring.md).
_Avoid_: Open Design as the Demo implementation skill, permanent Airtable-first Meta pipeline, wholesale Demo→shadcn migration

**Design reference pipeline**:
Ephemeral, PRD-scoped orchestration for one visual refinement pass — Airtable layout extract → Open Design components/layouts → Mobbin problem-section screen refs → Meta-prepared caches/artifacts → design sub-agents → Shadcn atom refinement → `@juli/ui` implementation. **Not** durable harness infrastructure; superseded after refinement by the **Durable design skill stack** ([ADR-043](docs/adr/043-frontend-design-skill-wiring.md)).
_Avoid_: treating Airtable as copy SoT, treating this pipeline as permanent agent-runtime config

**Airtable layout reference**:
One-shot visual/layout inspiration for the Demo visual refinement PRD — extracts component and layout patterns into Open Design; **not** copy authority (`dictionary.md`), **not** IA authority (ADR-023). Discarded as a Meta stage after the PRD completes.
_Avoid_: Airtable copy SoT, Airtable IA changes

**Mobbin screen reference**:
Reference-only UI inspiration from Mobbin search — adapted to Juli tokens ([ADR-015](docs/adr/015-design-system-token-foundation.md), `docs/product/design/`); never a 1:1 binding spec or copy source. Part of the **Durable design skill stack** ([ADR-043](docs/adr/043-frontend-design-skill-wiring.md)).
_Avoid_: Mobbin as authoritative layout/copy, pixel-perfect Mobbin clones

**Hybrid Juli UI model**:
Demo composes from **`@juli/ui`** + **`@juli/theme`**; shadcn registry may refine atoms then migrate into `@juli/ui`. No wholesale replacement of Demo page scaffolding with raw shadcn. See [ADR-043](docs/adr/043-frontend-design-skill-wiring.md).
_Avoid_: shadcn as Demo surface SoT, deleting `@juli/ui` for page composition

**Decision plan review**:
Seller-facing Recommendations detail flow on `apps/demo` **mobile-web** — the agent presents a proposed plan the seller traverses **section by section**, planning-mode style, instead of a flat form. The agent **pre-commits a proposed value for every field**; each section offers recommended options, a custom input, and an **ask-before-deciding** follow-up. Sections rest **folded** and expand on demand — the AI recommendation explains when asked, it does not narrate by default. Optimises for minimal cognitive load and **minimal time to value**: agreeing with the plan requires expanding nothing. Supersedes the **Five-stage decision review** ([ADR-055](docs/adr/055-decision-plan-review.md)).
_Avoid_: Five-stage decision review (Why → Analytics → Inputs → Preview → Approve — superseded), flat all-fields form, blank-by-default seller fields, backend step names in seller UI, node/graph configuration surfaces, inventing a new recommendation engine

**Agent-proposed value**:
The value the agent commits to for **every** field of a Decision plan review before the seller opens it — there is no blank-by-default field and no class of fields the agent declines to propose. The seller accepts, picks another recommended option, supplies a custom input, or asks a follow-up first. Accepted trade-off: pre-committing judgment-bound fields risks **rubber-stamping**; the mitigation is the ask-before-deciding affordance, not a blank field ([ADR-055](docs/adr/055-decision-plan-review.md)).
_Avoid_: empty-string defaults as "the seller will fill it in", seller-reserved blank fields

**Repeat consent**:
The post-completion ask — whether Juli may run this workflow again without a fresh approval. Raised **after** the work finishes (acknowledgement → progress → repeat consent), never bundled into the initial approval. Gated three ways: only on lifecycle **`completed`** (never `needs_input`), **once per workflow kind** (not per execution), and only for workflows whose shipped copy carries **no no-auto-act promise** — 5 of 11 today. What is granted is **pre-approval with notification**, never silent automation ([ADR-055](docs/adr/055-decision-plan-review.md)).
_Avoid_: an automation toggle inside the approve step, consent implied by a single approval, prompting after `needs_input`, silent automation, conflating "không tự suy diễn" (won't infer a number) with a no-auto-act promise

**No-auto-act promise**:
Shipped seller copy stating Juli will not perform an action unaided — e.g. `prevent_cancellation_8a`'s "Juli không tự động xử lý thay", `clear_excess_4`'s "chỉ thực hiện sau khi có xác nhận thực tế". Lives in **`risks` as often as `knownLimits`**. Bars **Repeat consent** for that workflow; widening eligibility means changing the copy deliberately first ([ADR-055](docs/adr/055-decision-plan-review.md)).
_Avoid_: treating these as class-A "won't infer a number" caveats, a consent prompt that contradicts shipped copy

**Impact metric**:
The tied Main KPI shown on a Decision plan review card — the card's centre of gravity. Every workflow already maps to one [ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md) Main KPI via `analyticsMetricKey`: **CTOR** (optimize-product, create/update/delete-activity), **GMV** (prevent-cancellation/return/refund, replenish-inventory, create-hero-product), **AOV** (clear-excess), **Cancellation rate** (process-order). Shows the KPI's **real current value and trend** from `gold.kpi_envelopes` plus a **directional goal** — never a projected magnitude, and **one state only** (pre-approval; unchanged after approval, since Mock executions are dry-run and no effect exists to observe). **LIVE hours is tied to no workflow.** See [ADR-055](docs/adr/055-decision-plan-review.md).
_Avoid_: projected impact magnitudes, post-execution "what your approval achieved" deltas in Mock mode, retrofitting a workflow onto LIVE hours

**Upload screening**:
The pre-acceptance check on seller-supplied files — **image files only** (both `main_images` and `supporting_file`, so a PDF certificate must be photographed instead), enforced by **file-signature (magic-byte) allowlist**, **full image decode** (corruption and polyglot detection), a **size cap**, and rejection when declared extension/content type disagrees with the signature. **Server-side is authoritative**: the real boundary is `_decode_optional_base64` / `_resolve_image_uri` in `services/execution/listing.py`, not the Demo control. Rejection follows the `ValueError` → `VALIDATION` → HTTP 400 convention. Detection is backed by **mitigation**: the image is **re-encoded** and the re-encoded bytes forwarded, which destroys appended data and polyglot payloads (OWASP image rewriting); the **filename is generated** (UUID + detected extension), never accepted from the caller; and a **pixel cap** guards decompression bombs that byte caps miss. **Not antivirus** — re-encoding removes payloads, it does not identify them. AV/CDR are acknowledged by OWASP and deliberately deferred to a separate ADR ([ADR-055](docs/adr/055-decision-plan-review.md) item 20).
_Avoid_: describing this as virus protection or AV, trusting the browser-supplied MIME type, client-side validation as the gate, widening the allowlist in code instead of amending the ADR

**Post-execution field**:
A workflow input that can only be answered **after** execution — e.g. `prevent-return.resellable_quantity` ("sau kiểm tra"), `replenish-inventory.received_quantity` ("sau giao"). Belongs to a later lifecycle moment; must not be collected at approve time ([ADR-055](docs/adr/055-decision-plan-review.md)).
_Avoid_: collecting post-execution fields in the approval flow

**Branch discriminator**:
The field whose value determines which later sections are relevant at all — `process-order.shipping_type` (Ship by TikTok vs Ship by Seller), `prevent-return.seller_decision` (approve vs reject). Gates section visibility; the superseded flat form rendered every branch's fields regardless ([ADR-055](docs/adr/055-decision-plan-review.md)).
_Avoid_: rendering dead branch fields, treating conditional fields as always-required

**Seller-surface copy**:
Vietnamese Demo strings that are benefit-led, one idea per line, free of backend jargon (webhooks, endpoints, `feature_id`, tool names, FBS/FBT badges). Machine fields may remain in fixtures/code for dry-run but **never render** in Demo UI. Authority: **Copy dictionary** + **Design context** ([ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)).
_Avoid_: "Độ tin cậy" / "Có thể thực thi qua FBS" in seller UI, exposing `tool_name` or workflow internals on cards

**`apps/landing`**:
Public marketing site (`app-juli.com`). Own IA per Phase 2.7 PRD; reuses design tokens. **Not required for Phase 2.10.** The hero carries **two paired CTAs**: Demo (Mock mode, low friction) and **Login/Signup** wired to the shared auth entry on the main domain (`LOGIN_URL` in `apps/landing/src/lib/site.ts` → `app-juli.com/login`). Hero framing is cost prevention plus revenue optimization, with a **three-improvements promise** ("3 điều shop bạn cần cải thiện") as the signup driver, delivered by TikTok OAuth shop connect. Elsewhere the Demo stays the sole CTA, including the curiosity CTA ("khám phá hiệu suất shop của bạn" → Demo). No pricing section until packaging is decided. Figma reference exports live outside the repo; extracted raster assets live in [`packages/brand`](packages/brand/) ([ADR-056](docs/adr/056-brand-asset-package.md)).
_Avoid_: Landing Page IA inside `docs/product/design/Screens/`, pricing tiers on the public LP, a standalone "Đăng ký" CTA (it is always paired as "Đăng nhập / Đăng ký"), landing and Demo pointing at different login destinations, em dashes in landing copy

**`packages/brand`**:
Workspace package owning canonical Juli brand rasters (wordmark, bird glyph, mascot hero art) and the `<JuliLogo>` component. Exactly one bird and one wordmark are canonical — the raw brand set's other variants stay out. Apps import from it — never copy asset files into an app's `public/` ([ADR-056](docs/adr/056-brand-asset-package.md)).
_Avoid_: per-app copies of the logo, binary assets inside `@juli/ui`, mixing bird/wordmark variants, shipping baked-copy infographic banners

**Mock/Sign-in mode toggle**:
`apps/demo`'s mode switch. **Mock mode** (2.10 default): shared masked reference-shop precompute; **material webhooks** (#1, #2, #5, #12, #27, #39, #67, #68 with coalesce) + hourly reconciliation advance data; **Demo Refresh is fake** (re-read cache/UI only); Decision actions are **dry-run**. **Sign-in mode** (Phase 3+): one user per shop; hybrid material webhooks + real Refresh recompute; approval-gated executors. See [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md).
_Avoid_: Mock visitor force-recompute, Fujiwa live writes from public Demo, assuming Sign-in is required to read masked KPIs

**Demo dry-run execution**:
Decision/Action paths on public Mock Demo that look like TikTok writes but only persist local/demo execution records — never call Partner write APIs with the reference merchant's OAuth credentials.
_Avoid_: sandbox-but-real writes against Fujiwa from public Demo

**Public Demo read API**:
Unauthenticated HTTP GETs used by `apps/demo` (Mock mode) to load masked Analytics/Decision envelopes for the one server-configured reference shop. Visitor cannot supply arbitrary `shop_id`. See [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md).
_Avoid_: public tenant switcher, requiring visitor JWT to read Demo KPIs in 2.10

**Masked reference-shop data**:
Reference-shop (Fujiwa) metrics for public Demo: **identity mask, real magnitudes** — aliased shop name and stable id/title aliases; real GMV/trend numbers and chart shapes. Not a second fake dataset. See [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md).
_Avoid_: mock data (2.6 fixtures), numeric noise/scale-factor masking, multi-shop Demo tenancy

**`packages/contracts`**:
Shared TypeScript fixture/type package for Decision/Action Card, execution, and KPI mock shapes — structurally aligned with `docs/api/data-models/` by hand, not code-generated.
_Avoid_: assuming these types are auto-generated from data-models

**Reference shop**:
The one pre-connected TikTok shop (e.g. Fujiwa/SANDBOX_VN) whose real data powers `apps/demo`'s Sign-in mode in Phase 3. Phase 3 does not add per-visitor self-serve TikTok connection — that is Phase 3.5.
_Avoid_: implying Phase 3 opens self-serve TikTok OAuth to arbitrary public visitors

**production_read credential**:
The `tiktok_credentials` row for Fujiwa Partner Section A reads — merchant `7658073774813611784` + capability `production_read`. Required by analytics backfill and Fujiwa poll; distinct from `seller_connect` OAuth rows.
_Avoid_: using `seller_connect` as a silent fallback for production analytics reads

## Seller workspace

**Decision**:
The seller-facing primary object — a ranked recommendation envelope wrapping one validated workflow plus reasoning, required inputs, status, and impact estimate ([ADR-014](docs/adr/014-decision-copilot-app-structure-and-journey.md)). What sellers review on `/decisions`.
_Avoid_: AI Action Card, recommendation card (UI renderings — see **Action Card (backend)**)

**Action Card (backend)**:
The Postgres persistence/API-layer name for the row backing a **Decision** — `action_cards` table, `ActionCardsRepo`, `POST /v1/action-cards/refresh`. 1:1 with one seller-facing Decision; layer-boundary naming split, not a competing synonym. Product/UI says "Decision"; backend says "Action Card."
_Avoid_: "Action Card" in seller-facing copy; "Decision" as SQLAlchemy model name; conflating with unrelated `Recommendation` model

## Inventory

**Phase 2 FBS-only fulfillment**:
Phase 2 executors assume **Fulfillment by Seller (FBS)** only. FBT paths deferred to Phase 5. Webhook catalog entries continue ingest/ACK/ETL; no FBT executor dispatch until Phase 5.
_Avoid_: implementing FBT clearance or restock writes in Phase 2

**Supplier-sourced replenishment**:
Restocking via external supplier integration (`Replenish via Supplier` workflow). Terminal step syncs available quantity to TikTok via Product API.
_Avoid_: Supplier Sourcing (informal), dropship (when meaning ERP/self-managed stock)

**ERP-sourced replenishment**:
Restocking via purchase request and inbound receipt in the seller's ERP (`Replenish via ERP` workflow). Juli does not operate a warehouse; ERP is the seller's stock ledger. Terminal step syncs to TikTok via Product API.
_Avoid_: ERP-sourced replenishment (when meaning supplier path), Warehouse System (phantom executor)

**Customer Service execution**:
Approval-gated workflow actions for Resolve Recurring Customer Complaints (Phase 3 deferred) and live Post-sales workflows **Request Return (8b)**, **Request Cancellation (8a)**, **Request Refund (8c)**. Phase 2 CSAT is advisory-only with **no live workflow key**. Step catalogs: `execution_layer.md`.
_Avoid_: Prevent Cancellation/Return/Refund (retired names), Workflow Engine (phantom executor)

## Scoring

**Computed KPI**:
A visual-layer KPI derived from joins or rollups across two or more synced Postgres sources — not a single API field. Phase 2 computes in `services/aggregates/`; techniques are deterministic rules; trained T1/T2 remain Phase 4.
_Avoid_: derived metric (generic), multi-source KPI (ambiguous)

**CSAT proxy**:
Phase 2 stand-in when no buyer review/chat text exists: score from return_rate_30d via `rules_proxy`; **no workflow_keys**. Real CSAT replaces when a legal text source exists ([ADR-011](docs/adr/011-display-grade-analytics-layer.md)).
_Avoid_: CSAT score (when meaning the Phase 3 model), customer satisfaction (generic)

## Execution

**Playbook-guided agent authority**:
The decision-authority split for LLM agent workflow execution (Phase: agent execution, ADR-068 pending): Juli's deterministic scoring pipeline owns *what* is recommended; the seller owns approval (of the workflow, and again for confirmation-class writes); the LLM owns *how* an approved workflow executes — but only inside that workflow's **playbook**, the specified end-to-end step sequence derived from `execution_layer.md`. Within a playbook step the agent reasons freely: selects allowlisted tool calls, proposes parameters, interprets sanitized results into seller language, emits structured output. It never selects workflows, never calls tools outside the allowlist, never invents thresholds.
_Avoid_: "LLM never decides" (over-broad after ADR-068 — it never decides *what*, it does decide *how*), autonomous agent (implies workflow selection authority), free-form agent loop (ignores the playbook constraint)

**Workflow playbook**:
The per-workflow ordered step specification the agent must follow during execution — compiled from the workflow's documented TikTok Partner API sequence in `execution_layer.md` into the workflow prompt/config, naming each step's intent and its permitted tools/endpoints. Bounded structure with in-step reasoning freedom.
_Avoid_: script (implies no reasoning), DAG engine (playbooks are linear specs, not a generic engine)

**Agent tool**:
An LLM-callable operation registered as a `ToolSpec` in `services/agent/tools/` (ADR-069 pending): business-semantic English snake_case name (never a vendor endpoint name), Pydantic input/output models (the LLM-facing JSON schema derives via `model_json_schema()`), read|write classification, auto|confirm policy, timeout. Distinct from the legacy Celery tool registry (`services/execution/runner.py`), which stays untouched; both share the guarded TikTok resource layer. Writes execute in-run and are audited as `ToolExecution` rows.
_Avoid_: vendor endpoint names as tool names, registering NEVER-class operations, extending runner.py with agent metadata

**Decision-point granularity**:
The rule for agent tool boundaries (ADR-069 pending): split where a decision point, a policy-class boundary, or a confirmation sits between calls; bundle only no-decision, same-class adjacent calls (Optimize Product steps 2+3 → `get_seo_keywords` is the only bundle). Bundled tools emit sub-step events so narration stays 1:1 with documented playbook steps.
_Avoid_: strict 1:1 tool-per-step (pays a reasoning-free LLM turn), read+write bundles (breaks per-write CONFIRM)

**Agent-safe tool result**:
The sanitized shape a tool returns to the LLM (ADR-070 pending): a Pydantic output model carrying business semantics only — no endpoints, status codes, vendor request IDs, or raw payloads; context-bound IDs (no ID params where entities are pre-bound); machine values (ISO-8601 UTC dates, numeric value + `currency` field, numeric rates, English keys); free text in source-role envelopes; hard caps with signaled truncation (~2k tokens/result, `{truncated, omitted_count}`); errors as `{category, message, retryable}`; banned-pattern checked fail-closed before entering the conversation.
_Avoid_: passing normalized ETL DTOs straight through, display formatting in tool results, silent truncation, LLM-side summarization of tool results

**Source role**:
Server-assigned provenance of free text in agent tool results (ADR-070 pending): `juli` (implicit trusted default), `vendor` (TikTok/marketplace text — data, never instructions), `seller` (client inputs — preference within policy). Assigned from field provenance server-side, never inferred from content; named `source` to avoid colliding with chat-API roles. No buyer role.
_Avoid_: role (chat-role collision), inferring source from content, buyer role (rejected)

**LLMService**:
The single module through which the product calls a model (ADR-071 pending): a neutral block interface — `complete(messages, system, tools, config) → AssistantTurn` of `TextBlock`/`ToolCallBlock`/`FinalResponse` + `Usage` — with the OpenAI Responses-API adapter private inside. Stateless (conversation rebuilt from the P-CS store), turn-level blocks (`assistant.text.delta` reserved for future chat surfaces), config resolution playbook > env > defaults, `OPENAI_API_KEY` fail-closed startup assertion, `openai` importable only here (AST containment). Base model: GPT-5.4 nano.
_Avoid_: provider SDK types outside the module, OpenAI server-side thread state (`previous_response_id`), LiteLLM, `LlmGenerator` (retired seam)

**Workflow prompt**:
The complete hand-written per-workflow instruction file sent to the agent model (ADR-072 pending): eight ordered sections (role, mandate & limits, source-role rules, input-signals guidance, playbook slot, recommend-within-scope, output guidance + worked example, prohibited behaviors), English instructions with Vietnamese output exemplars governed by `dictionary.md`. Lives at `services/agent/prompts/<workflow>/vN.md`, version-addressed; the `{playbook}` slot is the only templated part, rendered from the typed `Playbook` artifact so prompt text and enforced allowlist cannot disagree. Run data never appears in the prompt — it arrives as the opening `juli`-source context message. Extraction trigger: when a second workflow's prompt lands, shared sections are extracted so no behavior rule lives in more than one file.
_Avoid_: splicing run data into the prompt text, editing a released version in place, Jinja/layered composer (rejected for v1)

**Prompt version**:
The immutable identity of a released workflow prompt (ADR-072 pending): `<workflow>.vN` plus the `prompt_sha256` of the composed system prompt, both recorded on each `workflow_runs` row. A released `vN.md` is never edited — changes become `vN+1.md`; eval experiment variants are sibling files. The production pin is a code constant, not an env var, so what runs is always what was reviewed. Snapshot tests pin the composed bytes per released version.
_Avoid_: mutable prompt files versioned only by git, DB prompt registry (premature), env-selected prompt versions in v1

**WorkflowRunStatus**:
The 8-state lifecycle of an agent workflow run (ADR-068 pending): `created → queued → running ⇄ waiting_approval → completed | failed | cancelled | timed_out`. Stored state answers "what can happen next"; phase narration ("Đang phân tích…") travels as SSE `workflow.status` events, never as states. Maps onto — without rewriting — `ExecutionStatus` (per spawned write-tool execution), `ActionCard.status` (card side: `approved` at run creation, `executing` while live), and the frontend lifecycle, which gains a real terminal `failed` (deliberate supersession of ADR-055's no-terminal-failure note for agent runs).
_Avoid_: encoding narration phases (GATHERING_CONTEXT, ANALYZING) as stored states, extending `ExecutionStatus` with run semantics, reusing `DemoExecutionState` on the agent path

**Tool execution policy**:
The per-tool execution class on a `ToolSpec` in agent workflow execution (ADR-068 pending): **AUTO** (READ + internal tools — run without pausing), **CONFIRM** (every WRITE tool this phase — the run pauses with `workflow.approval_required`, showing the agent-composed mutation as a diff, because LLM-authored content did not exist at plan-approval time), **NEVER** (operations absent from every playbook — not registered as tools at all, structural rather than runtime). Repeat consent (ADR-055 item 19) is the only CONFIRM→AUTO downgrade path, valid solely for the five repeat-consent-eligible workflow kinds; class-D shipped promises must be changed deliberately before widening.
_Avoid_: requires_confirmation boolean (two-state — misses NEVER), auto-execute allowlist (policy lives on the ToolSpec, not a separate list)

**Action executor**:
The `System` column in an execution action table — must name a real integration surface (TikTok Partner API family, Third-Party connector, Juli AI LLM, or User input). Phantom labels forbidden. **Promotion API** vs **Marketing API** are not interchangeable.
_Avoid_: Internal engine names with no implemented client; "Ads API" on Shop Partner host for campaign writes

**TikTok OAuth redirect URLs**:
Production callback URIs for Shop Partner seller consent vs Marketing/Business advertiser vs account-holder flows — three distinct portal fields. See [ADR-034](docs/adr/034-tiktok-business-oauth-redirect-urls.md).
_Avoid_: reusing Shop OAuth callback for Business advertiser or account-holder registration

**Ads KPI workflow routing**:
Analytics Ads KPIs (ROAS, CAC, CTR) link to **Promotion** workflows from `execution_layer.md` — not Shop Ads Marketing API budget/bid writes (out of Phase 2 Partner scope).
_Avoid_: Increase Ad Budget, Reduce Ad Spend (retired P1.8 catalog labels)

**Product bundle routing**:
Multi-SKU / bundle listing optimization is a capability inside **Optimize Product (2)** — not a standalone workflow in `execution_layer.md`.
_Avoid_: Create Product Bundle (phantom workflow)

**Shop Status KPI routing**:
SPS / AHR / Violation Points render from mock/fixture data in Phase 2 — advisory display only, **no execution_layer workflow mapping** until a live source exists.
_Avoid_: mapping Shop Status KPIs to live workflows while data remains mock

## GMV impact measurement

**Fujiwa T1 GMV experiment**:
Disposable offline calibration — single T1 ETS on Fujiwa daily shop GMV for observed-vs-counterfactual incremental GMV. Pathfinder for Phase 4 T1; local offline artifacts only. See [ADR-032](docs/adr/032-fujiwa-t1-gmv-experiment-scope.md).
_Avoid_: treating outputs as decision-grade, persisting experiment rows into Analytics product tables

**Mediated Juli GMV impact**:
The intended future way to estimate Juli's effect on client GMV: compose **Juli → Product/LIVE mediators** and **mediators → GMV** elasticities. Requires shipped workflows plus enough history; calibration-grade until promotion gates exist. Hop detail: [ADR-032](docs/adr/032-fujiwa-t1-gmv-experiment-scope.md).
_Avoid_: direct Juli→GMV as the only story, Value calculator assumption tabs as measured Juli impact

## Security baseline

**Default-deny data boundary**:
The stance that a Postgres schema is closed to `anon`/`authenticated` by **default privileges**, not by per-table opt-in — `REVOKE ALL` plus `ALTER DEFAULT PRIVILEGES … REVOKE ALL ON TABLES/SEQUENCES`, so tables created later are born closed with no author action. Already true for `bronze`/`silver`/`ops` via [migration 021](backend/src/juli_backend/database/migrations/versions/021_medallion_schemas.py); extended to **`public`** by [ADR-061](docs/adr/061-first-user-security-baseline.md). `gold` is the only client-reachable schema, by explicit allowlist.
_Avoid_: per-table RLS as the primary tenant boundary, treating a one-time `REVOKE` as equivalent (it leaves future tables open)

**Security invariant**:
A control asserted mechanically in `pr.yml` so drift fails the build — data boundary, route auth coverage, debug surface disabled in production, no credentials in query strings, rate limiter attached. Distinct from a **Startup assertion**. See [ADR-061](docs/adr/061-first-user-security-baseline.md).
_Avoid_: documenting a control in a runbook and calling it enforced, security checklists as review-time judgment only

**Startup assertion**:
A boot-time check for controls that live in deployed configuration — AWS Secrets Manager, systemd env files, the Supabase console — and are therefore invisible to CI. The process refuses to start rather than degrading silently; `require_env("SUPABASE_JWT_SECRET")` is the motivating case. See [ADR-061](docs/adr/061-first-user-security-baseline.md).
_Avoid_: `os.environ.get(name, "")` for any security-critical value, treating a missing secret as a soft default

**Security logging baseline**:
The vendor-free logging floor shipped with the first-user security work — root `dictConfig` JSON to stdout/journald, `request_id` middleware, `--proxy-headers` for real client IPs, and coverage of webhook signature rejections, auth failures, and limiter 429s. Distinct from **DOCP**: this is the evidence floor for incident response, not the observability control plane. Phase 2.11 points a shipper at the same stream. See [ADR-061](docs/adr/061-first-user-security-baseline.md).
_Avoid_: treating DOCP/OpenObserve as a prerequisite for having any security logs, calling journald-only logging "structured" before the `dictConfig` lands

**Non-functional RLS policies**:
The ten existing `USING (… = current_setting('app.current_user_id')::uuid)` policies (migrations 001, 002, 017, 019, 020, 022, 024). The backend never sets that GUC, so they have never scoped a row — they only deny by raising. Treat as **absent** until rewritten onto `auth.uid()` when 3.5-C Login mode ships client-direct `gold` reads.
_Avoid_: citing these as existing tenant isolation, assuming RLS-enabled means RLS-working

## CI / test lanes

**Three-tier CI**:
Branch validation in `pr.yml` (#657+): **issue** (`pull_request` → `feature/*-wave`), **wave** (`push` → `feature/*-wave`), **main** (`pull_request` / `merge_group` → `main`/`staging`). Cheap path-filtered checks on issue; integration/architecture on wave push; full regression/E2E/security on wave→main. See [ADR-052](docs/adr/052-wave-free-merge-deferred-artifact-gate.md). Extends ADR-003 / ADR-040 / #657.
_Avoid_: assuming local `main` worktrees match `origin/main`, calling `ai-review` an LLM step, requiring issue PRs to re-green after sibling merges into wave, skipping artifact CI entirely (option B)

**Wave artifact gate (D)**:
On wave→main, CI reads a committed manifest on the wave branch (e.g. `agent-runtime/artifacts/waves/wave-<id>.json` with `{ "issues": […] }`) and checks each listed issue has review/validation artifacts with `status: PASS` (existence + status; not full `meta_prepare_executor` / check suite on every issue push). Issue→wave (**A**): `classify-tier`, `changes`, `gitleaks`, `policy-checks`, plus path-filtered `lint` / `typecheck` / `test` / `frontend` / `demo-frontend` — no artifact jobs. **Manifest ownership (B):** each issue→wave PR must bump the wave manifest to include its issue number; `policy-checks` fails if missing. **Wave push** path-filters **before→after** for integration/architecture/contracts only. Full regression/E2E/security + artifact-gate on **wave→main**. Parallel-status handoffs stay human ops UI — not the CI parser. See [ADR-052](docs/adr/052-wave-free-merge-deferred-artifact-gate.md).
_Avoid_: per-push issue-tier validate-artifacts as the merge SoT, trusting agent-local artifacts with no CI check at main, parsing `parallel-status*.md` as the artifact SoT, forcing all path filters true on every wave push, post-merge-only manifest edits as the primary path

**Free-merge (wave)**:
Path-disjoint issue PRs may merge into `feature/*-wave` without forcing siblings to update-from-base and re-wait CI. Mechanism: **skip issue-tier workflow (or heavy jobs) when only the base advanced** — head SHA unchanged; no “up to date with base” ruleset on `feature/*-wave`. Wave push path-filters against **before→after** of that push (domains just landed). Wave→main runs main-tier gates (full / path-aware as today) plus the wave artifact gate. See [ADR-052](docs/adr/052-wave-free-merge-deferred-artifact-gate.md).
_Avoid_: sync-before-merge between sibling issue PRs on the same wave, treating base-only CI re-runs as merge blockers, requiring up-to-date with wave, diffing wave vs main on every wave push

**PR-safe Tests**:
The default GitHub Actions `test` job on issue-tier (and related) pulls — unit + non-live integration, with `pytest-timeout` (30s/test) and a 15-minute job cap; runs `-m "not live and not demo_contract"` (plus heavier marker excludes on issue tier) and keeps `--cov-fail-under=80`. See [ADR-040](docs/adr/040-pr-safe-tests-lane.md).
_Avoid_: calling the whole `tests/` tree “PR tests”, assuming live Partner calls belong here

**live (pytest marker)**:
Tests that make real outbound TikTok Partner / sandbox HTTP calls. Excluded from **PR-safe Tests**; run in a dedicated merge_group job. See [ADR-040](docs/adr/040-pr-safe-tests-lane.md).
_Avoid_: marking local ASGI webhook signature tests that only use sandbox secrets for HMAC as `live`

**demo_contract (pytest marker)**:
Demo deploy/exit-gate contract pytest owned by dedicated demo CI jobs (`demo-deploy-contracts` / `demo-e2e`). Excluded from the main `test` job to avoid double-running. See [ADR-040](docs/adr/040-pr-safe-tests-lane.md).
_Avoid_: duplicating these files inside PR-safe Tests “just in case”

**migration_heavy (pytest marker)**:
Seeded Alembic downgrade/upgrade integration tests (`tests/integration/test_migrations.py`). Excluded from PR-safe Tests unless migration paths change; included on merge_group. Structural alembic still covered by `migration-check`. See [ADR-040](docs/adr/040-pr-safe-tests-lane.md).
_Avoid_: treating `migration-check` as a substitute for seeded row assertions on merge_group

**phase_scaffold (pytest marker)**:
Completed Phase 2.5 deploy/doc scaffold contracts. Excluded from PR-safe Tests; run on merge_group only.
_Avoid_: deleting these without a path-filtered or MQ replacement


## Vendor document corpora

**TikTok document corpora**:
Three markdown archives for agent planning and ad-hoc verification — `business_documents/` (TikTok Business API), `academy_documents/` (TikTok Academy; UI/product), `partner_documents/` (TikTok Partner API + webhooks). Bodies live on a **shared local root** outside git: `/Users/macos/Juli-AI-local/tiktok-corpora/{business,academy,partner}_documents/` (not under any worktree). **Layered authority:** curated `docs/integrations/tiktok_api/` and `docs/integrations/tiktok_platform/` remain Juli implementation / code SoT; corpora supply vendor depth, gap-fill, and verification. On conflict, cite both — curated binds code until `api-docs` / `platform-docs` promotes a change. See [ADR-051](docs/adr/051-tiktok-corpora-catalog-retrieval.md).
_Avoid_: dumping full corpora into context, treating raw corpora as code SoT, corpus overrides curated silently, committing corpus bodies to git, Business/Partner for UI copy, Academy for webhook schemas, keeping bodies only under `.worktrees/adhoc/`

**Corpus catalog retrieval**:
v1 agent access — thin per-corpus catalogs from YAML front matter, **committed on `main`** under `docs/integrations/tiktok_corpora/` (e.g. `{business,academy,partner}-catalog.json`); Focus routes catalog → Grep → selective Read of matched pages under the shared local corpus root. Cross-corpus answers search all three catalogs then open selected files. Embedding RAG is out of scope for v1. Regenerate catalogs after crawls; do not commit markdown bodies. Partner **`_raw/` is excluded** from catalogs and Focus Grep defaults (clean markdown only). **Harness wiring:** Focus Context Plan + `docs/integrations/tiktok_corpora/README.md` playbook + catalog regen script — **no** new Cursor skill in v1. **Phase gate:** only **Architect (Planning)** and **Meta** may open corpus catalogs/bodies; **Executor** and **Review** must not — they use curated `docs/integrations/` (and ADRs) only. **Downstream distillate:** Architect/Meta turn raw-page findings into **ADRs and curated docs**; lasting contracts promote into curated docs before implement. Task defaults: Academy → UI/product/seller policy; Business + Partner → webhooks/API/data-model; all three only for cross-surface synthesis or curated gap/conflict. **Missing bodies:** fail soft — catalogs still load for discovery; if a body path is absent, cite catalog metadata + curated docs and state corpus body unavailable; never invent page content. See [ADR-051](docs/adr/051-tiktok-corpora-catalog-retrieval.md).
_Avoid_: RAG, vector store, loading whole documents or whole corpora by default, catalogs only on `Juli-AI-local` with no in-repo index, new `tiktok-corpora` skill unless protocol fails in practice, Executor/Review opening corpus pages, Composer executors ingesting raw corpora, passing raw corpus paths into Executor caches as a substitute for ADRs/docs, hallucinating vendor text when local root is missing, hard-failing all corpus answers when only bodies are absent, indexing Partner `_raw/` duplicates

## Agent runtime (Executor domains)

**Domain executor skill**:
Meta-assigned primary skill under `.cursor/skills/domain/<name>/` — see skill-catalog and `agent-runtime/config/slice-routing.yml`.
_Avoid_: marketplace plugin skills as domain executors

**Integrations domain**:
Executor domain for vendor HTTP clients, inbound webhooks, polling/sync, and analytics backfill. Does **not** own Juli product API routes, scoring/copy, or JWT session auth (**backend**); does **not** own schema/migrations/ETL durability (**data-platform**).
_Avoid_: TikTok domain, overlapping ownership with backend for `/v1/*` routes
