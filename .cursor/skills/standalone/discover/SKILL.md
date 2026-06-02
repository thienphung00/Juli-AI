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
User Idea → Research & Reuse → Clarifying Questions → Scope & Dependencies → Spec Generation → Context Docs → Handoff
```

## Boundaries (avoid skill overlap)

`discover` is the **interactive** front-door: it interviews to remove ambiguity, studies repo prior art, and writes **feature-local docs** that downstream skills implement or ticket.

- **`discover` MUST do**
  - Ask clarifying questions to eliminate TBDs.
  - Perform mandatory **Research & Reuse** before proposing net-new design/work.
  - Produce architecture/system-design/data-sources docs under `docs/features/<feature-name>/`.
  - Hand off a complete, implementable spec to downstream skills.

- **`discover` MUST NOT do** (reserved for other skills)
  - Turn the current context into a PRD **without interviewing** (that is `to-prd`).
  - Create GitHub issues / tickets (that is `to-prd` + `to-issues` via `gh`).
  - Start implementation changes (that is `focus` → `tdd` / implementation agents).

## Step 0 (MANDATORY): Research & Reuse (before proposing anything new)

Do not design “from scratch” until you’ve looked for proven prior art.

### 0.1 GitHub code search first (required)

Search for existing implementations, templates, and patterns that solve ≥80% of the need.

- Run repo search:
  - `gh search repos "<keywords>" --limit 20`
- Run code search (target this repo and adjacent ecosystems):
  - `gh search code "<keywords>" --limit 20`
  - `gh search code "<keywords> repo:<owner>/<repo>" --limit 20`

Prioritize reuse targets:
- established OSS projects
- internal repo patterns (similar modules/tests)
- templates and reference implementations

### 0.2 Library docs second (required)

Before committing to an API/library choice, confirm version-specific behavior:
- Use Context7 or primary vendor docs.
- Record the chosen library + rationale in the spec (“Implementation Decisions”).

### 0.3 Exa only when the first two are insufficient (optional)

Use broader web research only when GitHub search + primary docs don’t answer the question.

### 0.4 Check package registries (required when adding utilities)

Before writing utility code, search registries (npm, PyPI, crates.io, etc.).
Prefer battle-tested libraries over hand-rolled utilities when they meet requirements.

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

**Integrations** (TikTok Shop Partner API):
- Webhook or polling? Rate limits?
- Mapping to `src/data` models and shop scoping?
- Retry/backoff strategy? Idempotency keys?

**Data features:**
- Forecast horizon? Aggregation level?
- Historical data requirements? Staleness tolerance?
- Privacy/PII implications?

## Step 2: Identify Scope

Map the feature to:
- Affected layers in [`docs/architecture/map.md`](../../../docs/architecture/map.md) and [architecture-context.md](architecture-context.md)
- Allowed data sources in [`docs/architecture/data-sources.md`](../../../docs/architecture/data-sources.md)
- Existing modules to modify vs. new modules (update `map.md` when adding modules)
- Database schema changes and migration strategy
- API surface changes (breaking vs. additive)
- Cross-cutting concerns (auth, caching, monitoring)

## Step 3: Generate Specification Docs

Produce docs in `docs/features/<feature-name>/`:

| Document | Purpose | Required? |
|----------|---------|-----------|
| `PRD.md` | Business requirements, success criteria, acceptance tests | Always |
| `architecture.md` | **Architecture**: boundaries, high-level structure, constraints, ownership | Always |
| `system-design.md` | **System design**: data flows, algorithms, storage/indexes, infra/runtime choices | Always |
| `data-sources.md` | What external/internal data sources are used (and why allowed) | Always |
| `api-contracts.md` | Endpoint specs, request/response schemas, error codes | If API changes |
| `db-changes.md` | Schema migrations, indexes, data model changes | If DB changes |
| `edge-cases.md` | Failure modes, race conditions, boundary values | Always |
| `ai-eval-plan.md` | Benchmarks, test datasets, scoring rubrics | If AI feature |

## Step 3.5 (CONDITIONAL): Generate an ADR (Architecture Decision Record)

If discovery introduces or selects an architectural decision that affects future work, write an ADR in `docs/decisions/`.

**Generate an ADR when ANY is true:**
- New module added to `docs/architecture/map.md`
- Breaking interface change is planned
- Major runtime/infra choice is made (queues, storage model, auth boundary, scheduling model)
- The architecture is non-obvious and has meaningful trade-offs

**ADR rules (repo conventions):**
- File: `docs/decisions/NNN-slug.md` (three-digit, zero-padded; lowercase slug)
- Update `docs/decisions/README.md` index row (id, title, status)
- Keep it decision-focused (not a tutorial)

### ADR Template (trade-off first)

```markdown
# ADR NNN: [Title]

