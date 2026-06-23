# ADR 028: Decision Copilot App Structure (3-Tab IA)

## Status
Accepted

## Context

- Product refined Juli positioning: a **Decision Copilot**, not an autonomous
  operator. The AI analyzes shop data, surfaces opportunities and risks, estimates
  impact, explains reasoning, collects user decisions and inputs, and executes
  workflows **only after explicit approval**.
- Phase 1.8 ([ADR-026](026-operations-system-orchestration.md)) delivered an
  operations pipeline spine (classify → health → rank → reasoning → approval →
  execution → outcomes) but mounted **all** seller actions on the Home tab:
  `OperationsPipelineShell` combines Shop Health hero, full ranked Clarity Cards,
  approval gate, and outcome views on `/`.
- Bottom navigation currently has **two** tabs (Home + Juli Chat — issue #123).
  There is no dedicated surface for reviewing, approving, or tracking decisions.
- Sellers need clear mental models per screen:
  - Home → "What is happening?"
  - Decisions → "What should I do?"
  - Juli Chat → "Help me understand and complete this."
- The validated **workflow catalog** (six workflows) and pipeline envelopes from
  ADR-026 remain authoritative for execution; this ADR changes **information
  architecture and primary UI object naming**, not backend pipeline stages.

## Decision

- We will: adopt exactly **three** main application tabs for the seller workspace:

  | Tab | Route | User question | Primary actions |
  |-----|-------|---------------|-----------------|
  | **Home** | `/` | What is happening? | Read-only visibility |
  | **Decisions** | `/decisions` | What should I do? | Review, approve, configure |
  | **Juli AI Chat** | `/ai-chat` | Help me understand and complete this. | Contextual Q&A |

- We will: introduce **Decision** as the seller-facing primary object. A Decision
  is a ranked recommendation envelope wrapping one **validated workflow**
  (`workflow_id` from ADR-026) plus reasoning, required user inputs, status, and
  impact estimate. Workflows remain execution templates; Decisions are what
  sellers review and approve.
- We will: structure **Home** as three sections (read-only — **no approvals or
  workflow execution** on Home):

  1. **Shop Status (hero)** — Shop Health Score, Account Health Rating (AHR/VP
     when available), platform alerts/messages/violations. Answers: *"How is my
     shop visibility on the platform right now?"*
  2. **Today's Report** — one container with animated domain switching across
     five business domains: Revenue Growth, Revenue Protection, Product Listings,
     Advertising, Refunds. Each card: current status, trend vs prior period,
     metric deltas.
  3. **Recommended Decisions Preview** — top **3** highest-impact decisions only;
     each shows title, estimated impact, revenue gain or loss-prevention value;
     CTA **"View All Decisions"** → `/decisions`. No approve/dismiss on Home.

- We will: structure **Decisions** with three sub-tabs:

  1. **Recommended** — full ranked decision cards (title, impact, confidence,
     AI reasoning, required user inputs, status, Review button). Primary object =
     Decision, not Workflow.
  2. **In Progress** — approved decisions with statuses: `needs_input`,
     `executing`, `completed`.
  3. **Workflow Templates** — advanced settings only (thresholds, automation
     rules, workflow configuration). Not the primary seller experience; hidden
     complexity by default.

- We will: implement a **Decision detail flow** (opened from Review on a card)
  as a guided 5-step sequence:

  1. Explain why the recommendation exists
  2. Show supporting analytics
  3. Collect required user decisions (product selection, budget limits, campaign
     goals, risk tolerance, etc.)
  4. Show execution preview (expected revenue impact, loss prevention, confidence,
     potential risks)
  5. Approve and execute (routes to existing P1.6/P1.7 panels or no-op per ADR-026)

- We will: make **Juli AI Chat** contextual — connected to active/recent decisions,
  capable of explaining recommendations, comparing products, clarifying metrics,
  assisting decision completion, and answering platform questions. Avoid generic
  assistant behavior.
- We will: enforce design principles: mobile-first, minimal cognitive load,
  recommendation-first, workflow complexity hidden by default, human approval
  required before execution, clear business impact on every recommendation, every
  recommendation explains why it exists.
- We will: use a **white seller canvas** (`#FFFFFF`) for page background, header,
  and muted surfaces — not the pink-tint `#FEF5F6` from ADR-027. Brand pink
  `#F86BA5` remains accent-only (health progress, primary CTAs).
- We will: implement as **Phase 1.8 slice P1.8-9** (product label *Phase 1.8.5 —
  Update app structure*). Depends on P1.8-3 (health) and P1.8-4 (ranking);
  refactors placement of P1.8-5…P1.8-7 components from Home into Decisions.
- We will not: add a fourth main tab; surface workflow templates as the default
  path; allow approval or execution from Home; invent decisions outside the six
  validated workflows; change pipeline stage envelopes from ADR-026.

## Why this architecture

- **Speed:** Reuses existing operations lib (`health-check`, `recommendations`,
  `reasoning`, `use-operations-approval`) and modal executors — primarily a route
  and component placement refactor plus Today's Report domain cards.
- **Cost:** No new backend, ML, or API work; mock data envelopes unchanged.
- **Scalability:** Decision detail flow and sub-tabs scale to Phase 2 live data
  without re-architecting navigation.
- **Performance:** Home stays lightweight (top-3 preview + domain summary); heavy
  approval UI loads only on Decisions.
- **Reliability/Operability:** Separating read (Home) from act (Decisions) reduces
  accidental approvals and matches human-in-the-loop product intent.

## Options considered

- **Option A: Keep single Home with full pipeline (status quo)** — Pros: already
  built. Cons: cognitive overload; approvals on landing page; no dedicated
  decision workspace; conflicts with Decision Copilot positioning.
- **Option B: 3-tab IA with Decision as primary object (chosen)** — Pros: clear
  user questions per screen; approval gated to Decisions; templates demoted.
  Cons: refactor of `OperationsPipelineShell`; new routes and nav tab.
- **Option C: Per-copilot tabs (New Seller / Growth / Leakage)** — Pros: familiar
  from Phase 1. Cons: contradicts unified operations spine; fragments decisions.

## Consequences

- **Positive:** Aligns UI with Decision Copilot positioning; Home answers status
  questions without action pressure; Decisions becomes the approval hub; Chat
  gains decision context; workflow templates accessible but not prominent.
- **Negative:** Short-term refactor of seller home and bottom nav; tests and
  screenshots need re-baseline; `/recommendations` legacy redirect should target
  `/decisions` not `/`.
- **Follow-ups:** P1.8-9 implementation slices (nav, Home sections, Decisions
  sub-tabs, decision detail flow, chat context wiring); update `web/MODULE.md`
  routes; re-baseline `screenshots/` after IA lands.

## Rollout / Migration plan

1. Add `/decisions` route and third bottom-nav tab (Vietnamese label TBD in PRD —
   e.g. *Quyết định*).
2. Split `OperationsPipelineShell`: Home gets hero + Today's Report + top-3
   preview; Decisions gets full list + approval gate + In Progress + Templates.
3. Implement decision detail as drawer or full-page stepper on `/decisions/[id]`.
4. Wire Juli Chat suggested prompts from active decision context.
5. Update legacy redirects (`/recommendations` → `/decisions`).
6. Re-baseline visual snapshots; verify Home has zero approve CTAs.
