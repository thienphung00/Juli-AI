# Context Routing Audit

Refactor completed 2026-06-09. Focus + skill-catalog are the authoritative routers; default runtime is minimal.

## Summary

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Rule files | 17 | 13 | −4 deleted, −4 merged into Tier 1 |
| `alwaysApply: true` rules | 16 | 4 | −75% |
| Always-on rule lines (est.) | ~728 | 108 | **~85% reduction** |
| Tier 2 conditional lines | — | 447 | Loaded on demand via Focus |
| Duplicate rule bodies | reliability ×2, workflow ×3, style ×3 | 0 | Consolidated |

**Note:** Cursor may still inject marketplace plugin skills and MCP metadata at the platform level. Repo changes enforce lazy-load via Focus + skill-catalog contract; full platform control is not guaranteed.

## Tier 1 — Always On (4 files, 108 lines)

| File | Purpose |
|------|---------|
| `core-safety.mdc` | Secrets, injection, authZ essentials |
| `core-orchestration.mdc` | Focus router, agents, skills governance |
| `mcp-usage.mdc` | MCP principles + catalog pointer |
| `git-baseline.mdc` | Branches, commits, PRs, CI/CD, test-first |

## Tier 2 — Focus-Triggered (9 files)

| File | Load when |
|------|-----------|
| `security.mdc` | Auth, PII, financial data, user input |
| `reliability.mdc` | External API, jobs, tests, error paths |
| `performance.mdc` | DB queries, high-traffic, caching |
| `observability.mdc` | Endpoints, services, jobs |
| `code-quality.mdc` | Any code change |
| `code-review.mdc` | Review phase / explicit review |
| `patterns.mdc` | Repositories, API envelopes |
| `hooks.mdc` | Automation / hooks changes |
| `issue-workflow.mdc` | Parallel issues / worktrees |

## Removed (merged or deleted)

| File | Fate |
|------|------|
| `workflow.mdc` | Merged → `git-baseline.mdc` |
| `dev-workflow.mdc` | Merged → `git-baseline.mdc` |
| `git-workflow.mdc` | Merged → `git-baseline.mdc` |
| `agents.mdc` | Merged → `core-orchestration.mdc` |
| `skills-governance.mdc` | Merged → `core-orchestration.mdc` |
| `coding-style.mdc` | Merged → `code-quality.mdc` |
| `maintainability.mdc` | Merged → `code-quality.mdc` |

## Redundancy resolution

| Capability | Canonical source |
|------------|------------------|
| Git / PR / CI | `git-baseline.mdc` |
| Code style / quality | `code-quality.mdc` + domain patterns |
| Reliability / testing | `reliability.mdc` + `review` checklists |
| MCP routing | `skill-catalog` index; Focus decides; `mcp-usage` principles |
| Security (full) | `security.mdc`; essentials in `core-safety.mdc` |
| Engineering pipeline | `build-feature` / `fix-bug` skills (not rules) |
| Review checks | `review/SKILL.md` + checklists (not duplicated in rules) |

## Repo skills inventory

| Skill | Location | Default | Trigger |
|-------|----------|---------|---------|
| focus | standalone | **Router** | Every non-trivial task |
| skill-catalog | index | Reference | Focus Step 0 / MCP touch |
| discover | standalone | No | New feature / rescope |
| to-prd | standalone | No | After discover |
| to-issues | standalone | No | After PRD |
| tdd | standalone | No | Implementation |
| review | standalone | No | Post-implementation |
| ship | standalone | No | Merge / deploy |
| validate | standalone | No | Pre-merge gates |
| qa | standalone | No | Bug triage |
| api-docs | standalone | No | New/stale vendor API |
| platform-docs | standalone | No | Policy / feature guides |
| build-feature | workflow | No | End-to-end feature |
| fix-bug | workflow | No | Bug / regression |
| python-patterns | domain | No | `src/**/*.py` |
| python-testing | domain | No | pytest |
| postgres-patterns | domain | No | SQL / migrations |
| swift-patterns | domain | No | `ios/**` |
| write-a-skill | meta | No | User explicit ask |

## MCP inventory (lazy-load)

See `skill-catalog` `catalog.mcpServers`. None always-on. Stale reference removed: `user-kafka` (was in old `mcp-usage` table, not in catalog).

## Migration validation

1. Run one TikTok integration issue loop: Focus → Context Plan → tdd → review.
2. Confirm Context Plan lists Rules / Skills / MCPs (template: `context-plan-template.md`).
3. Parallel issue run: verify `issue-workflow.mdc` loads when multiple agents active.
4. Update worktree copies of `.cursor/rules/` when merging to main.

## References

- Router: [`.cursor/skills/standalone/focus/SKILL.md`](../../.cursor/skills/standalone/focus/SKILL.md)
- Catalog: [`.cursor/skills/skill-catalog/SKILL.md`](../../.cursor/skills/skill-catalog/SKILL.md)
- Template: [`context-plan-template.md`](context-plan-template.md)
