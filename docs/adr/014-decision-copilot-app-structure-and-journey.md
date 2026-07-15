# ADR 014: Decision Copilot app structure and user journey

## Status
Partially superseded by
[ADR-023](023-four-destination-analytics-ownership.md).

**Pipeline spine:** [ADR-013](013-operations-pipeline-spine.md).

The Decision object, explicit approval gate, and five-step decision-detail flow
remain accepted. The three-tab IA, Home composition, RRAA navigation, standalone
Juli Chat, and Workflow Templates placement are superseded.

## Context

Juli is a **Decision Copilot** — analyzes shop data, surfaces opportunities and risks,
estimates impact, explains reasoning, collects user decisions, and executes workflows
**only after explicit approval**.

## Decision

### Three application tabs

> **Superseded by ADR-023.** Juli now uses Home, Decisions, Analytics, and
> Settings; Juli assistance is contextual rather than a standalone tab.

| Tab | Route | User question | Primary actions |
|-----|-------|---------------|-----------------|
| **Home** | `/` | What is happening? | Read-only visibility |
| **Decisions** | `/decisions` | What should I do? | Review, approve, configure |
| **Juli AI Chat** | `/ai-chat` | Help me understand? | Contextual Q&A |

### Home (read-only)

> **Superseded by ADR-023.** Home is now a sparse launcher with exactly two
> prominent cards: Decisions and Analytics. Reporting belongs to Analytics.

1. **Shop Status** — health score, AHR/VP when available, platform alerts.
2. **Today's Report** — domain cards: Revenue Growth, Revenue Protection, Listings, Ads, Refunds.
3. **Recommended Decisions Preview** — top 3 highest-impact; CTA to `/decisions`. No approve on Home.

### Decisions

- **Recommended** — full ranked decision cards with reasoning and Review button.
- **In Progress** — approved decisions: `needs_input`, `executing`, `completed`.
- ~~**Workflow Templates** — advanced thresholds and automation rules.~~
  **Superseded by ADR-023:** templates and thresholds belong to Settings.

### Decision detail flow (5 steps)

1. Explain why the recommendation exists
2. Show supporting analytics
3. Collect required user inputs
4. Show execution preview (impact, confidence, risks)
5. Approve and execute

### RRAA user journey loop

> **Superseded by ADR-023.** Cross-destination evidence links now connect
> Analytics and Decisions; Home does not host metric charts.

The historical chart-first Home ↔ Decisions loop no longer defines product
behavior. Supporting metrics now deep-link between Analytics and Decisions,
while Home only launches those destinations.

### Primary object

**Decision** wraps one workflow from the execution-layer taxonomy plus reasoning,
required inputs, status, and impact estimate. Workflows are execution templates;
Decisions are what sellers review and approve.

## Rationale

Consolidates seller-money rescope: keeps enforcement aligned with TikTok VN policy while routing alerts through the operations pipeline instead of a standalone service.

## Consequences

- Seller canvas **white** (`#FFFFFF`); pink accent only ([ADR-015](015-design-system-token-foundation.md)).
- Juli Chat contextual to active/recent decisions — not generic chatbot.
