# Context Routing Rules

Detailed rules for deciding what context to load based on code patterns detected.

## Plugin skills and MCP

Before loading feature docs for integration work, consult the project plugin index:

- **Catalog:** [`.cursor/skills/skill-catalog/SKILL.md`](../../skill-catalog/SKILL.md) (`catalog` frontmatter lists MCP servers + `/skill-name` invocations)
- **MCP routing rule:** [`.cursor/rules/mcp-usage.mdc`](../../../rules/mcp-usage.mdc)

| Task signal | Plugin skill(s) to load | MCP `serverName` |
|-------------|-------------------------|------------------|
| Supabase schema, RLS, auth | `supabase`, `supabase-postgres-best-practices` | `supabase` |
| Framework/library docs | `context7-mcp` | `context7` |
| New/stale vendor API reference | `api-docs`, `context7-mcp` | `context7` |
| Seller / creator policy, feature guide, account health | `platform-docs` | — (WebFetch TikTok Shop University + official policy pages) |
| Existing vendor integration (`docs/*_api/`) | — | — (load `docs/<vendor>_api/` + `docs/<vendor>_platform/` + MODULE.md) |
| `web/` / `apps/dashboard` Next.js UI (component, page, form, visual design) | `ui-ux-design`, `nextjs`, `react-best-practices` | — |
| `web/` / `apps/dashboard` deploy / env | `deployments-cicd`, `env-vars` | `plugin-vercel-vercel` |
| shadcn registry primitive | `shadcn` (with `ui-ux-design`) | `shadcn` (prefer `user-shadcn`) |
| Sentry / prod errors | `sentry-workflow` → `sentry-python-sdk` or `sentry-nextjs-sdk` | `plugin-sentry-sentry` |
| Figma | `figma-use` (required before `use_figma`) | `figma` |
| E2E browser | — | `playwright` or `cursor-ide-browser` |
| Celery / Redis | — | `celery`, `upstash` |

## Detection Patterns → Context Mapping

### Python/FastAPI Patterns

| Code Pattern | Detected Intent | Load |
|-------------|-----------------|------|
| `@app.post`, `@app.get` | New endpoint | api-endpoint checklist, security |
| `openai.`, `AsyncOpenAI`, rule-based forecast | AI / heuristic call | review (ai-integration), reliability |
| `celery_app.task` | Background job | reliability (retry/idempotency) |
| `httpx.get`, `requests.post` | External API | reliability (timeout/retry) |
| `select(Model).where` | DB query | performance (N+1, indexes) |
| `alembic.op.` | Migration | db-changes spec, rollback plan |
| `os.environ`, `settings.` | Config | security (secrets handling) |

### TypeScript/Next.js Patterns

| Code Pattern | Detected Intent | Load |
|-------------|-----------------|------|
| `'use client'` | Client component | `ui-ux-design`, app `MODULE.md`, `docs/product/design/` (README + roots) |
| `web/src/components/` or `apps/dashboard/**/components/` | New/changed UI | `ui-ux-design`, nearest existing component, `docs/product/design/Components/<name>.md`, `colors_and_type.css` |
| Route under Home / Decisions / Analytics / Settings | Destination screen | `docs/product/design/Screens/<dest>.md`, matching `Flows/` if journey changes |
| Visual / brand / token / copy polish | Product design | `docs/product/design/README.md` then root authorities (`context.md`, `design.md`, `flows.md`, `soul.md`, `ux_principles.md`) |
| `'use server'` | Server action | security (input validation) |
| `useQuery`, `useSWR` | Data fetching | caching patterns |
| `supabase.from` | DB access | Supabase patterns, RLS policies |
| `<Chart`, `<Recharts` | Visualization | `docs/product/design/Screens/analytics.md`, `Components/charts.md` (Analytics owns metrics) |

**Frontend design authority:** resolve conflicts top-down per `docs/product/design/README.md`. Do not load `preview/`, `ui_kits/`, `source_examples/`, or `context/` unless reconciling evidence — they never override root authorities.

### Infrastructure Patterns

| Code Pattern | Detected Intent | Load |
|-------------|-----------------|------|
| `Dockerfile`, `docker-compose` | Container config | deployment standards |
| `.github/workflows` | CI/CD | ship, ci-examples |
| `nginx.conf` | Load balancing | infrastructure section |
| `railway.json` | Deploy config | deployment environment docs |

## Priority Override Rules

Some detections override others:

1. **Security always wins** — if financial data or auth is involved, security standards load regardless of other priorities
2. **AI core is additive** — never replaces reliability; both load together
3. **Performance is conditional** — only loads when new queries or high-traffic paths are involved

## Context Freshness Rules

| Context Type | Staleness Threshold | Action |
|-------------|--------------------:|--------|
| EXECUTION.md / system-design.md | If rescope PR merged | Reload affected slices/sections |
| GitHub issue / PRD | If planning handoff updated since issue filed | Reload issue + handoff |
| Standards | Never stale | Always use latest |
| Architecture | If new services added | Regenerate affected sections |

## Multi-Feature Context

When a task spans multiple EXECUTION.md slices or subsystems:

1. Load shared architectural context ONCE (`EXECUTION.md`, `map.md`, `data-sources.md`)
2. Load each affected `system-design.md` subsystem section
3. Load GitHub issues / planning handoffs for each slice
4. Deduplicate overlapping standards
5. Flag potential conflicts between slice scopes

Example: "Add demand forecasting on top of TikTok inventory polling (P2-1 + P1.5-4)"
- Load: `EXECUTION.md` slices P2-1, P1.5-4
- Load: `docs/architecture/system-design.md` → Data pipeline + ML models sections
- Load: `docs/architecture/data-sources.md` (confirm #1 API only)
- Load: `src/services/polling/MODULE.md`, `src/data/MODULE.md`
- Load: review ai-integration checklist (shared, if model calls added)
- Flag: shared `InventoryItem` schema between sync and forecast jobs
