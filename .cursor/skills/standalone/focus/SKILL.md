---
name: focus
description: >-
  Default context router — classifies tasks and produces a Context Plan for docs,
  rules, skills, MCPs, and agent phases. Invoke at conversation start and before
  implementation; also when switching features or context overload is detected.
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

Decide what gets loaded into the agent's context window. Acts as the **single router** for agent phases, Meta Agent context/skill routing, Tier 2 rules, canonical docs, domain patterns, plugin skills, and MCP servers.

## When to Invoke

**Every non-trivial task** — at conversation start, not only pre-implementation:

| Trigger | Action |
|---------|--------|
| New user message (non-trivial) | Classify task → produce Context Plan |
| After Planning (`to-prd` / `to-issues`) | Re-run before implementation |
| Switching features mid-session | Re-run; update DO NOT Load list |
| Context window large / agent confused | Re-run; trim loaded context |

**Ad-hoc chat:** Focus only — do not auto-enter Review, Executor, or Validate phases unless the user asks.

## Runtime Flow

```
User message
  → Tier 1 rules (core-safety, core-orchestration, mcp-usage, git-baseline)
  → Focus (this skill) → Context Plan
  → Load selected: agent phase | Tier 2 rules | docs | domain skills | plugin skills | MCP schemas
  → Execute task
```

## Context Decision Algorithm

### Step 0: Classify agent phase

