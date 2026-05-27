---
name: focus
description: >-
  Routes the right context to the right agent by deciding which docs, standards, APIs,
  and dependencies to load based on the task. Use when scoping context before
  implementation, switching features mid-session, or when the agent seems confused
  from context overload or wrong context.
---

# Navigator

The most important skill. LLMs fail because of too much context, wrong context, outdated context, or duplicated context. Navigator solves that by intelligently routing the right information to the right agent at the right time.

## Purpose

Decide what gets loaded into the implementation agent's context window. Acts as an intelligent router between discover outputs and implementation work.

## When to Invoke

Call this skill AFTER `discover` has produced specs and BEFORE the implementation agent starts coding. Also invoke when:
- Switching between features mid-session
- Context window is getting large
- Agent seems confused or hallucinating (likely wrong context loaded)

## Context Decision Algorithm

### Step 1: Classify the Task

Detect what the implementation involves:

| Detection | Context to Load |
|-----------|----------------|
| External API usage | → `review` (reliability section) |
| AI model integration | → `review` (ai-integration checklist), reliability, observability |
| Financial/sensitive data | → `review` (security section) |
| New API endpoint | → `review` (api-endpoint checklist) |
| Database changes | → Schema docs, migration patterns |
| Frontend component | → Component library docs, design system |
| Background job | → Celery patterns, retry/idempotency standards |
| TikTok integration / webhook | → `docs/tiktok_api/`, `data-sources.md`, affected MODULE.md files |

### Step 2: Load Architecture Baseline

Always consult before loading feature docs:

```
ALWAYS load:
  - docs/architecture/map.md (module list, tiers, dependency graph)
  - docs/architecture/data-sources.md (allowed/forbidden external data)
  - MODULE.md for each affected module under src/, web/, or ios/
```

### Step 3: Load Feature Context

From `docs/features/<feature-name>/` (output of `discover`):

```
ALWAYS load:
  - architecture.md (system design for this feature)
  - api-contracts.md (interface definitions)

LOAD IF EXISTS:
  - edge-cases.md (known gotchas)
  - db-changes.md (if touching persistence)
  - ai-eval-plan.md (if AI feature)

DOMAIN DOCS (TikTok integration work):
  - docs/tiktok_api/*.md as needed (auth, webhooks, endpoints, rate-limits)

DO NOT load:
  - PRD.md (business context, not needed for implementation)
```

### Step 4: Load Layer Context

Based on affected layers from [`docs/architecture/map.md`](../../../docs/architecture/map.md):

```
Integrations (src/integrations/tiktok):
  - Load: authentication.md, rate-limits.md, endpoints.md (docs/tiktok_api/)
  - Skip: web/ios UI unless building OAuth callback UX

Services (src/services/webhook, src/services/polling):
  - Load: webhooks.md, reliability/idempotency patterns
  - Skip: dashboard components

Data (src/data):
  - Load: db-changes.md, Supabase/RLS patterns, performance rules
  - Skip: TikTok signing details unless migration touches credentials

Auth (src/auth):
  - Load: authentication.md, security rules
  - Skip: product analytics

API (src/api):
  - Load: api-endpoint checklist, api-contracts.md
  - Skip: raw TikTok client internals unless proxying

Intelligence (src/intelligence/scoring):
  - Load: data-sources.md rows #7–#8, edge-cases for post-stream-only
  - Skip: in-stream websocket designs (forbidden)

Interface (web/, ios/):
  - Load: MODULE.md for target app, shadcn/SwiftUI patterns
  - Skip: Kafka/Celery unless debugging a displayed lag issue

AI features (post-MVP / OpenAI):
  - Load: review ai-integration checklist, feature ai-eval-plan.md
  - Skip: TikTok connector docs unrelated to the model call
```

### Step 5: Load Standards (Selectively)

Do NOT load all standards. Load based on what's detected:

```python
STANDARD_TRIGGERS = {
    "external_api_call": ["reliability", "observability"],
    "ai_model_call": ["ai-integration-checklist", "reliability", "observability"],
    "user_input_handling": ["security", "reliability"],
    "database_query": ["performance", "reliability"],
    "new_endpoint": ["api-endpoint-checklist", "security", "observability"],
    "background_job": ["reliability", "observability"],
    "financial_data": ["security", "reliability", "observability"],
}
```

### Step 6: Exclude Irrelevant Context

Explicitly DO NOT load:
- Features/services not affected by this task
- Historical context from previous unrelated work
- Full codebase structure (only affected modules)
- Completed/merged feature specs (unless referenced)

## Context Budget

Target: **60-70% of context window for actual code and task**. Context docs should use 20-30%. Reserve 10% for agent reasoning.

| Priority | Content | Budget |
|----------|---------|--------|
| 1 (Critical) | Current file + immediate dependencies | 30% |
| 2 (High) | Feature architecture + API contracts | 15% |
| 3 (Medium) | Applicable standards + patterns | 10% |
| 4 (Low) | Examples + anti-patterns (load on demand) | 5% |

If context is too large, progressively disclose: load summaries first, fetch details only when the agent needs them.

## Output Format

When invoked, produce a context loading plan:

```markdown
## Context Plan: [Feature/Task Name]

### Load (Required)
- `docs/architecture/map.md`
- `docs/architecture/data-sources.md`
- `docs/features/tiktok-order-webhook-sync/architecture.md`
- `docs/features/tiktok-order-webhook-sync/api-contracts.md`
- `src/services/webhook/MODULE.md`
- `src/data/MODULE.md`

### Load (If Needed)
- `docs/tiktok_api/webhooks.md`
- `.cursor/skills/standalone/review/checklists/api-endpoint.md`

### DO NOT Load
- `web/`, `ios/` (not affected)
- `src/intelligence/scoring/` (not affected)
- Shopee/Lazada or multi-platform connector docs (out of scope per data-sources.md #13)

### Standards Applied
- [x] AI Core (model integration detected)
- [x] Reliability (external API calls detected)
- [x] Observability (new service endpoint)
- [ ] Security (no user-facing input handling)
- [ ] Performance (no new queries — uses existing indexes)
```

## Integration with Agent Roles

| Agent | Uses Navigator For |
|-------|-------------------|
| Discovery Agent | N/A (produces context, doesn't consume) |
| Implementation Agent | Gets precisely scoped context for coding |
| Validation Agent | Gets standards + feature specs for review |
| Context Manager | IS the focus skill |

## Anti-Patterns

### Context Overload
Loading everything "just in case" — wastes tokens, confuses the agent.

### Stale Context
Loading specs from features that have since changed — causes hallucinated patterns.

### Context Duplication
Loading the same information from multiple sources — wastes budget, risks conflicts.

### Missing Context
Not loading edge-cases.md — agent produces happy-path-only code.

## Additional Resources

- For architecture layer reference, see `discover/architecture-context.md`
- For context routing rules, see [routing-rules.md](routing-rules.md)
