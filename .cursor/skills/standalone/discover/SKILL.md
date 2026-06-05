---
name: discover
description: >-
  Synthesizes user ideas and upstream api-docs/platform-docs handoffs into updates
  to EXECUTION.md, docs/system-design.md, docs/architecture/, and docs/decisions/.
  Use when scoping a new initiative, rescoping phases, or aligning product intent
  with canonical architecture docs before to-prd.
---

# Blueprint

Synthesizes ambiguous user requests into **updates to canonical repo docs**. This is the
interactive front-door of every workflow — nothing gets built until discovery aligns
the plan with `EXECUTION.md` and related architecture docs.

## Workflow

```
User Idea
  + api-docs handoff (when vendor/API)
  + platform-docs handoff (when seller/creator/platform)
    → Research & Reuse
    → Clarifying Questions
    → Scope & Dependencies
    → Update Canonical Docs
    → Validate
    → Handoff → to-prd
```

## Boundaries (avoid skill overlap)

`discover` is the **interactive** front-door: it interviews to remove ambiguity, studies
repo prior art, and **updates canonical docs** that downstream skills implement or ticket.

- **`discover` MUST do**
  - Ask clarifying questions to eliminate TBDs.
  - Perform mandatory **Research & Reuse** before proposing net-new design/work.
  - Consume `api-docs` and `platform-docs` handoffs when vendor/platform context applies.
  - Update `EXECUTION.md`, `docs/system-design.md`, `docs/architecture/`, and `docs/decisions/` as needed.
  - Hand off a complete scope summary to `to-prd`.

- **`discover` MUST NOT do** (reserved for other skills)
  - Generate **any** docs under `docs/features/<feature>/`.
  - Turn context into a PRD or GitHub issue (`to-prd`, `to-issues`).
  - Extract vendor API or platform reference material (`api-docs`, `platform-docs`).
  - Start implementation changes (`focus` → `tdd` / implementation agents).

## Step 0: Load inputs (MANDATORY)

Always read before proposing changes:

- [`EXECUTION.md`](../../../../EXECUTION.md)
- [`docs/system-design.md`](../../../../docs/system-design.md)
- [`docs/architecture/map.md`](../../../../docs/architecture/map.md)
- [`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md)
- [`docs/decisions/README.md`](../../../../docs/decisions/README.md) (+ relevant ADRs)

When vendor/platform work applies:

- **`api-docs` handoff** — or run `api-docs` first if `docs/<vendor>_api/` is missing/stale
- **`platform-docs` handoff** — or run `platform-docs` first if `docs/<vendor>_platform/` is missing/stale

Record a synthesis note in chat (not a new file):

```markdown
### Discovery inputs
- User idea: <one paragraph>
- Vendor API: <loaded | stale | N/A> — docs/<vendor>_api/
- Platform: <loaded | stale | N/A> — docs/<vendor>_platform/
- EXECUTION.md phase fit: <P1 | P1.5 | P2 | out | needs rescope>
- Conflicts with current plan: <none | list>
```

**Authority order** when editing (from `EXECUTION.md` governance):

```
Code > EXECUTION.md > docs/system-design.md > docs/architecture/map.md
```

If a user idea conflicts with `EXECUTION.md`, surface the conflict and get explicit
approval before changing the execution plan.

## Step 0.1: Research & Reuse (before proposing anything new)

Do not design “from scratch” until you’ve looked for proven prior art.

### GitHub code search first (required)

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

### Library docs second (required)

Before committing to an API/library choice, confirm version-specific behavior:
- Use Context7 or primary vendor docs.
- Record the chosen library + rationale in the discover → to-prd handoff (“Implementation Decisions”).

### Exa only when the first two are insufficient (optional)

Use broader web research only when GitHub search + primary docs don’t answer the question.

### Check package registries (required when adding utilities)

Before writing utility code, search registries (npm, PyPI, crates.io, etc.).
Prefer battle-tested libraries over hand-rolled utilities when they meet requirements.

## Step 1: Ask Clarifying Questions

Before updating canonical docs, gather enough to eliminate ambiguity:

1. **Business goals** — What outcome does this serve? Who benefits?
2. **Constraints** — Budget, timeline, compliance, model tier, team capacity
3. **Dependencies** — Which services are affected? Which APIs consumed/exposed?
4. **Data flow** — Where does data originate, transform, and persist?
5. **Failure modes** — What happens when things break? What's the blast radius?
6. **Approval gates** — Human-in-the-loop required? Who signs off?
7. **Phase fit** — Which `EXECUTION.md` phase/slice does this belong to?
8. **Scope boundary** — Does this require a north-star or in/out scope change?

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
- Affected layers in [`docs/architecture/map.md`](../../../../docs/architecture/map.md) and [architecture-context.md](architecture-context.md)
- Allowed data sources in [`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md)
- Existing modules to modify vs. new modules (update `map.md` when adding modules)
- Database schema changes and migration strategy
- API surface changes (breaking vs. additive)
- Cross-cutting concerns (auth, caching, monitoring)
- Target `EXECUTION.md` slices and phase gates

## Step 3: Update Canonical Docs

Update existing files — do **not** create parallel trees under `docs/features/`.