| Task signal | Agent phase | Load |
|-------------|-------------|------|
| New initiative / rescope / canonical doc updates | Planning (Architect) | [`agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md) Planning section; canonical docs; `grill-with-docs` → `to-prd` path |
| Spec from conversation | Planning | `grill-with-docs` (if scope open) → `to-prd` → `to-issues` |
| GitHub issue implementation | Implementation | Meta routing → **`meta_prepare_executor.py --issue N`** (ensure parent/child cache) → domain executor skill (`ui-ux`, `backend`, `data-platform`, `machine-learning`); built-in TDD |
| Bug / failing test / Sentry | Implementation | `qa` first, then Meta routing + Executor |
| Post-implementation quality gate | Review + Testing | `intent-review` → `guardrails` → `validate` → `ship` |
| Branch / PR / "review since X" | Review + Testing | `intent-review` (Spec fidelity × structure); then `guardrails` when emitting ADR-003 artifact |
| Architecture review / deepen modules | Ad-hoc (explore → report → grill → execute) | `improve-codebase-architecture`, `codebase-design`, `CONTEXT.md`, `docs/adr/`, `docs/architecture/map.md` |
| Mechanical file/module moves (structure already decided) | Ad-hoc | `restructure` (test-invariant moves only) |
| Parallel issues / worktrees | Implementation | `issue-workflow.mdc` + [`docs/handoffs/worktree-branch-topology.md`](../../../docs/handoffs/worktree-branch-topology.md) |
| Quick GitHub commit / hotfix in `.worktrees/debug` (no `issue-<N>` branch) | Ad-hoc | Skip ADR-003 artifacts per [`agent-runtime.config.yml`](../../../agent-runtime/config/agent-runtime.config.yml) `artifact_gates.quickCommitSkip` — do not edit `pr.yml`/rules from this slot |
| Multiple independent edits/explores in one session | Ad-hoc or Implementation | Task subagents always `model: composer-2.5-fast`; ≤3 concurrent (ask if more); prefer small parallel tasks per [`core-orchestration.mdc`](../../../rules/core-orchestration.mdc) § Composer sub-agents; parent synthesizes |

Domain executor skills live under `.cursor/skills/domain/{ui-ux,backend,data-platform,machine-learning}/`.

### Step 1: Plugin and MCP routing

When the task touches an external product or MCP integration:

1. Read [`.cursor/skills/skill-catalog/SKILL.md`](../../skill-catalog/SKILL.md) — use `catalog` frontmatter for MCP `serverName` values and plugin skill names.
2. Load **only** matching plugin skills (e.g. `supabase` for migrations, `nextjs` for `web/`).
3. Read MCP tool schemas from `mcps/<folder>/tools/` **only for selected servers**.
4. Follow [`.cursor/rules/mcp-usage.mdc`](../../../rules/mcp-usage.mdc) before calling MCP tools.

**Lazy-load contract:** Marketplace plugin skills listed in Cursor UI are not authoritative — load only those Focus selects from skill-catalog. Ignore unselected plugin skills even if visible in `available_skills`.

| Task signal | Plugin skill(s) | MCP `serverName` |
|-------------|-----------------|------------------|
| TikTok API / webhooks | — | — (use `docs/integrations/tiktok_api/`, MODULE.md) |
| New vendor API | `api-docs`, `context7-mcp` | `context7` |
| Seller/creator policy | `platform-docs` | — |
| `web/` Next.js UI | `ui-ux-design`, `nextjs`, `react-best-practices`; `shadcn` if registry | `shadcn` |
| Supabase / migrations / RLS | `supabase`, `supabase-postgres-best-practices` | `supabase` |
| Production error | `sentry-workflow` → platform SDK | `plugin-sentry-sentry` |
| Figma design sync | `figma-use` (before `use_figma`) | `figma` |
| E2E / browser verify | — | `playwright` or `cursor-ide-browser` |
| Celery / Redis | — | `celery`, `upstash` |
| Deploy / env vars | `deployments-cicd`, `env-vars` | `plugin-vercel-vercel` |

### Step 2: Classify the Task (docs & patterns)

Detect what the implementation involves:

| Detection | Context to Load |
|-----------|----------------|
| External API usage | → `guardrails` (reliability section), `.cursor/rules/reliability.mdc` |
| AI model integration | → `guardrails` (ai-integration checklist), reliability, observability rules |
| Financial/sensitive data | → `guardrails` (security section), `.cursor/rules/security.mdc` |
| New API endpoint | → `guardrails` (api-endpoint checklist), security, observability |
| Database changes / SQL | → `data-platform` executor, `postgres-patterns`, `performance.mdc` |
| Python code / FastAPI | → `backend` executor, `python-patterns`, `code-quality.mdc` |
| Python tests / pytest | → `backend` executor, `python-testing`, `reliability.mdc` |
| SwiftUI / iOS | → `ui-ux` executor, `swift-patterns` |
| Frontend component / page / form | → `ui-ux` executor, `ui-ux-design`, `web/MODULE.md`; `shadcn` only if adding registry primitives |
| Background job | → Celery MCP, reliability, observability |
| TikTok integration / webhook | → `docs/integrations/tiktok_api/`, `data-sources.md`, affected MODULE.md |
| Net-new vendor API / stale `docs/*_api/` | → `api-docs` skill first |
| Marketplace policy / feature guide | → `platform-docs`; `docs/<vendor>_platform/` |
| Automation / hooks changes | → `.cursor/rules/hooks.mdc` |
| New repository / API envelope | → `.cursor/rules/patterns.mdc` |

### Step 3: Load Architecture Baseline

Always consult before loading task-specific context:

```
ALWAYS load:
  - EXECUTION.md (phase, slice, in/out scope for the current issue)
  - docs/architecture/system-design.md (subsystem behavior for the active phase)
  - docs/architecture/map.md (module list, tiers, dependency graph)
  - docs/architecture/data-sources.md (allowed/forbidden external data)
  - MODULE.md for each affected module under src/, web/, or ios/
```

### Step 4: Load Task Context

From the GitHub issue (PRD from `to-prd`), planning handoff, and vendor docs:

```
ALWAYS load:
  - Relevant EXECUTION.md slice(s) driving the issue
  - docs/architecture/system-design.md sections for affected subsystems
  - GitHub issue body (acceptance criteria, user stories)
  - to-prd / planning handoff (scope, edge cases, implementation decisions)

LOAD WHEN VENDOR/PLATFORM WORK:
  - docs/<vendor>_api/*.md as needed (auth, webhooks, endpoints, rate-limits)
  - docs/<vendor>_platform/*/implementation-hooks.md (guardrails, alerts, gates)

LOAD IF EXISTS (legacy only):
  - docs/product/features/<feature-name>/*.md — historical attachments; prefer canonical docs

DO NOT load by default:
  - Full EXECUTION.md when a single slice is sufficient
  - Superseded ADRs unless the issue explicitly references them
```

### Step 5: Load Layer Context

Based on affected layers from [`docs/architecture/map.md`](../../../docs/architecture/map.md):

```
Integrations (src/integrations/tiktok):
  - Load: authentication.md, rate-limits.md, endpoints.md (docs/integrations/tiktok_api/)
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
  - Load: MODULE.md for target app, ui-ux-design (web) or swift-patterns (ios)
  - Skip: Celery/Redis unless debugging a displayed lag issue (v2.0)

AI features (post-MVP / OpenAI):
  - Load: guardrails ai-integration checklist, system-design.md ML model sections, issue eval notes
  - Skip: TikTok connector docs unrelated to the model call
```

### Step 6: Load Tier 2 Rules & Review Checklists

Do NOT load all rules. Tier 1 (`core-safety`, `core-orchestration`, `mcp-usage`, `git-baseline`) is always on. Load Tier 2 based on detection:

```python
RULE_TRIGGERS = {
    "external_api_call": [".cursor/rules/reliability.mdc", ".cursor/rules/observability.mdc"],
    "ai_model_call": [".cursor/skills/standalone/guardrails/checklists/ai-integration.md",
                      ".cursor/rules/reliability.mdc", ".cursor/rules/observability.mdc"],
    "user_input_handling": [".cursor/rules/security.mdc", ".cursor/rules/reliability.mdc"],
    "database_query": [".cursor/rules/performance.mdc", ".cursor/rules/reliability.mdc"],
    "new_endpoint": [".cursor/skills/standalone/guardrails/checklists/api-endpoint.md",
                     ".cursor/rules/security.mdc", ".cursor/rules/observability.mdc"],
    "background_job": [".cursor/rules/reliability.mdc", ".cursor/rules/observability.mdc"],
    "financial_data": [".cursor/rules/security.mdc", ".cursor/rules/reliability.mdc",
                       ".cursor/rules/observability.mdc"],
    "code_change": [".cursor/rules/code-quality.mdc"],
    "frontend_ui": [".cursor/rules/ui-ux-design.mdc"],
    "review_phase": [".cursor/rules/code-review.mdc"],
    "backend_api": [".cursor/rules/patterns.mdc"],
    "automation_change": [".cursor/rules/hooks.mdc"],
    "parallel_issues": [".cursor/rules/issue-workflow.mdc"],
    # Domain skills (prefer over broad docs)
    "python_impl": [".cursor/skills/domain/testing-patterns/python-patterns.md"],
    "python_tests": [".cursor/skills/domain/testing-patterns/python-testing.md"],
    "postgres_impl": [".cursor/skills/domain/testing-patterns/postgres-patterns.md"],
    "swiftui_impl": [".cursor/skills/domain/testing-patterns/swift-patterns.md"],
}
```

**Priority overrides:** security always wins for auth/PII/financial data; reliability is additive with AI integration.

**Review-phase skill split:** load `intent-review` then `guardrails` per
[`.cursor/skills/standalone/intent-review/BOUNDARY.md`](../intent-review/BOUNDARY.md) —
do not conflate Spec fidelity with AC coverage.

### Step 7: Exclude Irrelevant Context

Explicitly DO NOT load:
- Features/services not affected by this task
- Historical context from previous unrelated work
- Full codebase structure (only affected modules)
- Completed/merged feature specs (unless referenced)

## Context Budget

Target: **60-70% of context window for actual code and task**. Context docs should use 20-30%. Reserve 10% for agent reasoning.

**Issue implementation hierarchy (do not restate):** cache → harnessUtility → this Context Plan → Tier-1 → one domain skill → Tier-2 → docs/MODULE → code. Artifacts are post-run telemetry/CI, not prompt filler. Full layers + anti-patterns: [`agent-runtime.md` § Context hierarchy](../../../agent-runtime/docs/agent-runtime.md#context-hierarchy-efficiency); machine-readable: [`agent-runtime.config.yml`](../../../agent-runtime/config/agent-runtime.config.yml) → `context_hierarchy` + `workflow_prompt_cache.injectionOrder`.

| Priority | Content | Budget |
|----------|---------|--------|
| 1 (Critical) | Current file + immediate dependencies | 30% |
| 2 (High) | system-design.md + issue acceptance criteria | 15% |
| 3 (Medium) | Applicable standards + patterns | 10% |
| 4 (Low) | Examples + anti-patterns (load on demand) | 5% |

If context is too large, progressively disclose: load summaries first, fetch details only when the agent needs them.

## Output Format

When invoked, produce a context loading plan (template: `docs/handoffs/context-plan-template.md`):

```markdown
## Context Plan: [Feature/Task Name]

### Agent Phase
- [ ] ad-hoc (Focus only)
- [ ] Planning: Architect Agent (focus → grill-with-docs → to-prd → to-issues)
- [x] Implementation: Meta routing → Executor (built-in TDD)
- [ ] Review + Testing: intent-review → guardrails → validate → ship-ready
- [ ] Harness Optimization: Meta (post-validation)

### Rules (Tier 2 — load selectively)
- [x] `.cursor/rules/reliability.mdc`
- [x] `.cursor/rules/observability.mdc`
- [ ] `.cursor/rules/security.mdc`
- [ ] `.cursor/rules/performance.mdc`
- [ ] `.cursor/rules/code-quality.mdc`

### Skills
- [x] Executor built-in TDD (Red → Green → Refactor)
- [ ] `grill-with-docs` (Architect planning / rescope)
- [ ] `intent-review` (Spec fidelity × structure; Review Agent)
- [ ] `guardrails` (domain quality + ADR-003 review artifact)
- [ ] Plugin: `nextjs` (web/ work)

### MCPs (read schemas only when listed)
- [ ] `supabase`
- [x] — none (TikTok uses docs, not MCP)

### Load (Required)
- `EXECUTION.md` (slice P2-1)
- `docs/architecture/system-design.md` (Data pipeline → Phase 2)
- `docs/architecture/map.md`
- `docs/architecture/data-sources.md`
- GitHub issue #N — acceptance criteria
- `docs/integrations/tiktok_api/endpoints.md`, `authentication.md`
- `src/services/polling/MODULE.md`
- `src/data/MODULE.md`

### Load (If Needed)
- `docs/integrations/tiktok_api/webhooks.md`
- `.cursor/skills/standalone/guardrails/checklists/api-endpoint.md`

### DO NOT Load
- `web/`, `ios/` (not affected)
- Unselected marketplace plugin skills
- MCP tool schemas for servers not listed above
- Shopee/Lazada connector docs (out of scope per data-sources.md #13)
```

## Integration with Agent Roles

| Agent | Uses Navigator For |
|-------|-------------------|
| Architect Agent | Planning context; canonical docs; `grill-with-docs` → `to-prd` / `to-issues` handoffs |
| Meta Agent | Context routing, skill routing, executor domain assignment (IS built on focus). Before Executor: see [`core-orchestration.mdc`](../../../rules/core-orchestration.mdc) + [`prompt-caching`](../prompt-caching/SKILL.md). Single primary domain skill only. |
| Executor Agent | Precisely scoped implementation context from injection plan; built-in TDD. Must not start without valid cache. |
| Review Agent | `intent-review` (Spec + structure) + `guardrails` (domains + review artifact) + issue |

## Meta → Executor hard gate

Always-on one-liner lives in [`.cursor/rules/core-orchestration.mdc`](../../../rules/core-orchestration.mdc). Session procedure: [`prompt-caching`](../prompt-caching/SKILL.md). Do **not** ask the user to prepare caches. Halt Executor unless `readyForExecutor: true`.

## Meta Agent — Harness Optimization (post-validation)

Focus-routed after `validate` (PASS or FAIL). Full procedure, schemas, and must-not list: [`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md) (§ Harness optimization / Product-development optimization). Handoff template: [`docs/templates/handoffs/validation-meta.md`](../../../docs/templates/handoffs/validation-meta.md). Benchmarks: [`agent-runtime-benchmarks.md`](../../../agent-runtime/docs/agent-runtime-benchmarks.md).

Meta must not: implement features; bypass Review/Validate; auto-edit skills/rules/ADRs/PRDs/architecture docs; ship or merge PRs.

## Anti-Patterns

### Context Overload
Loading everything "just in case" — wastes tokens, confuses the agent.

### Stale Context
Loading specs from features that have since changed — causes hallucinated patterns.

### Context Duplication
Loading the same information from multiple sources — wastes budget, risks conflicts.

### Missing Context
Not loading planning handoff edge cases, issue acceptance criteria, or system-design failure modes — agent produces happy-path-only code.

## Additional Resources

- Agent runtime architecture: [`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md)
- Runtime artifacts: [`agent-runtime/docs/agent-runtime-artifacts.md`](../../../agent-runtime/docs/agent-runtime-artifacts.md)
- For context routing rules, see [routing-rules.md](routing-rules.md)
