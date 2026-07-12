# Juli AI — ubiquitous language

Shared domain language for seller-money workflows across `ios/`, `web/`, and `backend/`.

> Maintained by `grill-with-docs` and `domain-modeling`. Do not edit manually unless correcting an error.
> Architectural decisions live in `docs/adr/`.

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
([ADR-005](docs/adr/011-display-grade-analytics-layer.md)).
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

## Inventory

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
deferred) and live Post-sales workflows Prevent Return (8b), Prevent Cancellation (8a),
Prevent Refund (8c). Phase 2 CSAT is advisory-only with **no live workflow key**.
_Avoid_: Prevent Product Returns (renamed Prevent Return 8b), Workflow Engine, Monitoring Engine, Messaging API (use Customer Service API in execution tables)

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
Home Ads KPIs (ROAS, CAC, CTR) link to **Promotion** workflows from
`execution_layer.md` — Create Activity (7a), Update Activity (7c), Delete Activity (7b)
— not Shop Ads Marketing API budget/bid writes (out of Phase 2 Partner scope).
_Avoid_: Increase Ad Budget, Reduce Ad Spend, Budget Optimization (P1.8 catalog labels — retired)

**Product bundle routing**:
Multi-SKU / bundle listing optimization is a capability inside **Optimize Product (2)** —
not a standalone workflow in `execution_layer.md`.
_Avoid_: Create Product Bundle (phantom workflow — use Optimize Product (2))

**Shop Status KPI routing**:
SPS / AHR / Violation Points render on Home from mock/fixture data in Phase 2 because
Partner API shop-health fields are not available to retrieve. They emit advisory
display only — **no execution_layer workflow mapping** until a live source exists.
_Avoid_: mapping Shop Status KPIs to Process Order / Prevent Cancellation / Resolve
Recurring Customer Complaints while data remains mock
