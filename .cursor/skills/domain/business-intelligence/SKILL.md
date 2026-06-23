---
name: business-intelligence
description: >-
  KPI framework design and display-grade dashboard specification for Juli-AI's
  seller app. Use when defining seller-facing KPIs, designing the Home tab
  analytics layer, setting RAG thresholds on tier signals, or specifying
  React/Next.js chart components — always within ADR-011 display-grade constraints.
  Not for SQL analysis (data-analyst), ML training (mle-agent), or schema
  migrations (analytics-engineer).
metadata:
  version: 1.0.0
  category: data-analytics
  updated: 2026-06-19
  tags: [bi, kpi, dashboard, display-grade, home-tab, seller, juli-ai]
---

# Purpose

Use when **designing or iterating on Juli-AI's seller-facing analytics layer**:
Home tab KPI definitions, display signal specifications, RAG threshold choices,
and React component layout — all under the display-grade constraint of ADR-011.

| Skill | Role |
|-------|------|
| **business-intelligence** (this) | KPI framework, display-grade signal design, Home tab layout, React chart specs |
| [`data-analyst`](../data-analyst/SKILL.md) | Ad-hoc SQL analysis, cohort/funnel queries, insight delivery |
| [`analytics-engineer`](../analytics-engineer/SKILL.md) | Supabase views, Alembic migrations, RLS, data transform layers |
| [`data-scientist`](../data-scientist.md) | T1–T8 algorithm vetting; display vs decision tier classification |

# Authority chain (read before designing)

