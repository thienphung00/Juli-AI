# Focus Routing Rules

Canonical routing for the `focus` skill. Load **only** what the task type requires, then add conditional context from detection tables below.

## Task types

### Planning task

**Signals:** new initiative, rescope, `grill-with-docs`, architecture review, `to-prd` prep, domain modeling, "what should we build?"

```
Planning task
  → EXECUTION.md          (phases, slices, gates, in/out scope)
  → Tier 1 doc            (pick ONE from table below)
  → ADR(s)                (relevant docs/decisions/NNN-*.md only)
```

**Do not load by default:** GitHub issue bodies, PRD attachments, full `MODULE.md` trees, vendor API field maps.

### Implementation task

**Signals:** GitHub issue #N, `tdd`, bug fix with issue, `review`/`ship`/`validate` on a scoped change.

```
Implementation task
  → Issue                 (acceptance criteria, module hints, linked PR)
  → PRD                   (parent issue / `to-prd` output — usually the issue body)
  → ADR(s)                (relevant docs/decisions/NNN-*.md only)
```

**Add on demand** (from detection tables): affected `MODULE.md`, ONE Tier 1 doc when the issue spans a domain not covered by the PRD, Tier 2 rules, domain skills, vendor docs, MCP schemas.

---

## Tier 1 selection

Read [`docs/README.md`](../../../docs/README.md) for the full index. Pick **one** Tier 1 file per planning task; for implementation, load only when the issue touches that domain.

| Task touches… | Tier 1 doc |
|---------------|------------|
| Subsystem behavior, envelopes, ML thresholds | [`docs/system-design.md`](../../../docs/system-design.md) |
| External data availability by phase | [`docs/architecture/data-sources.md`](../../../docs/architecture/data-sources.md) |
| Deployed modules, paths, endpoints | [`docs/architecture/map.md`](../../../docs/architecture/map.md) |
| MVP stack diagram, daily UTC schedule | [`docs/phases/phase-2-mvp.md`](../../../docs/phases/phase-2-mvp.md) |
| KPI charts, T1–T8 techniques | [`docs/ml_layer.md`](../../../docs/ml_layer.md) |
| Home rendering, advisory signals | [`docs/visual_layer.md`](../../../docs/visual_layer.md) |
| Workflow → action taxonomy | [`docs/execution_layer.md`](../../../docs/execution_layer.md) |
| Entity schemas, features, synthetic data | [`docs/data-models/README.md`](../../../docs/data-models/README.md) |
| TikTok API field maps | [`docs/tiktok_api/endpoints.md`](../../../docs/tiktok_api/endpoints.md) |
| Post-MVP real-time / polyglot | [`docs/phases/phase-3-vision.md`](../../../docs/phases/phase-3-vision.md) |
| Pre-MVP history | [`docs/phases/phase-1-completed.md`](../../../docs/phases/phase-1-completed.md) |

**Authority chain:** Code → `EXECUTION.md` → Tier 1 → ADR.

---

## Plugin skills and MCP

Consult [`.cursor/skills/skill-catalog/SKILL.md`](../../skill-catalog/SKILL.md) and [`.cursor/rules/mcp-usage.mdc`](../../../rules/mcp-usage.mdc). Read MCP tool schemas only for selected servers.

| Task signal | Plugin skill(s) | MCP `serverName` |
|-------------|-----------------|------------------|
| Supabase schema, RLS, migrations | `supabase`, `supabase-postgres-best-practices` | `supabase` |
| Framework/library docs | `context7-mcp` | `context7` |
| New/stale vendor API | `api-docs`, `context7-mcp` | `context7` |
| Seller / creator policy | `platform-docs` | — |
| Existing vendor integration | — | — (load `docs/<vendor>_api/` + MODULE.md) |
| `web/` Next.js UI | `ui-ux-design`, `nextjs`, `react-best-practices` | — |
| shadcn registry primitive | `shadcn` + `ui-ux-design` | `shadcn` |
| Deploy / env vars | `deployments-cicd`, `env-vars` | `plugin-vercel-vercel` |
| Production error | `sentry-workflow` | `plugin-sentry-sentry` |
| Figma sync | `figma-use` | `figma` |
| E2E / browser verify | — | `playwright` or `cursor-ide-browser` |
| Celery / Redis | — | `celery`, `upstash` |
| TikTok API / webhooks | — | — (use `docs/tiktok_api/`) |

---

## Code detection → Tier 2 rules and domain skills

Tier 1 rules (`core-safety`, `core-orchestration`, `mcp-usage`, `git-baseline`) are always on. Load Tier 2 selectively.

| Detection | Load |
|-----------|------|
| External API call | `reliability.mdc`, `observability.mdc` |
| AI / model call | `review/checklists/ai-integration.md`, `reliability.mdc`, `observability.mdc` |
| Auth / PII / financial data | `security.mdc`, `reliability.mdc` |
| New endpoint | `review/checklists/api-endpoint.md`, `security.mdc`, `observability.mdc` |
| DB query / migration | `postgres-patterns`, `performance.mdc`, `reliability.mdc` |
| Python / FastAPI | `python-patterns`, `code-quality.mdc`, `patterns.mdc` |
| ML train/infer / copy layer | `mle-agent.md`, `system-design.md` § ML |
| ML algorithm vetting | `data-scientist.md`, `ml_layer.md`, ADR-011 |
| Python tests | `python-testing`, `reliability.mdc` |
| SwiftUI / iOS | `swift-patterns` |
| Frontend component / page | `ui-ux-design`, `web/MODULE.md`, `ui-ux-design.mdc` |
| Background job | `reliability.mdc`, `observability.mdc` |
| Architecture / rescope | `architect.md`, `map.md` |
| Parallel issues / worktrees | `issue-workflow.mdc` |
| Automation / hooks | `hooks.mdc` |
| Review phase | `code-review.mdc` |

**Priority:** security wins for auth/PII/financial data; reliability is additive with AI integration.

---

## Layer map (implementation add-on)

Load `MODULE.md` for affected paths only. Module list: [`docs/architecture/map.md`](../../../docs/architecture/map.md).

| Layer | Path(s) |
|-------|---------|
| Integrations | `src/modules/catalog/domain/integrations/tiktok/` |
| Services | `src/apps/cron_jobs/services/polling/`, webhook ingest |
| Intelligence / ML | `src/modules/catalog/domain/intelligence/`, `src/modules/ml/` |
| Data | `src/` repos, Alembic, Supabase |
| API | `src/apps/api_gateway/` |
| Interface | `web/`, `ios/` |

---

## Context budget

Target **60–70%** of the window for code and task work. Docs **20–30%**. If overloaded, drop Tier 1 extras first, then vendor docs, never drop Issue + ADR on implementation tasks.

---

## Multi-slice tasks

When an issue spans multiple EXECUTION slices:

1. Load shared planning context once (`EXECUTION.md` + one Tier 1 + ADRs).
2. Load each issue/PRD section for the active slice only.
3. Deduplicate Tier 2 rules and domain skills.
4. Flag scope conflicts in the Context Plan.
