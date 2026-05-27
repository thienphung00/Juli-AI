---
name: discover
description: >-
  Turns vague ideas into implementable specifications by combining requirements
  gathering, system design, and documentation into a single discovery workflow.
  Use when starting a new feature, receiving a vague request, or needing to produce
  PRDs, technical specs, API contracts, or architecture docs before implementation
  begins.
---

# Blueprint

Transforms ambiguous user requests into complete, implementable specifications. This is the entry point of every workflow — nothing gets built without discovery.

## Workflow

```
User Idea → Clarifying Questions → Scope & Dependencies → Spec Generation → Context Docs → Handoff
```

## Step 1: Ask Clarifying Questions

Before producing any spec, gather enough to eliminate ambiguity:

1. **Business goals** — What outcome does this serve? Who benefits?
2. **Constraints** — Budget, timeline, compliance, model tier, team capacity
3. **Dependencies** — Which services are affected? Which APIs consumed/exposed?
4. **Data flow** — Where does data originate, transform, and persist?
5. **Failure modes** — What happens when things break? What's the blast radius?
6. **Approval gates** — Human-in-the-loop required? Who signs off?

Use the AskQuestion tool for structured gathering when available.

### Domain-Specific Probes

**AI features:**
- Which model tier? Real-time or batch?
- Accuracy requirements? Evaluation criteria?
- Fallback on AI failure? Confidence thresholds?
- Cost budget per request/day?

**Integrations** (TikTok Shop, GrabFood, etc.):
- Webhook or polling? Rate limits?
- Data mapping to unified schema?
- Retry/backoff strategy? Idempotency keys?

**Data features:**
- Forecast horizon? Aggregation level?
- Historical data requirements? Staleness tolerance?
- Privacy/PII implications?

## Step 2: Identify Scope

Map the feature to:
- Affected architectural layers (see [architecture-context.md](architecture-context.md))
- Existing services that need modification vs. new services required
- Database schema changes and migration strategy
- API surface changes (breaking vs. additive)
- Cross-cutting concerns (auth, caching, monitoring)

## Step 3: Generate Specification Docs

Produce docs in `/context/features/<feature-name>/`:

| Document | Purpose | Required? |
|----------|---------|-----------|
| `PRD.md` | Business requirements, success criteria, acceptance tests | Always |
| `architecture.md` | System design, sequence diagrams, component interactions | Always |
| `api-contracts.md` | Endpoint specs, request/response schemas, error codes | If API changes |
| `db-changes.md` | Schema migrations, indexes, data model changes | If DB changes |
| `edge-cases.md` | Failure modes, race conditions, boundary values | Always |
| `ai-eval-plan.md` | Benchmarks, test datasets, scoring rubrics | If AI feature |

### PRD Template

```markdown
# Feature: [Name]

## Problem Statement
[What problem does this solve? Why now?]

## Success Criteria
- [ ] Measurable outcome 1
- [ ] Measurable outcome 2

## User Stories
- As a [role], I want [action] so that [outcome]

## Constraints
- Budget: [token/infra budget]
- Timeline: [deadline]
- Compliance: [requirements]

## Acceptance Criteria
- Given [context], when [action], then [result]
```

### Architecture Template

```markdown
# Architecture: [Feature Name]

## Overview
[One paragraph summary]

## Components
| Component | Responsibility | Layer |
|-----------|---------------|-------|

## Sequence Diagram
[Mermaid sequence diagram]

## Data Flow
[Input] → [Transform] → [Store] → [Output]

## Failure Modes
| Failure | Impact | Mitigation |
|---------|--------|------------|
```

## Step 4: Validate Completeness

Before handing off to implementation, every item must be checked:

- [ ] All clarifying questions answered (no TBDs remaining)
- [ ] Dependencies identified and documented
- [ ] API contracts specify error responses, not just happy paths
- [ ] Edge cases enumerated with mitigation strategies
- [ ] Success criteria are measurable and testable
- [ ] AI eval plan exists (if AI feature)
- [ ] Security implications considered

## Output

The generated `/context/features/<feature-name>/` directory becomes shared context for all downstream agents (implementation, validation, delivery). The `focus` skill uses these docs to determine what context to load.

## Integration with Other Skills

| Downstream Skill | What It Uses from Blueprint |
|-----------------|---------------------------|
| `focus` | Feature docs to build context loading plan |
| `review` | Edge cases and API contracts for validation |
| `build-ai` | AI eval plan and model tier decisions |
| `ship` | Architecture docs for deployment planning |

## Additional Resources

- For architecture layer reference, see [architecture-context.md](architecture-context.md)
- For example discovery sessions, see [examples.md](examples.md)
