# Phase 1 Completed (Historical Summary)

> **Status:** Complete — exit gate passed 2026-06-19.  
> **Authority:** Historical reference only. Active work begins at [Phase 2 MVP](phase-2-mvp.md).

Phases 1.0 through 1.8 validated seller UX and workflow taxonomy on **mock data only** —
no TikTok API, no Postgres workflow persistence, no cloud LLM, no production ML inference.

| Track | Scope |
|-------|-------|
| **1.0** | Mock UX for workflow surfaces |
| **1.5 / 2.0** | Display-grade ML backtest prep (now Phase 2 MVP Milestone A) |
| **1.6** | Executable listing workflow on mock fixtures |
| **1.7** | Executable loss-prevention workflow on mock fixtures |
| **1.8** | Operations orchestration spine + design polish + 3-tab IA + RRAA loop |

---

## What shipped

| Track | Outcome |
|-------|---------|
| **Mock UX** | Workflow surfaces, approval flow, rules-based seller-stage detection, UX instrumentation |
| **Display-grade ML (offline)** | Backtest dataset, router classifier, return-fraud detector, ads regressor, serialized artifacts, feature specs |
| **Listing workflow** | Dual-path listing UI, rules-based draft generation, CSV/JSON export, shop-progress widget |
| **Loss-prevention workflow** | Four leakage task types, modal stepper, executor integration, PII guard |
| **Operations spine** | Classify → health → rank → reason → approve → route → track on mock fixtures |
| **Design & IA** | Token foundation (Seller light / Affiliate dark), 3-tab Decision Copilot (Home / Decisions / Juli Chat), RRAA Home ↔ Decisions loop |

---

## Mock-only constraints (intentional)

- No TikTok Partner API calls for seller workflow data
- No Postgres persistence for workflow sessions
- No Claude Haiku or other cloud LLM for copy
- No production batch inference or live executors
- Rules-only copy and deterministic fixtures throughout

---

## GitHub traceability

| Issue range | Work |
|-------------|------|
| #103–#123 | Phase 1.0 mock UI slices |
| #136–#143 | Display-grade ML backtest / artifact promotion |
| #153–#157 | Listing executable workflow |
| #164–#168 | Loss-prevention executable workflow |
| #174–#234 | Operations orchestration, design polish, 3-tab IA, RRAA loop |

---

## Retired framing

The following are **historical only** and must not appear in active docs:

- **3 Copilot surfaces** (New Seller / Growth / Revenue Leakage) — replaced by the layered Visual / ML / Execution model ([ADR-011](../decisions/011-display-grade-analytics-layer.md))
- **Closed "six validated workflows" catalog** — replaced by [`execution_layer.md`](../execution_layer.md) taxonomy
- **Phase 1.5 / 2.0 / 2.5 numbering** — collapsed into [Phase 2 MVP](phase-2-mvp.md)
