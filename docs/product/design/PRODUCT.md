# Juli AI — Product Design Baseline

> Context for OpenDesign and design polish. **Authority:** [`EXECUTION.md`](../../EXECUTION.md) >
> [`docs/architecture/system-design.md`](../architecture/system-design.md) > this file. Code reality in
> [`web/MODULE.md`](../../web/MODULE.md).

## One-liner

Juli AI is a **Decision Copilot** for TikTok Shop sellers — an AI Operations System that
analyzes shop data, surfaces opportunities and risks, recommends validated high-impact
workflows with impact estimates and reasoning, collects user decisions and inputs, and
executes **only after explicit approval**.

## What we build

| Pillar | Description |
|--------|-------------|
| **Probation completion** | Help new shops graduate (SPS, AHR, violations) |
| **Revenue growth** | ROAS scaling, product scaling, budget optimization |
| **Loss prevention** | Refund spikes, stockouts, fulfillment failures |

**We do not build:** generic analytics dashboards, CRM, inventory/finance/settlement
management software, or creator↔shop matching (Phase 3+).

## Target users

| User | Workspace | pre-MVP status |
|------|-----------|----------------|
| **TikTok Shop seller** | `seller` (light theme) | Primary — full Decision Copilot IA |
| **Affiliate / creator** | `affiliate` (dark theme) | Out-of-scope placeholder shell |

Sellers operate in **Vietnamese** (`vi-VN`), VND currency (₫), ICT timezone. The product
assumes mobile-first, single-thumb operation with desktop dashboard expansion on Home.

## Shop profiles & copilot surfaces

Exactly two shop profiles drive which workflows surface:

| Profile | Copilot surface | Validated workflows |
|---------|-----------------|---------------------|
| **NEW_SHOP** | New Seller Copilot | Add New Product Listings (NPL); Minimize Violations |
| **MID_LARGE_SHOP** | Growth Copilot | Budget Optimization; Product Scaling |
| **MID_LARGE_SHOP** | Revenue Leakage (loss prevention) | Refund Spike Detection; Stockout Prevention |

**Six workflows total** — no expansion without explicit product evaluation
([ADR-007](../adr/013-operations-pipeline-spine.md)).

Profile rules:

- **NEW_SHOP** — shop in probation or not yet graduated; focus on SPS + AHR.
- **MID_LARGE_SHOP** — graduated, 90+ days active, or ≥2 GMV metrics tracked; focus on
  growth + loss prevention.

Do not recommend growth/loss-prevention workflows to NEW_SHOP, or probation workflows to
MID_LARGE_SHOP.

## Primary UI object: Decision

A **Decision** is the seller-facing envelope wrapping one validated `workflow_id` plus:

| Field | Meaning |
|-------|---------|
| `title` | Workflow name in Vietnamese |
| `estimated_impact` | Metric + value (e.g. revenue gain, loss prevented) |
| `confidence` | `high` \| `medium` \| `low` |
| `reasoning_summary` | Why Juli recommends this now |
| `required_inputs` | Budget limits, product selection, risk tolerance, etc. |
| `status` | `recommended` \| `needs_input` \| `executing` \| `completed` |

Sellers **review and approve Decisions** on the Decisions tab — not on Home.

_Avoid:_ treating "AI Action Card" or "recommendation card" as separate domain concepts;
they are renderings of a Decision ([`CONTEXT.md`](../../CONTEXT.md)).

## Application information architecture

Three main tabs answer three questions ([ADR-007](../adr/014-decision-copilot-app-structure-and-journey.md)):

| Tab | Route | User question | Primary mode |
|-----|-------|---------------|--------------|
| **Trang chủ** (Home) | `/` | What is happening? | Read-only visibility |
| **Quyết định** (Decisions) | `/decisions` | What should I do? | Review, approve, configure |
| **Juli** (AI Chat) | `/ai-chat` | Help me understand and complete this. | Contextual Q&A |

### Home (implemented — chart-first)

Current shipped layout (`web/MODULE.md`):

1. **Shop info** — name + status in header/sidebar (`ShopInfoHeader`, `ShopInfoCard`)
2. **Báo cáo hôm nay** — tabbed metric dashboard with Recharts sparklines
3. **Shop Health** — SPS/AHR score bars with threshold ticks