1. [`docs/decisions/011-display-grade-analytics-layer.md`](../../../../docs/decisions/011-display-grade-analytics-layer.md) — **hard constraint**: every Home tab signal is display-grade (advisory only; never gates an action)
2. [`docs/ml_layer.md`](../../../../docs/ml_layer.md) — T1 forecast and T4 anomaly techniques backing Home KPIs
3. [`docs/system-design.md`](../../../../docs/system-design.md) § 3 ML models + § 5 UI — KPI→signal→component contracts
4. [`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md) — what signal data is available per phase
5. [`EXECUTION.md`](../../../../EXECUTION.md) — current phase gate; Phase 1 uses mock signals
6. `web/src/` — existing React/Next.js component conventions (check before specifying new charts)

# The display-grade rule (ADR-011)

> **Every Home tab KPI is advisory only.** A display-grade signal informs the seller; it does not execute, approve, or block any action.

Violation examples:
- ❌ "Show a warning that auto-pauses the ad campaign when ROAS drops below threshold."
- ❌ "Flag an order as high-risk and hold it for review based on the anomaly score."
- ✅ "Show a ⚠ advisory badge when the ROAS trend is below the seller's 30-day average."
- ✅ "Display a 'risk signal' label; the seller decides whether to review the order."

If a signal needs to gate an action → it is decision-grade → it requires
a Product sign-off (#142) and an ADR amendment before implementation.

# KPI definition template

Fill for every new Home tab metric before implementing any chart component:

```yaml
kpi:
  name: "Weekly Order Velocity"
  owner: "Product"
  display_surface: "Home tab — KPI card"
  technique: "T1 ETS forecast or naive-seasonal fallback"          # from ml_layer.md
  tier: "display-grade"                                            # NEVER decision-grade without ADR
  signal_output: "tier + delta"                                    # what the UI receives
  formula: "orders this week vs 4-week rolling average (% delta)"
  presentation:
    value: "Δ +12% WoW"                                           # relative, not raw count if sensitive
    badge: "up | flat | down"
    rag:
      green: "delta >= +5%"
      yellow: "delta between -5% and +5%"
      red: "delta < -5%"
  data_source: "orders table (Phase 2.5) | backtest fixture (Phase 1–2.0)"
  phase_available: "P1 (mock), P2.0 (synthetic), P2.5 (live)"
  caveats:
    - "Does not adjust for promotions or platform outages."
    - "Seasonality correction requires ≥2 weekly cycles of history."
```

# Home tab KPI catalog

These are the approved display-grade signals from `ml_layer.md` and `system-design.md`.
Do not add new KPIs without a new entry here and alignment with ADR-011.

| KPI | Technique | Signal output | Phase available |
|-----|-----------|---------------|-----------------|
| Order velocity forecast | T1 ETS / Holt-Winters | Trend + delta tier | P2.0 (backtest), P2.5 (live) |
| Revenue trend signal | T1 (shared forecaster) | Up/flat/down badge + Δ tier | P2.0+ |
| ROAS advisory | T2 RandomForest + T4 EWMA | Action label (scale/cut/hold) + anomaly flag | P2.0+ |
| Return-risk flag | T6 (advisory mode only) | Risk tier (low/medium/high) + reason label | P2.0+ |
| Seller lifecycle signal | T8 classifier | Stage label (new/leakage/growth) | P2.0+ |
| Ad spend anomaly | T4 EWMA/z-score | Anomaly badge + severity | P2.0+ |
| SLA countdown | T5 deadline rule | Urgency tier (ok/warn/critical) | P1+ |
| Livestream score | Intelligence heuristics (σ-deviation) | Engagement tier + anomaly flag | P1+ |
| SKU depletion risk | Intelligence forecasting (linear) | Risk level (ok/low-stock/critical) | P1+ |

# RAG threshold design

Define thresholds in terms of **percentage deltas or tier transitions** — never raw
financial values. RAG colors per brand convention:

| Color | Hex | Meaning |
|-------|-----|---------|
| Green | `#16A34A` | On target or improving |
| Yellow | `#D97706` | Caution; within acceptable range |
| Red | `#DC2626` | Needs attention |
| Gray | `#6B7280` | No data or phase unavailable |

```typescript
// Threshold pattern for React signal components
type RagStatus = "green" | "yellow" | "red" | "gray";

function getOrderVelocityRag(deltaWoW: number | null): RagStatus {
  if (deltaWoW === null) return "gray";
  if (deltaWoW >= 5) return "green";
  if (deltaWoW >= -5) return "yellow";
  return "red";
}
```

# Dashboard layout principles

**Home tab visual hierarchy (top → bottom):**

```
+--------------------------------------------------+
| SELLER STAGE BADGE   |  SLA COUNTDOWN CARD        |
+--------------------------------------------------+
| ORDER VELOCITY CARD  |  REVENUE TREND CARD        |  ← Summary KPI cards
+--------------------------------------------------+
| ROAS ADVISORY CARD   |  RETURN RISK FLAG CARD     |  ← Risk/opportunity signals
+--------------------------------------------------+
| LIVESTREAM SCORE     |  SKU DEPLETION RISKS        |  ← Intelligence signals
+--------------------------------------------------+
```

Rules:
1. Summary-to-detail flow: KPI cards at top, detail signals below.
2. Maximum 3 signals visible without scroll on mobile.
3. Every signal card includes: value/tier, trend badge, and a one-line explanation
   string (never a raw financial number in the explanation).
4. Gray/skeleton state for Phase 1 mock signals — never show fabricated numbers.
5. Tapping any signal opens a detail sheet — advisory copy only, no execute buttons.

# Signal-to-component contract

Each backend signal must follow this JSON shape before the UI component renders it:

```typescript
interface DisplaySignal {
  id: string;                  // e.g. "order_velocity_weekly"
  label: string;               // e.g. "Order Velocity"
  value: string;               // e.g. "Δ +12% WoW" — never raw financial value
  tier: "high" | "medium" | "low" | "unknown";
  rag: "green" | "yellow" | "red" | "gray";
  badge?: "up" | "flat" | "down" | "anomaly" | "risk";
  explanation: string;         // e.g. "Orders trending above your 4-week average"
  phase_available: boolean;    // false → show skeleton
  last_updated_at: string;     // ISO timestamp
}
```

The LLM copy layer (Phase 2) rewrites `explanation` strings from structured signal JSON —
it never changes `tier`, `rag`, or `badge` values. See `mle-agent.md` §Copy layer boundary.

# Reporting and alerting patterns

## Scheduled digest (Phase 2+)

```yaml
digest:
  name: "Weekly Seller Performance Digest"
  schedule: "0 9 * * MON"           # 09:00 UTC Mondays (after 08:00 batch)
  channel: "in-app notification"
  content:
    - order_velocity_weekly
    - roas_advisory
    - return_risk_flag
  format: "tier + delta only"       # never raw values in notification payload
```

## Anomaly alert threshold (T4)

```yaml
alert:
  signal: ad_spend_anomaly
  condition: "z_score > 2.0"        # T4 EWMA rolling z-score
  severity: warning                  # display-grade advisory only
  message: "Ad spend pattern differs from your 30-day baseline."
  action: null                       # NO auto-action; seller decides
```

# Self-service BI maturity for Juli-AI sellers

| Level | What the seller can do in the app |
|-------|-----------------------------------|
| 1 — Consumer | View Home tab KPI cards, tap for detail sheets |
| 2 — Explorer | Filter signals by date range, compare to previous period |
| 3 — Builder | (Phase 3) Configure custom alert thresholds on display signals |

# Governance

- All KPI definitions live in this skill file and are reviewed when ADR-011 is amended.
- RAG thresholds are product decisions — document in the KPI catalog, not in code comments.
- New KPIs must be classified in the `ml_layer.md` T1–T8 catalog before component work begins.
- Row-level security for multi-tenant seller data is enforced at the Supabase layer
  (see `analytics-engineer` skill) — BI components must not apply their own seller filters.

# Integration points

- **Data Analyst** — Complex ad-hoc queries that discover new patterns graduate into
  repeatable KPI signals via this skill.
- **Data Scientist** — Technique selection for each KPI signal is gated by `data-scientist`
  vetting (T1–T8). BI does not choose algorithms.
- **MLE Agent** — Signal JSON produced by ML suites is the input to every BI card.
  Copy rewrites happen in the copy layer, not in BI component logic.
- **Analytics Engineer** — Supabase views that back each signal are owned by the
  analytics-engineer skill. Schema changes require BI component updates.
- **UI/UX** — Load [`standalone/ui-ux-design`](../../standalone/ui-ux-design/SKILL.md)
  for pixel-level component implementation after signal contracts are defined here.

# Success criteria

- Every Home tab KPI has an entry in the catalog above with tier, technique, and phase gate.
- All signal outputs use tier/delta language — no raw financial values in component props or notification payloads.
- RAG thresholds are documented in the KPI template before any frontend implementation.
- New display signals pass ADR-011 classification (advisory only) before entering sprint.
- Every signal card has a gray/skeleton state for phases where data is unavailable.

# Scope & limitations

**In scope:** KPI framework design, display-grade signal specification, Home tab layout,
RAG threshold decisions, signal-to-component contracts, scheduled digest patterns.

**Out of scope:** SQL queries and data profiling (data-analyst), ML training and artifact
management (mle-agent), schema migrations or RLS (analytics-engineer), algorithm
selection (data-scientist), pixel-level component implementation (ui-ux-design skill).

**Limitations:** Phase 1 signals are mock/fixture only — do not commit to exact threshold
values until Phase 2.0 backtest data is available. LLM copy-layer rewrite requires Ollama
to be running (Phase 2); Phase 1 uses hardcoded explanation strings.