## Status
Proposed | Accepted | Rejected | Superseded

## Context
- What problem/constraint forces a decision?
- What prior art exists in this repo (and what doesn’t fit)?
- What is the decision deadline / risk window?

## Decision
- We will: [chosen architecture / boundary / component]
- We will not: [explicit non-goals / rejected scope]

## Why this architecture (the “because”)
- **Speed (time-to-ship)**: [what becomes faster/easier]
- **Cost**: [infra/runtime/ops + dev cost; lock-in]
- **Scalability**: [growth path; expected bottlenecks]
- **Performance**: [latency/throughput budgets; query patterns]
- **Reliability/Operability**: [idempotency/retries; monitoring; blast radius]

## Options considered
- Option A: [summary] → Pros / Cons / Why not chosen
- Option B: [summary] → Pros / Cons / Why not chosen

## Consequences
- **Positive**: [what we gain]
- **Negative**: [what we accept/pay]
- **Follow-ups**: [work required to make this safe/complete]

## Rollout / Migration plan (if applicable)
- Stepwise plan including compatibility windows and backfills.
```

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

## Boundaries & Ownership
- **Owned modules**: [what this feature owns]
- **Touched modules**: [what it depends on]
- **External dependencies**: [APIs/infra vendors]

## Fundamental Constraints
- **Security**: [authn/authz, PII rules, threat model]
- **Reliability**: [idempotency, retries, DLQ, backpressure]
- **Performance**: [rate limits, pagination, budgets]
- **Operational**: [alerts, runbooks, observability]

## High-level Components
| Component | Responsibility | Layer / Boundary |
|-----------|---------------|------------------|

## Sequence Diagram
[Mermaid sequence diagram]

## Key Flows (high-level)
- [Trigger] → [Boundary] → [Boundary] → [Outcome]

## Failure Modes
| Failure | Impact | Mitigation |
|---------|--------|------------|
```

### System Design Template

```markdown
# System Design: [Feature Name]

## End-to-end Data Flow
[Input] → [Validate] → [Transform] → [Persist] → [Serve] → [Observe]

## Detailed Components
For each component:
- Responsibilities
- Inputs/outputs (schemas or examples)
- Algorithms / rules (edge conditions, ordering, idempotency)
- Storage model (tables, indexes, constraints) and access patterns
- Runtime/infra decisions (queues, workers, cron, timeouts)

## Trade-offs
- Option A vs Option B, with rationale and risk.

## Operational Plan
- Logs/metrics/traces
- Alerts and SLO signals
- Backfill/migration plan (if any)
```

### Data Sources Template

```markdown
# Data Sources: [Feature Name]

## Sources Used
| Source | Purpose | Status (MVP/v1.5/v2.0/Out/Forbidden) | Constraints | Notes |
|--------|---------|--------------------------------------|------------|------|

## Compliance With `docs/architecture/data-sources.md`
- Cite the applicable rows and explain how the feature stays within constraints.

## Data Minimization / PII
- What is stored, for how long, and how it is masked/redacted.
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
- [ ] Research & Reuse completed (GitHub search + docs verification + registry check as needed)
- [ ] ADR added to `docs/decisions/` if an architectural decision was made (modules/interfaces/runtime trade-offs)

## Output

The generated `docs/features/<feature-name>/` directory becomes shared context for all downstream agents (implementation, validation, delivery). The `focus` skill uses these docs plus `docs/architecture/map.md` to determine what context to load.

## Integration with Other Skills

| Downstream Skill | What It Uses from Blueprint |
|-----------------|---------------------------|
| `focus` | Feature docs to build context loading plan |
| `review` | Edge cases and API contracts for validation |
| `ship` | Architecture docs for deployment planning |

## Additional Resources

- For architecture layer reference, see [architecture-context.md](architecture-context.md)
- For example discovery sessions, see [examples.md](examples.md)
