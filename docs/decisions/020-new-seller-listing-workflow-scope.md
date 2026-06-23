# ADR 020: New Seller Listing Workflow Scope

## Status
Accepted

## Context

- Product prompt (Phase 1.6 Refined) proposed a dual-path New Seller Copilot listing
  workflow: Path A (distributor-known fast listing) and Path B (opportunity discovery),
  converging on a unified listing generation service with CSV/JSON export and Phase 2
  TikTok publish.
- [`EXECUTION.md`](../../EXECUTION.md) originally had only Phase 1 (mock UI, no ML/API),
  Phase 1.5 (ML training), and Phase 2 (live APIs + inference). No listing-specific
  workflow existed beyond a generic `list_products` mock task (P1-2).
- The implementation prompt conflicted on: cloud LLM timing, backend persistence in
  "Phase 1.6", missing distributor/opportunity data sources, and a different definition
  of "Phase 2" (publish vs inference pipeline).
- Seller Center scraping and third-party marketplace scraping are **forbidden**
  ([`data-sources.md`](../architecture/data-sources.md) §Forbidden).
- TikTok Seller Center trend API exposure is **UNKNOWN** until P2-1 verification.

## Decision

- We will: insert **Phase 1.6** (Weeks 9–10) between Phase 1.5 and Phase 2 as the
  first **executable** New Seller Copilot task — **end-to-end**, not a standalone
  listing checklist. Success criteria: recommend (`list_products`) → approve → Path A
  or B → fill forms → execute (CSV/JSON export). Through P1.5 the same task stops at
  approve (no-op executor). Dual-path workflow uses **mock fixtures**, **rules-only**
  extraction/compliance/readiness scoring. No cloud LLM, no Postgres, no TikTok API in P1.6.
- We will: add **P2-7** (listing approval queue) and **P2-8** (Products API publish)
  to Phase 2 while keeping the existing P2-1…P2-6 inference pipeline.
- We will: use **curated mock catalogs** for Path B in P1.6; in P2 persist drafts in
  Postgres and use **Ollama** to assist matching against a **curated internal**
  distributor/product catalog (copy layer only — never ranks or selects).
- We will not: use cloud LLM (Claude) in Phase 1.6; scrape Seller Center or marketplace
  directories; wire third-party marketplace supplier APIs before Phase 3+.

## Why this architecture (the "because")

- **Speed (time-to-ship):** Reuses P1 mock-fixture patterns; avoids building backend
  services and LLM pipelines before P1.5 ML gate and P1.6 UX validation complete.
- **Cost:** No cloud LLM spend in P1.6; Ollama deferred to P2 alongside existing copy
  layer infrastructure.
- **Scalability:** ProductDraft/Distributor/Opportunity entities designed now; Postgres
  persistence and API routes land in P2 without rework.
- **Performance:** Deterministic compliance and readiness scoring are auditable and
  fast — suitable for interactive UI without async job infrastructure.
- **Reliability/Operability:** Rules-only P1.6 eliminates LLM failure modes during UX
  validation; approval queue (P2-7) gates publish blast radius.

## Rationale

Option C (mock fixtures + rules-only P1.6; live publish in P2) aligns with the UI-first
rescope, preserves the Phase 2 inference pipeline, and stages data sources without cloud
LLM or TikTok API dependencies in P1.6. See **Why this architecture** below for
speed, cost, scalability, performance, and operability trade-offs.

## Options considered

- **Option A: Full backend + Claude LLM in "Phase 1.6"** → Fast feature demo but
  violates EXECUTION Phase 1 contract, duplicates P2 Ollama, requires data sources that
  do not exist. **Rejected.**
- **Option B: Path A only in P1.6, defer Path B** → Lower scope but loses dual-persona
  validation. **Rejected** — mock catalogs are sufficient for Path B UX test.
- **Option C: Mock fixtures + rules-only P1.6; live publish in P2 slices** → Aligns
  with UI-first rescope, preserves inference pipeline, stages data sources. **Chosen.**

## Consequences

- **Positive:** Clear phase gates; E2E copilot → executor chain validated before P2;
  listing workflow entities documented; Path B testable without external supplier APIs;
  P2 publish is additive, not a rescope.
- **Negative:** P1.6 cannot validate URL/PDF LLM extraction quality until P2 Ollama;
  timeline extends by ~1 week (14-week horizon).
- **Follow-ups:** Add workflow entities to `canonical-entities.md`; implement P1.6
  slices; extend `target-v2.md` with listing publish path when P2-7/P2-8 begin.

## Rollout / Migration plan

1. **P1.6:** Client-side or mock-module listing generation; export from fixtures.
2. **P2:** Migrate fixtures → Postgres `product_drafts` table; wire approval queue;
   Products API publish behind P2-7 gate.
3. **P3+:** Optional third-party marketplace supplier API adapter behind feature flag.
