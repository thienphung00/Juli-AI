# Handoff: Demo UI fix + CDP Analytics card set (Architect grill)

**Date:** 2026-07-30  
**Audience:** Fresh agent window — run **`to-issues`** next (when user approves).  
**PRD issue:** [#600](https://github.com/thienphung00/Juli-AI/issues/600) — Demo UI fix: CDP-honest Analytics cards and Decision automation UX  
**Skill sequence:** `focus` → **`to-prd`** ✓ → `to-issues` (when user approves).  
**Canonical docs:** [CONTEXT.md](../../CONTEXT.md), [ADR-049](../adr/049-demo-analytics-main-kpi-override.md), [ADR-048](../adr/048-cdp-webhook-first-spine-dual-credential.md), [ADR-046](../adr/046-cdp-medallion-physical-model.md) (3.5-A physical model).

---

## Problem

Public **`apps/demo`** (Mock mode, Fujiwa **`production_read`**, CDP envelopes) still
behaves like Phase 2.6 mock IA in places: Analytics Main KPI selector follows
ADR-023 placeholders many of which cannot be envelope-backed; trust copy exposes
backend/fixture language; Decisions automation UX shows confidence, silent prefills,
and a you-vs-Juli execution checklist that mis-set seller expectations; **`/decisions`**
can hang on **`Đang tải…`** (including highlight deep links); contextual **Juli
assistance** (left bar) renders format errors on Decisions and Analytics.

Sellers evaluating the Demo need a CDP-honest Analytics hero set, trustworthy insight
copy, and a Decision approve flow that feels like **Juli does the work** — without
OAuth, real Partner writes, or confidence scores on cards.

---

## Two-track delivery (Q6 — do not merge)

Founder preference: **keep Backend/CDP and Demo UI fix as separate tracks** — UI polish
does not reorder CDP spine priorities.

| Track | Scope | Near-term |
|-------|-------|-----------|
| **Track A — Backend / CDP** | Continuous CDP spine ([ADR-048](../adr/048-cdp-webhook-first-spine-dual-credential.md)); physical model ([ADR-046](../adr/046-cdp-medallion-physical-model.md) — **3.5-A / #598**) | **Now:** shop update → ETL → compute → **KPI envelope → Demo Analytics** (`gold.kpi_envelopes`). **Next slice:** same compute trigger → rules scoring → Decision/Action Cards (emission budget; Demo dry-run). Rules → ML later — **do not block Analytics on Decisions wire.** |
| **Track B — Demo UI fix** | `apps/demo` UX and seller-surface contracts | Analytics Main KPI set (ADR-049), trust copy, Decision automation UX, must-fix `/decisions` load + contextual assistance bugs. Consumes envelopes from Track A; Decision **feed freshness** depends on Track A Decisions slice — UI may ship UX contracts ahead of that wire. |

---

## Users

| User | Need |
|------|------|
| **Prospective seller (visitor)** | See real masked KPIs that reflect what Juli can measure today; understand trends without API jargon; try Decisions safely (dry-run). |
| **Product / GTM** | Demo proves webhook-first CDP + Decision loop for sales and Phase 2.10 exit. |
| **Implementer (Demo UI + envelope consumers)** | Locked KPI keys, copy rules, and UX contracts aligned with `analytics_backfill` → envelope → Demo read API. |

---

## Decisions locked (do not re-ask)

### Analytics Main KPI set — Option B′ ([ADR-049](../adr/049-demo-analytics-main-kpi-override.md))

Demo Analytics: **one hero + four selector cards** (**exactly five KPIs**; no sixth card) from CDP
envelopes (upgrade path: `analytics_backfill` → transform/compute → envelope → public Demo
read API).

| # | KPI | Source |
|---|-----|--------|
| 1 | GMV (TikTok) | A-36 |
| 2 | AOV | A-36 GMV ÷ orders |
| 3 | CTOR (click→đơn) | A-34 `click_order_rate`, GMV-weighted |
| 4 | LIVE hours (`live_hours`) | A-28 — **not** GMV LIVE; **not** `avg_watch_duration` (Partner gap) |
| 5 | Cancellation rate | A-7 + webhook #11 |

**Removed from B′ (2026-07-30 catalog amendment):** Bestselling (A-38/A-39) — marketplace/
platform bestselling ≠ merchant shop KPIs. Ops may still stop wasted A-38/A-39 calls; that is
not a Demo KPI requirement.

**Drop from Demo selector** until envelope-backed (no empty ADR-023 placeholders):
SPS, ROAS, CSAT, inventory turnover, fulfillment accuracy, Bestselling.

### Analytics trust copy (Q3)

- Insight chain on **every** card: what changed → risk/opportunity → action; **prioritize negative/downtrend** cards in ordering/emphasis where product rules allow.
- **Seller-language** provenance (no API names, no “fixture” in UI).
- **Relative sync freshness** + live indicator from envelope **`computed_at`**.
- **One consistent demo-data timestamp** across Home and Analytics.

### Decisions automation UX (Q4)

| Area | Lock |
|------|------|
| Suggest | Glow + **`Gợi ý bởi Juli`**; **no silent prefill** |
| Edit | Inputs **editable before approve** |
| Confidence | **Not visible** on seller cards (reconciles **Seller-surface copy** — no **Độ tin cậy**) |
| Confirm | **Juli handles all work** after approve — not a you-vs-Juli split checklist |
| Policy | Keep **TikTok Shop policy checked** badge |
| Safety | Cancel/rollback **always visible**; expected duration **5–10 min** |
| In Progress | **ChatGPT-style progress cards** (not status table); **mode strip** separates confirm vs running |
| Execution | **Demo dry-run only** — no real Partner writes |
| Auth | Sign-in/OAuth **still disabled** ([ADR-048](../adr/048-cdp-webhook-first-spine-dual-credential.md)) |

### Must-fix before ship (Q5)

- **`/decisions` load / `Đang tải…`** — including **highlight deep link**; verify in real browser before ship.
- **Left-bar (contextual Juli assistance) format errors** on Decisions and Analytics.

### Already locked elsewhere

- [ADR-046](046-cdp-medallion-physical-model.md): bronze/silver/gold/ops schemas, one-writer rule, serving vs ML gold fork — **3.5-A physical model** ([#598](https://github.com/thienphung00/Juli-AI/issues/598)); Track B reads serving gold only. **Q2 cutover:** schemas first, per-domain migrate (orders→silver, KPI→`gold.kpi_envelopes`); Demo stays green via gold/compat view; no long-term dual-write; bronze MVP = webhook + targeted fetch for Demo KPI domains only. **Q3:** flexible `payload.kpis` map (no per-KPI DB columns). **Q4:** one shop-scoped Shared Compute job per material trigger (bronze append → silver upsert → gold envelope write). **Q5:** Demo Main KPI catalog **locked at five** — no sixth card; Bestselling removed from B′.
- [ADR-048](048-cdp-webhook-first-spine-dual-credential.md): webhook-first CDP spine; OAuth/Sign-in deferred this release.
- Mock mode + Fujiwa **`production_read`** only; **`seller_connect`** future Phase 3.
- [ADR-023](023-four-destination-analytics-ownership.md) IA unchanged; authenticated dashboard Main KPI catalog unchanged until future ADR.

---

## Out of scope

- TikTok OAuth, Sign-up, Sign-in implementation or enabling the Demo mode toggle.
- Real Partner write APIs from public Demo (dry-run / local execution records only).
- Landing (`app-juli.com`) deploy.
- Reintroducing SPS, ROAS, CSAT, inventory turnover, or fulfillment accuracy in Demo selector without envelope backing.
- In Progress sub-tab **full redesign** beyond progress-card + mode-strip contract (Five-stage review flow remains; see CONTEXT **Five-stage decision review**).
- New GitHub issues or product code in this handoff step.

---

## Acceptance themes (for PRD / test planning)

1. **Analytics selector** shows exactly five Demo Main KPIs; dropped ADR-023 metrics and Bestselling absent from selector; GMV/AOV/CTOR/LIVE hours/cancellation map to envelope fields with honest unavailable states.
2. **Trust copy** passes seller-language guardrails; insight chain present; freshness from `computed_at`; shared timestamp with Home.
3. **Recommendations → approve** uses suggestion glow, no confidence UI, editable inputs, Juli-handles-all confirm, policy badge, visible cancel/rollback and 5–10 min expectation.
4. **In Progress** uses progress cards + mode strip (confirm vs running).
5. **`/decisions`** loads reliably; deep-link highlight works; browser-verified.
6. **Contextual assistance** renders without format errors on Decisions and Analytics.
7. **Dry-run** only — no live Partner writes; Sign-in control disabled.

---

## Open TBDs (minimal)

| TBD | Notes |
|-----|-------|
| Default Analytics hero | Grill implies GMV-first; confirm in PRD if URL default remains `/analytics/...` key. |
| Negative-card prioritization rule | Locked as product intent; exact sort/weight algorithm left to implementation PRD. |

---

## Glossary / ADR updates (this session)

- [CONTEXT.md](../../CONTEXT.md): **Demo Main KPI set**, **CTOR**, **Analytics trust copy**, Decision UX terms, **Main KPI** cross-ref ADR-023 vs Demo override.
- [ADR-049](../adr/049-demo-analytics-main-kpi-override.md): Demo-only Main KPI override (three ADR gates met).
- [ADR-046](../adr/046-cdp-medallion-physical-model.md): medallion physical model Q1–Q5 locked (2026-07-30); catalog count Q5 = exactly five KPIs.

---

## Suggested PRD title (for `to-prd`)

**Demo UI fix — CDP-honest Analytics cards and Decision automation UX**

---

## Files to read before PRD

1. This handoff  
2. [CONTEXT.md](../../CONTEXT.md) (Frontend surfaces + Scoring terms)  
3. [ADR-049](../adr/049-demo-analytics-main-kpi-override.md), [ADR-048](../adr/048-cdp-webhook-first-spine-dual-credential.md)  
4. [`docs/product/design/Screens/analytics.md`](../product/design/Screens/analytics.md) (will need post-PRD design sync)  
5. `apps/demo` Decisions + Analytics routes and envelope consumers (explore for module boundaries only — no code in grill doc)
