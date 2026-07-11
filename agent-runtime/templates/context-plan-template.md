# Context Plan Template

Copy this block when Focus produces a Context Plan. Fill checkboxes per task.

```markdown
## Context Plan: [Feature/Task Name]

### Agent Phase
- [ ] ad-hoc (Focus only)
- [ ] Planning: Architect Agent (focus → to-prd → to-issues)
- [ ] Scope Alignment: `grill-with-docs` (alignment) + `prompt-caching` (cache)
- [ ] Implementation: Meta routing → Executor (built-in TDD)
- [ ] Review + Testing: review → validate → ship-ready
- [ ] Harness Optimization: Meta (post-validation)

### Runtime artifacts (commit on branch when phase completes)
- [ ] `artifacts/grill-cache/parent-cache-issue-<P>.json` (epic constant)
- [ ] `artifacts/grill-cache/grill-cache-issue-<n>.json` (child unique)
- [ ] `docs/handoffs/scope-alignment-issue-<n>.md` (scope alignment)
- [ ] `artifacts/implementations/implementation-issue-<n>.json` (Executor)
- [ ] `artifacts/reviews/review-issue-<n>.json` (Review)
- [ ] `artifacts/validation/validation-issue-<n>.json` (Validate)
- [ ] `artifacts/optimization/harness-issue-<n>-<phaseRunId>.json` (Meta)
- [ ] `artifacts/optimization/product-development-<id>.json` (Meta, occasional)

### Rules (Tier 2 — load selectively)
- [ ] `.cursor/rules/security.mdc`
- [ ] `.cursor/rules/reliability.mdc`
- [ ] `.cursor/rules/performance.mdc`
- [ ] `.cursor/rules/observability.mdc`
- [ ] `.cursor/rules/code-quality.mdc`
- [ ] `.cursor/rules/code-review.mdc`
- [ ] `.cursor/rules/patterns.mdc`
- [ ] `.cursor/rules/hooks.mdc`
- [ ] `.cursor/rules/issue-workflow.mdc`

### Grill cache (child #N, parent #P)
- [ ] Parent constant: `parent-cache-issue-<P>.json`
- [ ] Child unique: `grill-cache-issue-<n>.json` — phase: ___
- [ ] issueLoadProfile: domain ___ | docs ___ | modules ___
- [ ] No sibling child cache loaded

### Skills
- [ ] `to-prd` / `to-issues` (Architect planning; `discover` removed)
- [ ] `grill-with-docs` (scope alignment) + `prompt-caching` (workflow cache)
- [ ] `review` / `validate` / `ship` / `qa` (Executor uses built-in TDD; standalone `tdd` removed)
- [ ] `api-docs` / `platform-docs`
- [ ] Domain: `python-patterns` / `python-testing` / `postgres-patterns` / `swift-patterns`
- [ ] Plugin: _______________

### MCPs (read schemas only when checked)
- [ ] `supabase`
- [ ] `context7`
- [ ] `plugin-sentry-sentry`
- [ ] `figma`
- [ ] `plugin-vercel-vercel`
- [ ] `shadcn`
- [ ] `cursor-ide-browser` / `playwright`
- [ ] `celery` / `upstash`
- [ ] none

### Load (Required)
-

### Load (If Needed)
-

### DO NOT Load
-
```

## Tier 1 (always on — do not list unless debugging)

- `.cursor/rules/core-safety.mdc`
- `.cursor/rules/core-orchestration.mdc`
- `.cursor/rules/mcp-usage.mdc`
- `.cursor/rules/git-baseline.mdc`
- `.cursor/skills/standalone/focus/SKILL.md`

## References

- Runtime: [`docs/architecture/agent-runtime.md`](../architecture/agent-runtime.md)
- Artifacts: [`docs/architecture/agent-runtime-artifacts.md`](../architecture/agent-runtime-artifacts.md)
- Router: [`.cursor/skills/standalone/focus/SKILL.md`](../../.cursor/skills/standalone/focus/SKILL.md)
- Catalog: [`.cursor/skills/skill-catalog/SKILL.md`](../../.cursor/skills/skill-catalog/SKILL.md)
- Audit: [`context-routing-audit.md`](context-routing-audit.md)
