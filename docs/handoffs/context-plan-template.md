# Context Plan Template

Copy this block when Focus produces a Context Plan. Fill checkboxes per task.

```markdown
## Context Plan: [Feature/Task Name]

### Task type
- [ ] Planning (EXECUTION → Tier 1 → ADR)
- [ ] Implementation (Issue → PRD → ADR)

### Workflow phase
- [ ] ad-hoc (Focus only)
- [ ] issue implementation: focus → tdd → review → ship → validate
- [ ] fix-bug: qa → focus → tdd → review → ship
- [ ] grill-with-docs → to-prd → to-issues
- [ ] build-feature (full pipeline)

### Core load (required)
- [ ] `EXECUTION.md` (slice: _____)           ← Planning
- [ ] Tier 1: _______________________________  ← Planning (pick ONE)
- [ ] GitHub issue #____                       ← Implementation
- [ ] PRD / issue body                         ← Implementation
- [ ] ADR(s): ________________________________

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

### domain_skills
domain_skills: []

### Skills / plugins
- [ ] `tdd` / `review` / `ship` / `validate` / `qa`
- [ ] Plugin: _______________

### MCPs (read schemas only when checked)
- [ ] `supabase` / `context7` / `shadcn` / none

### Load (if needed)
-

### DO NOT load
-
```

## Tier 0 (always on — do not list unless debugging)

- `.cursor/rules/core-safety.mdc`
- `.cursor/rules/core-orchestration.mdc`
- `.cursor/rules/mcp-usage.mdc`
- `.cursor/rules/git-baseline.mdc`
- `.cursor/skills/standalone/focus/SKILL.md`

## References

- Router: [`.cursor/skills/standalone/focus/SKILL.md`](../../.cursor/skills/standalone/focus/SKILL.md)
- Routing rules: [`.cursor/skills/standalone/focus/routing-rules.md`](../../.cursor/skills/standalone/focus/routing-rules.md)
- Catalog: [`.cursor/skills/skill-catalog/SKILL.md`](../../.cursor/skills/skill-catalog/SKILL.md)
