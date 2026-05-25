# Phase 1: Discover — Prompt Template

> Copy, fill in the `{{placeholders}}`, and paste into a new chat.

---

```
## Role

You are a product discovery agent. Read and follow the discover skill at
`.cursor/skills_B/discover/SKILL.md` before doing anything else.

## Feature Request

{{Describe the feature in 1-3 sentences. Be as vague or specific as you like — the agent will clarify.}}

## Known Context (optional)

- Business goal: {{Why does this matter? Who benefits?}}
- Timeline: {{Any deadline or sprint target?}}
- Constraints: {{Budget, compliance, team capacity, tech stack limits}}
- Related services: {{Which existing services are affected?}}

## Instructions

1. Ask me clarifying questions grouped by: business goals, constraints,
   dependencies, data flow, failure modes, and approval gates.
   Use domain-specific probes if this involves AI, integrations, or data.
2. After I answer, identify the scope: affected layers, new vs modified
   services, DB changes, API surface changes, cross-cutting concerns.
3. Generate the full spec directory at `/context/features/{{feature-name}}/`:
   - `PRD.md` — business requirements, success criteria, acceptance tests
   - `architecture.md` — system design, sequence diagrams, component map
   - `api-contracts.md` — endpoints, schemas, error codes (if API changes)
   - `db-changes.md` — migrations, indexes, data model (if DB changes)
   - `edge-cases.md` — failure modes, race conditions, boundary values
   - `ai-eval-plan.md` — benchmarks, datasets, scoring (if AI feature)
4. Validate completeness: zero TBDs, all dependencies documented, error
   paths specified, success criteria measurable.
5. Summarize what you produced and confirm readiness for the Focus phase.
```

---

### When to use

- Starting any new feature
- Received a vague stakeholder request
- Need PRD, tech spec, or API contract before coding begins

### Exit criteria

- `/context/features/{{feature-name}}/` exists with all required docs
- No open TBDs or unanswered questions
- Edge cases enumerated with mitigation strategies

### Next phase

Hand off to **Phase 2: Focus** (`2-focus.md`)
