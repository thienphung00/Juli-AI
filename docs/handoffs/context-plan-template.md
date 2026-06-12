# Context Plan Template

Copy this block when Focus produces a Context Plan. Fill checkboxes per task.

```markdown
## Context Plan: [Feature/Task Name]

### Workflow Phase
- [ ] ad-hoc (Focus only)
- [ ] issue implementation: focus → tdd → review → ship → validate
- [ ] fix-bug: qa → focus → tdd → review → ship
- [ ] discover → to-prd → to-issues
- [ ] build-feature (full pipeline)

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

### Skills
- [ ] `discover` / `to-prd` / `to-issues`
- [ ] `tdd` / `review` / `ship` / `validate` / `qa`
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

- Router: [`.cursor/skills/standalone/focus/SKILL.md`](../../.cursor/skills/standalone/focus/SKILL.md)
- Catalog: [`.cursor/skills/skill-catalog/SKILL.md`](../../.cursor/skills/skill-catalog/SKILL.md)
- Audit: [`context-routing-audit.md`](context-routing-audit.md)
