# Context Routing Rules

Detailed rules for deciding what context to load based on code patterns detected.

## Detection Patterns → Context Mapping

### Python/FastAPI Patterns

| Code Pattern | Detected Intent | Load |
|-------------|-----------------|------|
| `@app.post`, `@app.get` | New endpoint | api-endpoint checklist, security |
| `await litellm.completion` | AI model call | build-ai, reliability |
| `celery_app.task` | Background job | reliability (retry/idempotency) |
| `httpx.get`, `requests.post` | External API | reliability (timeout/retry) |
| `select(Model).where` | DB query | performance (N+1, indexes) |
| `alembic.op.` | Migration | db-changes spec, rollback plan |
| `os.environ`, `settings.` | Config | security (secrets handling) |

### TypeScript/Next.js Patterns

| Code Pattern | Detected Intent | Load |
|-------------|-----------------|------|
| `'use client'` | Client component | frontend patterns, state mgmt |
| `'use server'` | Server action | security (input validation) |
| `useQuery`, `useSWR` | Data fetching | caching patterns |
| `supabase.from` | DB access | Supabase patterns, RLS policies |
| `<Chart`, `<Recharts` | Visualization | dashboard component library |

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
2. **AI platform is additive** — never replaces reliability; both load together
3. **Performance is conditional** — only loads when new queries or high-traffic paths are involved

## Context Freshness Rules

| Context Type | Staleness Threshold | Action |
|-------------|--------------------:|--------|
| Feature specs | If PR merged > 7 days ago | Verify still current |
| API contracts | If endpoint modified since spec | Reload from source |
| Standards | Never stale | Always use latest |
| Architecture | If new services added | Regenerate affected sections |

## Multi-Feature Context

When a task spans multiple features:

1. Load shared architectural context ONCE
2. Load feature-specific context for EACH affected feature
3. Deduplicate overlapping standards
4. Flag potential conflicts between feature specs

Example: "Add AI forecasting to the GrabFood sync pipeline"
- Load: ai-inventory-forecasting architecture
- Load: grabfood-order-sync architecture
- Load: build-ai (shared)
- Load: connector patterns (shared)
- Flag: data schema overlap between features
