---
name: focus
description: >-
  Routes the right context to the right agent by deciding which docs, standards, APIs,
  and dependencies to load based on the task. Use when scoping context before
  implementation, switching features mid-session, or when the agent seems confused
  from context overload or wrong context.
catalog:
  pluginIndex: skill-catalog
  loadWhen:
    - external mcp or marketplace plugin
    - supabase sentry figma vercel shadcn context7
    - browser playwright celery upstash integration
---

# Navigator

The most important skill. LLMs fail because of too much context, wrong context, outdated context, or duplicated context. Navigator solves that by intelligently routing the right information to the right agent at the right time.

## Purpose

Decide what gets loaded into the implementation agent's context window. Acts as an intelligent router between discover handoffs, canonical docs, and implementation work.

## When to Invoke

Call this skill AFTER `discover` has updated canonical docs and handed off to `to-prd`/`to-issues`, and BEFORE the implementation agent starts coding. Also invoke when:
- Switching between features mid-session
- Context window is getting large
- Agent seems confused or hallucinating (likely wrong context loaded)

## Context Decision Algorithm

### Step 0: Plugin and MCP routing

When the task touches an external product or MCP integration:

1. Read [`.cursor/skills/skill-catalog/SKILL.md`](../../skill-catalog/SKILL.md) — use the `catalog` frontmatter for MCP `serverName` values and plugin skill names.
2. Load only the plugin skills that match the task (e.g. `supabase` for migrations, `nextjs` for `web/` routing).
3. Follow [`.cursor/rules/mcp-usage.mdc`](../../../rules/mcp-usage.mdc) before calling MCP tools (read tool schema first).

### Step 1: Classify the Task

Detect what the implementation involves:

| Detection | Context to Load |
|-----------|----------------|
| External API usage | → `review` (reliability section) |
| AI model integration | → `review` (ai-integration checklist), reliability, observability |
| Financial/sensitive data | → `review` (security section) |
| New API endpoint | → `review` (api-endpoint checklist) |
| Database changes / SQL | → `.cursor/skills/domain/postgres-patterns.md`, schema docs, migration patterns |
| Python code / FastAPI | → `.cursor/skills/domain/python-patterns.md` |
| Python tests / pytest | → `.cursor/skills/domain/python-testing.md` |
| SwiftUI / iOS | → `.cursor/skills/domain/swift-patterns.md` |
| Frontend component | → Component library docs, design system |
| Background job | → Celery patterns, retry/idempotency standards |
| TikTok integration / webhook | → `docs/tiktok_api/`, `data-sources.md`, affected MODULE.md files |
| Net-new vendor API / stale `docs/*_api/` | → `api-docs` skill first; then `docs/<vendor>_api/`, `data-sources.md` |
| Marketplace policy / feature guide / account health / seller or creator | → `platform-docs`; then `docs/<vendor>_platform/`, `implementation-hooks.md` |
| Existing vendor API implementation | → `docs/<vendor>_api/`, `docs/<vendor>_platform/` (if exists), `data-sources.md`, affected MODULE.md files |

### Step 2: Load Architecture Baseline

Always consult before loading task-specific context:

```
ALWAYS load:
  - EXECUTION.md (phase, slice, in/out scope for the current issue)
  - docs/system-design.md (subsystem behavior for the active phase)
  - docs/architecture/map.md (module list, tiers, dependency graph)
  - docs/architecture/data-sources.md (allowed/forbidden external data)
  - MODULE.md for each affected module under src/, web/, or ios/
```

### Step 3: Load Task Context

From the GitHub issue (PRD from `to-prd`), discover handoff, and vendor docs:

```
ALWAYS load:
  - Relevant EXECUTION.md slice(s) driving the issue
  - docs/system-design.md sections for affected subsystems
  - GitHub issue body (acceptance criteria, user stories)
  - discover → to-prd handoff (scope, edge cases, implementation decisions)

LOAD WHEN VENDOR/PLATFORM WORK:
  - docs/<vendor>_api/*.md as needed (auth, webhooks, endpoints, rate-limits)
  - docs/<vendor>_platform/*/implementation-hooks.md (guardrails, alerts, gates)

LOAD IF EXISTS (legacy only):
  - docs/features/<feature-name>/*.md — historical attachments; prefer canonical docs

DO NOT load by default:
  - Full EXECUTION.md when a single slice is sufficient
  - Superseded ADRs unless the issue explicitly references them
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
  - Load: system-design.md data-pipeline section, issue schema notes, Supabase/RLS patterns, performance rules
  - Skip: TikTok signing details unless migration touches credentials

Auth (src/auth):
  - Load: authentication.md, security rules
  - Skip: product analytics

API (src/api):
  - Load: api-endpoint checklist, issue API contracts / system-design.md interface notes
  - Skip: raw TikTok client internals unless proxying

Intelligence (src/intelligence/scoring):
  - Load: data-sources.md rows #7–#8, edge-cases for post-stream-only
  - Skip: in-stream websocket designs (forbidden)

Interface (web/, ios/):
  - Load: MODULE.md for target app, shadcn/SwiftUI patterns
  - Skip: Celery/Redis unless debugging a displayed lag issue (v2.0)

AI features (post-MVP / OpenAI):
  - Load: review ai-integration checklist, system-design.md ML model sections, issue eval notes
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
    # Domain skills (prefer these over broader docs)
    "python_impl": [".cursor/skills/domain/python-patterns.md"],
    "python_tests": [".cursor/skills/domain/python-testing.md"],
    "postgres_impl": [".cursor/skills/domain/postgres-patterns.md"],
    "swiftui_impl": [".cursor/skills/domain/swift-patterns.md"],
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
| 2 (High) | system-design.md + issue acceptance criteria | 15% |
| 3 (Medium) | Applicable standards + patterns | 10% |
| 4 (Low) | Examples + anti-patterns (load on demand) | 5% |

If context is too large, progressively disclose: load summaries first, fetch details only when the agent needs them.

## Output Format

When invoked, produce a context loading plan:

```markdown
## Context Plan: [Feature/Task Name]

### Load (Required)
- `EXECUTION.md` (slice P2-1)
- `docs/system-design.md` (Data pipeline → Phase 2)
- `docs/architecture/map.md`
- `docs/architecture/data-sources.md`
- GitHub issue #N — acceptance criteria
- `docs/tiktok_api/endpoints.md`, `authentication.md`
- `src/services/polling/MODULE.md`
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
| Discovery Agent | Updates canonical docs; handoff consumed by to-prd |
| Implementation Agent | Gets precisely scoped context for coding |
| Validation Agent | Gets standards + canonical docs + issue for review |
| Context Manager | IS the focus skill |

## Anti-Patterns

### Context Overload
Loading everything "just in case" — wastes tokens, confuses the agent.

### Stale Context
Loading specs from features that have since changed — causes hallucinated patterns.

### Context Duplication
Loading the same information from multiple sources — wastes budget, risks conflicts.

### Missing Context
Not loading discover handoff edge cases or system-design failure modes — agent produces happy-path-only code.

## Additional Resources

- For architecture layer reference, see `discover/architecture-context.md`
- For context routing rules, see [routing-rules.md](routing-rules.md)
