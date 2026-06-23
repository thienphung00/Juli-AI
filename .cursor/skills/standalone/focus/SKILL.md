---
name: focus
description: >-
  Default context router — classifies tasks and produces a Context Plan for docs,
  rules, skills, MCPs, and workflow phases. Invoke at conversation start and before
  implementation; also when switching features or context overload is detected.
catalog:
  pluginIndex: skill-catalog
  loadWhen:
    - external mcp or marketplace plugin
    - supabase sentry figma vercel shadcn context7
    - browser playwright celery upstash integration
---

# Navigator

The single router for what enters the agent's context window. LLMs fail from too much, wrong, outdated, or duplicated context — Focus prevents that.

## Purpose

Decide what gets loaded: workflow phase, Tier 2 rules, canonical docs, domain skills, plugin skills, and MCP servers. **All routing detail lives in [routing-rules.md](routing-rules.md)** — do not duplicate tables here.

## When to invoke

| Trigger | Action |
|---------|--------|
| New user message (non-trivial) | Classify task type → produce Context Plan |
| After `grill-with-docs` → `to-prd`/`to-issues` | Re-run before implementation |
| Switching features mid-session | Re-run; update DO NOT Load list |
| Context window large / agent confused | Re-run; trim loaded context |

**Ad-hoc chat:** Focus only — do not auto-enter grill-with-docs/tdd/review unless the user asks.

## Runtime flow

```
User message
  → Tier 1 rules (core-safety, core-orchestration, mcp-usage, git-baseline)
  → Focus → classify Planning vs Implementation
  → Load per routing-rules.md + conditional detection
  → Execute task
```

## Step 0 — Classify task type

| Type | Load core | See |
|------|-----------|-----|
| **Planning** | `EXECUTION.md` → ONE Tier 1 doc → relevant ADR(s) | [routing-rules.md § Planning](routing-rules.md#planning-task) |
| **Implementation** | GitHub Issue → PRD → relevant ADR(s) | [routing-rules.md § Implementation](routing-rules.md#implementation-task) |

**Planning signals:** rescope, grill-with-docs, architecture review, to-prd prep, domain modeling.  
**Implementation signals:** issue #N, tdd, review, ship, validate, scoped bug fix.

## Step 1 — Classify workflow phase

| Task signal | Workflow |
|-------------|----------|
| New initiative / rescope | `grill-with-docs` → canonical docs |
| Spec from conversation | `to-prd` → `to-issues` |
| GitHub issue implementation | `focus` → `tdd` → `review` → `ship` → `validate` |
| Bug / failing test / Sentry | `fix-bug`: `qa` → `focus` → `tdd` → … |
| End-to-end feature build | `build-feature` orchestrator |
| Parallel issues / worktrees | `issue-workflow.mdc` + `EXECUTION.md` slice status |

## Step 2 — Add conditional context

After the core load set from Step 0:

1. **MCP / plugin skills** — if external product touch; see [routing-rules.md § MCP](routing-rules.md#plugin-skills-and-mcp).
2. **Tier 2 rules + domain skills** — from code/path detection; see [routing-rules.md § detection](routing-rules.md#code-detection--tier-2-rules-and-domain-skills).
3. **`MODULE.md`** — implementation tasks only, for modules under `src/`, `web/`, `ios/` that the issue touches.
4. **Vendor docs** — `docs/<vendor>_api/` when integrating or debugging external APIs.

**Lazy-load contract:** Marketplace plugin skills in Cursor UI are not authoritative — load only what Focus selects from skill-catalog.

## Step 3 — Domain glossary and ADRs

Before emitting the handoff block:

1. If `CONTEXT.md` exists at repo root, read it — decode domain terms in the issue.
2. Include summaries of relevant ADRs in the Context Plan so `tdd` does not re-litigate settled choices.

## Domain classification

Classify the issue from title, body, and file paths using the **Domain skill routing** table in [`.cursor/rules/core-orchestration.mdc`](../../../rules/core-orchestration.mdc).

- No match → `domain_skills: []`
- Multiple matches → list all (consumed by `tdd`)

## Output format

Produce a context loading plan (template: `docs/handoffs/context-plan-template.md`):

```markdown
## Context Plan: [Feature/Task Name]

### Task type
- [ ] Planning (EXECUTION → Tier 1 → ADR)
- [x] Implementation (Issue → PRD → ADR)

### Workflow phase
- [ ] ad-hoc (Focus only)
- [x] issue implementation: focus → tdd → review → ship

### Core load (required)
- `EXECUTION.md` slice P2-1          ← Planning only
- `docs/system-design.md` § …        ← Tier 1 pick (Planning) or on-demand (Implementation)
- GitHub issue #N                    ← Implementation only
- ADR-013: operations pipeline spine

### Rules (Tier 2)
- [x] `.cursor/rules/reliability.mdc`

### domain_skills
domain_skills: [patterns.mdc, python-patterns]

### MCPs
- [ ] `supabase`

### Load (if needed)
- `docs/tiktok_api/endpoints.md`
- `src/apps/cron_jobs/services/polling/MODULE.md`

### DO NOT load
- Unselected marketplace plugin skills
- Peer Tier 1 docs not listed above
- Legacy `docs/features/mvp_*` folders
```

## Anti-patterns

| Pattern | Fix |
|---------|-----|
| Context overload | Drop peer Tier 1 docs; keep Issue + ADR on implementation |
| Stale context | Reload after rescope PR merges |
| Duplication | One source per fact — EXECUTION for scope, ADR for why, Tier 1 for how |
| Missing edge cases | On implementation, ensure PRD / issue acceptance criteria are loaded |

## Reference

- [routing-rules.md](routing-rules.md) — Tier 1 table, MCP map, detection patterns, layer map