Home is **read-only**: no approve/dismiss, no task queue, no Tiến độ gần đây, no persona
copilot panels. Metric tiles expand **Gợi ý từ Juli** and link to Decisions.

> **ADR-007 delta:** the accepted ADR also described a top-3 Recommended Decisions Preview
> on Home. That preview is **not** on the current Home surface; decisions live entirely on
> `/decisions`. OpenDesign should treat Decisions as the action hub.

### Decisions

Three sub-tabs:

| Sub-tab | Purpose |
|---------|---------|
| **Recommended** | Full ranked `ClarityCard` list + approval gate |
| **In Progress** | Approved decisions: `needs_input`, `executing`, `completed` |
| **Workflow Templates** | Advanced thresholds and automation (demoted complexity) |

Decision detail: guided 5-step flow at `/decisions/[decisionId]` — why → analytics →
inputs → preview → approve.

### Juli AI Chat

Contextual assistant connected to active/recent decisions. Suggested prompts are
mode-aware. pre-MVP uses mock replies; avoids generic chatbot behavior.

## Cross-screen journey (RRAA)

**Reward → Reason → Action → Anticipation** links Home metrics to Decisions cards
without exposing stage labels in UI:

1. Seller explores a metric on Home (chart + delta).
2. Expands **Gợi ý từ Juli** or taps estimated bar segment → `/decisions?highlight=<workflow_id>`.
3. Reviews `ClarityCard` on Decisions; after Anticipation, **Xem trên Trang chủ →**
   returns to `/?highlight=<domain>:<metric>` with tab switch + chart pulse.

Registry: `web/src/lib/operations/journey-loop.ts`.

## Display-grade analytics (visual target)

Phase 2+ KPI rendering follows [`docs/ml/visual_layer.md`](../ml/visual_layer.md): visualize ML
output (forecast bands, rankings, gauges), not raw numbers alone. Every KPI shows a
one-line signal — **What changed → Risk/Opportunity → Action** — then links to a
workflow. Home remains advisory; execution stays on Decisions
([ADR-005](../adr/011-display-grade-analytics-layer.md)).

## Backend pipeline (design-relevant stages)

```
Data → Health Check → Profile Classification → Recommendation & Ranking
  → Reasoning (copy layer) → User Approval → Copilot Execution → Outcome Tracking
```

pre-MVP uses mock envelopes; Phase 2 MVP Milestone B swaps in live TikTok data and batch inference
without changing UI object shapes.

## Platforms

| Surface | Stack | Design scope |
|---------|-------|--------------|
| **Web** | Next.js 14, Tailwind, Recharts | Primary — this design baseline |
| **iOS** | SwiftUI (`ios/`) | Affiliate daily-loop shell; seller parity is future work |

## Demo & persona model (Phase 1)

`DemoPersonaProvider` persists a demo seller persona for mock data. Persona switcher is
**not** on Home in the chart-first IA; personas still drive which mock workflows and
metrics load behind the scenes.

## Non-goals for design polish

- Do not add a fourth main tab.
- Do not surface workflow templates as the default seller path.
- Do not allow approval or execution from Home.
- Do not invent decisions outside the six validated workflows.
- Do not expose raw seller financial PII in copy, tooltips, or LLM-facing strings —
  use computed signals (deltas, trend direction, tier labels) per core safety rules.

## Canonical references

| Doc | Use |
|-----|-----|
| [`EXECUTION.md`](../../EXECUTION.md) | Phase gates, workflow catalog |
| [`docs/architecture/system-design.md`](../architecture/system-design.md) | Pipeline envelopes, health indicators |
| [`docs/ml/visual_layer.md`](../ml/visual_layer.md) | KPI → chart type → workflow mapping |
| [`web/MODULE.md`](../../web/MODULE.md) | Routes, components, invariants |
| [`CONTEXT.md`](../../CONTEXT.md) | Ubiquitous language |
| [ADR-007](../adr/015-design-system-token-foundation.md) | Tokens, motion, states |
| [ADR-007](../adr/014-decision-copilot-app-structure-and-journey.md) | 3-tab IA, Decision object |
| [ADR-005](../adr/011-display-grade-analytics-layer.md) | ML visual layer |
