---
name: discover
description: >-
  Turn vague ideas into implementable specifications. Combines requirements gathering,
  system design, API design, and documentation into a single discovery workflow.
  Use when starting a new feature, receiving a vague request, or needing to produce
  PRDs, technical specs, API contracts, or architecture docs before implementation.
disable-model-invocation: true
---

# Solution Discovery

The first skill every workflow uses. Transforms ambiguous user requests into complete, implementable specifications.

## Workflow

```
User Idea → Clarifying Questions → Constraints & Dependencies → Spec Generation → Context Docs
```

## Step 1: Ask Clarifying Questions

Before producing any spec, gather:

1. **Business goals** - What outcome does this serve?
2. **Constraints** - Budget, timeline, compliance, model tier
3. **Dependencies** - Which services are affected? Which APIs consumed?
4. **Data flow** - Where does data originate, transform, and persist?
5. **Failure modes** - What happens when things break?
6. **Approval gates** - Human-in-the-loop required?

Use the AskQuestion tool for structured gathering when available.

### Domain-Specific Probes

For **AI features**:
- Which model tier? Real-time or batch?
- Accuracy requirements? Evaluation criteria?
- Fallback on AI failure?

For **integrations** (KiotViet, GrabFood, etc.):
- Webhook or polling? Rate limits?
- Data mapping to unified schema?
- Retry/backoff strategy?

For **data features**:
- Forecast horizon? Aggregation level?
- Historical data requirements?
- Staleness tolerance?

## Step 2: Identify Scope

Map the feature to:
- Affected architectural layers (see [architecture reference](architecture-context.md))
- Existing services that need modification
- New services or modules required
- Database schema changes
- API surface changes

## Step 3: Generate Specification Docs

Produce docs in `/context/features/<feature-name>/`:

| Document | Purpose |
|----------|---------|
| `PRD.md` | Business requirements, success criteria, acceptance tests |
| `architecture.md` | System design, sequence diagrams, component interactions |
| `api-contracts.md` | Endpoint specs, request/response schemas, error codes |
| `db-changes.md` | Schema migrations, indexes, data model changes |
| `edge-cases.md` | Failure modes, race conditions, boundary values |
| `ai-eval-plan.md` | (AI features only) Benchmarks, test datasets, scoring rubrics |

### PRD Template

```markdown
# Feature: [Name]

## Problem Statement
[What problem does this solve?]

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

Before handing off to implementation:

- [ ] All clarifying questions answered
- [ ] Dependencies identified and documented
- [ ] API contracts specify error responses
- [ ] Edge cases enumerated
- [ ] Success criteria are measurable
- [ ] AI eval plan exists (if AI feature)

## Output

The generated `/context/features/<feature-name>/` directory becomes shared context for all downstream agents (implementation, validation, delivery).

## Additional Resources

- For architecture layer reference, see [architecture-context.md](architecture-context.md)
- For example discovery sessions, see [examples.md](examples.md)
