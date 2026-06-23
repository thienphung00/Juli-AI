# Juli AI — ubiquitous language

Shared domain language for seller-money workflows across `ios/`, `web/`, and `src/`.

> Maintained by `grill-with-docs` and `domain-modeling`. Do not edit manually unless correcting an error.
> Architectural decisions live in `docs/decisions/`.

<!-- Terms are added under ## [Domain area] sections as they are resolved in grilling sessions.
     Format per domain-modeling skill:

     **Term**:
     One or two sentences defining what it IS.
     _Avoid_: rejected alias1, alias2
-->

## Architecture

**Layered model**:
The product's three-layer structure — **visual layer** (Home KPI charts + one-line
advisory signals), **ML layer** (T1–T8 advisory techniques), and **execution layer**
(the workflow → action taxonomy a signal links to). Authoritative docs:
`docs/visual_layer.md`, `docs/ml_layer.md`, `docs/execution_layer.md`
([ADR-005](docs/decisions/011-display-grade-analytics-layer.md) Decision #6).
_Avoid_: 3 Copilots, Copilot surfaces, New Seller / Growth / Revenue Leakage Copilots
(retired UI grouping), "exactly six validated workflows" (closed catalog — retired by ADR-005)

**Workflow taxonomy**:
The domain-organized catalog of workflows (Catalog · Ads · Inventory · Operations ·
Customer Service) and their actions, each action owned by exactly one workflow. Single
source of truth is `docs/execution_layer.md`. The shop profile (`NEW_SHOP` vs
`MID_LARGE_SHOP`) selects the **rule set** via the T8 router, not a UI grouping.
_Avoid_: validated workflow catalog (closed "six only" framing — superseded by ADR-005)

**Copy layer**:
The stage that turns structured ML/rules signals into seller-facing Vietnamese copy
for Decisions/cards. Runs after batch inference, before UI render; uses Claude Haiku
3.5 with a deterministic rules fallback (ADR-006). Receives computed signals only,
never raw financial PII.
_Avoid_: LLM layer, summarizer (when referring to the whole stage)

**Display-grade analytics**:
The lightweight ML layer that powers the visual layer — a small set of reusable
techniques (T1–T8: ETS forecaster, recycled ads regressor, policy rules,
statistical anomaly, deadline rule, recycled return-fraud detector, weighted
ranker, recycled router classifier) applied across all KPIs. Charts plus one-line
"what changed / risk / action" signals on Home; advisory only, never executes
([ADR-005](docs/decisions/011-display-grade-analytics-layer.md)).
_Avoid_: per-KPI models (implies ~19 separate trained models)

**Decision-grade ML**:
Trained techniques (T2, T6, T8) that must pass backtest promotion gates before
Phase 2.5 artifact load — precision/recall or ROAS MAPE thresholds in
`thresholds.py`, golden fixtures, and `feature_schema_hash` validation. All Home
outputs remain **display-grade** (advisory only); gates vet accuracy, not execute
authority. Former "3 vetted suites" logic is **recycled** into T2/T6/T8 per ADR-005.
_Avoid_: the 3 vetted suites (closed catalog — superseded by ADR-005)

**Phase 3 polyglot target**:
The documented future stack — ClickHouse (OLAP), Amazon S3 (raw landing), AWS SQS
(async ingestion queue) — adopted only when volume/latency/burst justify it. Not
built in MVP/Phase 2, which stays single-store Supabase Postgres (ADR-006).
_Avoid_: target architecture (overloaded term — use Phase 3 polyglot target or `phase-2-mvp.md`)

## Seller workspace

**Decision**:
The seller-facing primary object — a ranked recommendation envelope wrapping one
validated workflow plus reasoning, required inputs, status, and impact estimate
(ADR-007). What sellers review and approve on the Decisions tab.
_Avoid_: AI Action Card, action card, recommendation card (UI renderings of a Decision, not a separate concept)
