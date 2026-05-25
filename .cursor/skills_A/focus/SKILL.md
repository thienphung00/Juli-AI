---
name: focus
description: >-
  Manages what context gets loaded into the coding agent. Decides which docs, standards,
  APIs, and dependencies to load based on the task at hand. Prevents context overload,
  wrong context, and duplication. Use BEFORE implementation to determine what the agent
  needs to know. This is the routing layer between discovery and implementation.
disable-model-invocation: true
---

# Context Orchestrator

The most important skill. LLMs fail because of too much context, wrong context, outdated context, or duplicated context. This skill solves that.

## Purpose

Decide what gets loaded into the implementation agent's context window. Acts as an intelligent router between discovery outputs and implementation work.

## When to Invoke

Call this skill AFTER `discover` has produced specs and BEFORE the implementation agent starts coding. Also invoke when:
- Switching between features mid-session
- Context window is getting large
- Agent seems confused or hallucinating (likely wrong context)

## Context Decision Algorithm

### Step 1: Classify the Task

Detect what the implementation involves:

| Detection | Context to Load |
|-----------|----------------|
| External API usage | → `review` (reliability section) |
| AI model integration | → `build-ai` standards |
| Financial/sensitive data | → `review` (security section) |
| New API endpoint | → `review` (api-endpoint checklist) |
| Database changes | → Schema docs, migration patterns |
| Frontend component | → Component library docs, design system |
| Background job | → Celery patterns, retry/idempotency standards |
| Integration connector | → Connector architecture, unified schema |

### Step 2: Load Feature Context

From `/context/features/<feature-name>/`:

```
ALWAYS load:
  - architecture.md (system design for this feature)
  - api-contracts.md (interface definitions)

LOAD IF EXISTS:
  - edge-cases.md (known gotchas)
  - db-changes.md (if touching persistence)
  - ai-eval-plan.md (if AI feature)

DO NOT load:
  - PRD.md (business context, not needed for implementation)
```

### Step 3: Load Architectural Context

Based on affected layers (from discovery docs):

```
Layer 1 (Connectors):
  - Load: connector patterns, unified schema, webhook handlers
  - Skip: frontend, AI platform

Layer 2 (AI Gateway):
  - Load: build-ai skill, LiteLLM patterns, model routing
  - Skip: connectors, infrastructure

Layer 3 (AI Models):
  - Load: build-ai skill, prompt registry, eval framework
  - Skip: connectors, deployment

Layer 4 (Interface):
  - Load: component library, Supabase patterns, state management
  - Skip: backend internals, AI models

Layer 5/6 (Data):
  - Load: schema docs, query patterns, caching strategy
  - Skip: frontend, AI models

Layer 7 (Infrastructure):
  - Load: deployment configs, scaling patterns
  - Skip: business logic, AI

Layer 8 (Monitoring):
  - Load: observability standards, alert configs
  - Skip: feature implementation details
```

### Step 4: Load Standards (Selectively)

Do NOT load all standards. Load based on what's detected:

```python
STANDARD_TRIGGERS = {
    "external_api_call": ["reliability", "observability"],
    "ai_model_call": ["build-ai", "reliability", "observability"],
    "user_input_handling": ["security", "reliability"],
    "database_query": ["performance", "reliability"],
    "new_endpoint": ["api-endpoint-checklist", "security", "observability"],
    "background_job": ["reliability", "observability"],
    "financial_data": ["security", "reliability", "observability"],
}
```

### Step 5: Exclude Irrelevant Context

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
- `/context/features/ai-inventory-forecasting/architecture.md`
- `/context/features/ai-inventory-forecasting/api-contracts.md`
- `.cursor/skills/build-ai/SKILL.md` (sections: Prompt Standards, Cost Controls)
- `src/services/inventory/` (affected module)

### Load (If Needed)
- `.cursor/skills/review/checklists/ai-integration.md`
- `.cursor/skills/review/anti-patterns.md` (reliability section only)

### DO NOT Load
- Payment service docs
- Frontend components (not affected)
- HR/admin module
- Previous sprint's customer-segmentation specs

### Standards Applied
- [x] AI Platform (model integration detected)
- [x] Reliability (external API calls detected)
- [x] Observability (new service endpoint)
- [ ] Security (no user-facing input handling)
- [ ] Performance (no new queries — uses existing indexes)
```

## Integration with Agent Roles

| Agent | Uses Context Orchestrator For |
|-------|-------------------------------|
| Discovery Agent | N/A (produces context, doesn't consume) |
| Implementation Agent | Gets precisely scoped context for coding |
| Validation Agent | Gets standards + feature specs for review |
| Context Manager | IS the context orchestrator |

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