| File | What discover updates |
|------|----------------------|
| [`EXECUTION.md`](../../../../EXECUTION.md) | North star alignment, in/out scope, phase placement, slices, exit gates, issue refs |
| [`docs/system-design.md`](../../../../docs/system-design.md) | Phase capability matrix, subsystem behavior, ML/pipeline/executor details |
| [`docs/architecture/map.md`](../../../../docs/architecture/map.md) | New/changed modules, layers, dependency edges |
| [`docs/architecture/data-sources.md`](../../../../docs/architecture/data-sources.md) | Status rows, substitutes, operational rules, forbidden patterns |
| [`docs/decisions/NNN-slug.md`](../../../../docs/decisions/) | ADRs when architecture choices have trade-offs |
| [`docs/decisions/README.md`](../../../../docs/decisions/README.md) | Index row for each new/changed ADR |

### 3.1 `EXECUTION.md`

- [ ] Idea fits current north star, or north star section updated with rationale
- [ ] Phase and week placement explicit
- [ ] New/changed slices added (`P1-N`, `P1.5-N`, `P2-N`) with issue refs or `TBD`
- [ ] In scope / Explicitly out lists updated if scope boundary moves
- [ ] Exit gates unchanged or updated with Product lead approval

### 3.2 `docs/system-design.md`

- [ ] Phase capability matrix rows affected
- [ ] Subsystem sections updated (agent tree, pipeline, models, copy layer, executor)
- [ ] Cross-links to `EXECUTION.md` slices driving the change

### 3.3 `docs/architecture/map.md`

- [ ] New modules or boundary changes reflected
- [ ] Dependency graph updated when cross-layer flows change

### 3.4 `docs/architecture/data-sources.md`

- [ ] Rows added/updated from `api-docs` / `platform-docs` handoffs (status, constraints)
- [ ] Forbidden / substitute / operational rules aligned with platform policy surface

### 3.5 `docs/decisions/` (conditional)

Generate or update an ADR when **ANY** is true:
- New module added to `docs/architecture/map.md`
- Breaking interface change is planned
- Major runtime/infra choice is made (queues, storage model, auth boundary, scheduling model)
- The architecture is non-obvious and has meaningful trade-offs

**ADR rules (repo conventions):**
- File: `docs/decisions/NNN-slug.md` (three-digit, zero-padded; lowercase slug)
- Update `docs/decisions/README.md` index row (id, title, status)
- Keep it decision-focused (not a tutorial)
- Do **not** duplicate ADR content already drafted by `api-docs` / `platform-docs` — promote their ADR candidates or merge rationale

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

## Step 4: Validate Completeness

Before handing off to `to-prd`, every item must be checked:

- [ ] All clarifying questions answered (no TBDs in canonical docs)
- [ ] Upstream handoffs consumed (or `api-docs` / `platform-docs` run first)
- [ ] `EXECUTION.md` and `system-design.md` agree on phase behavior
- [ ] `data-sources.md` reflects vendor + platform constraints
- [ ] ADRs indexed in `docs/decisions/README.md` when applicable
- [ ] Security implications considered
- [ ] Research & Reuse completed (GitHub search + docs verification + registry check as needed)
- [ ] **No files created under `docs/features/`**

## Output: Handoff → to-prd

```markdown
## Handoff: discover → to-prd

### Feature summary
[One paragraph: what, why, for whom]

### Canonical doc updates (this session)
- EXECUTION.md: <slices/phases changed>
- docs/system-design.md: <sections changed>
- docs/architecture/map.md: <modules/edges changed | none>
- docs/architecture/data-sources.md: <rows changed | none>
- docs/decisions/: <ADR-NNN added/updated | none>

### Scope
- EXECUTION.md phase/slices: [e.g. P1-3, P2-1]
- Affected layers: [from map.md]
- Data sources: [rows from data-sources.md]
- Services to modify / add: [modules]
- DB changes: [yes/no + brief]
- API surface: [breaking/additive/none]

### Constraints
- [Budget, timeline, compliance, platform limits from platform-docs]

### Edge cases & failure modes
- [From discovery + risks.md + platform policy]

### Implementation decisions
- [Key architectural choices, libraries, patterns from Research & Reuse]

### Assumptions for to-prd
- [Anything still soft — to-prd will note in PRD]

### Open questions
- [Unresolved items]
```

Downstream skills (`focus`, `review`, `ship`) load canonical docs plus vendor/platform
docs — not `docs/features/`. The `focus` skill uses `EXECUTION.md`, `system-design.md`,
`map.md`, and the discover handoff to determine what context to load.

## Integration with Other Skills

| Skill | Relationship |
|-------|--------------|
| `api-docs` | **Upstream (required for net-new/stale vendor)** — discover consumes handoff; does not re-extract |
| `platform-docs` | **Upstream (required for seller/creator features)** — discover consumes guardrails + policy surface |
| `to-prd` | **Downstream** — receives handoff; writes PRD + GitHub issue |
| `to-issues` | **Downstream of to-prd** — slices from PRD, aligned to `EXECUTION.md` slices |
| `focus` | **Downstream** — loads canonical docs + vendor docs + issue/PRD |
| `review` | **Downstream** — edge cases and contracts from handoff + system-design |
| `ship` | **Downstream** — architecture docs for deployment planning |

## Additional Resources

- For architecture layer reference, see [architecture-context.md](architecture-context.md)
- For example discovery sessions, see [examples.md](examples.md)
