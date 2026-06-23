# ADR 014: Decision Copilot app structure and user journey

## Status
Accepted

**Pipeline spine:** [ADR-013](013-operations-pipeline-spine.md).

## Context

Juli is a **Decision Copilot** — analyzes shop data, surfaces opportunities and risks,
estimates impact, explains reasoning, collects user decisions, and executes workflows
**only after explicit approval**.

## Decision

### Three application tabs

| Tab | Route | User question | Primary actions |
|-----|-------|---------------|-----------------|
| **Home** | `/` | What is happening? | Read-only visibility |
| **Decisions** | `/decisions` | What should I do? | Review, approve, configure |
| **Juli AI Chat** | `/ai-chat` | Help me understand? | Contextual Q&A |

### Home (read-only)

1. **Shop Status** — health score, AHR/VP when available, platform alerts.
2. **Today's Report** — domain cards: Revenue Growth, Revenue Protection, Listings, Ads, Refunds.
3. **Recommended Decisions Preview** — top 3 highest-impact; CTA to `/decisions`. No approve on Home.

### Decisions

- **Recommended** — full ranked decision cards with reasoning and Review button.
- **In Progress** — approved decisions: `needs_input`, `executing`, `completed`.
- **Workflow Templates** — advanced thresholds and automation rules.

### Decision detail flow (5 steps)

1. Explain why the recommendation exists
2. Show supporting analytics
3. Collect required user inputs
4. Show execution preview (impact, confidence, risks)
5. Approve and execute

### RRAA user journey loop

Chart-first Home ↔ Decisions closed navigation:

- Home metric charts + Juli two-step suggestion
- Decisions RRAA card chrome with inbound `?highlight=` deep links
- **Return path:** "Xem trên Trang chủ →" from Decisions back to highlighted Home metric
- Home gate: no preview/Tiến độ/Reward labels on chart-first Home

### Primary object

**Decision** wraps one workflow from the execution-layer taxonomy plus reasoning,
required inputs, status, and impact estimate. Workflows are execution templates;
Decisions are what sellers review and approve.

## Rationale

Consolidates seller-money rescope: keeps enforcement aligned with TikTok VN policy while routing alerts through the operations pipeline instead of a standalone service.

## Consequences

- Seller canvas **white** (`#FFFFFF`); pink accent only ([ADR-015](015-design-system-token-foundation.md)).
- Juli Chat contextual to active/recent decisions — not generic chatbot.
