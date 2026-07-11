# Prompt caching — reference

## Resolve parent issue

Child issue #N is never the cache anchor. Resolve parent #P first:

1. Epic handoff `PRD: [#P]` (e.g. `phase-2-tiktok-implementation.md` → #278)
2. Child issue body: `Parent: #P`, `Part of #P`, tracking link
3. `gh issue view <n> --json body,title` + label `epic:P`
4. `.agent-state/issue-<n>.checkpoint.yml` → `parent_prd`
5. If parent unknown → ask user once before grilling

## Workflow pipeline

```
implement issue #N (child)
  → resolve parent #P
  → load parent-cache-issue-P.json     → inject parentScopeBlock ONLY
  → load grill-cache-issue-N.json      → inject child blocks + issueLoadProfile + harnessUtility
  → Meta → Executor → Review → Validate (each appends its phaseCacheBlocks to child cache)
  → append N to parent.childIssueIds; refresh parent if epic scope changed
```

## What differs per child issue

| Child | Parent #278 constant | Unique to child |
|-------|---------------------|-----------------|
| #297 Layer 1 reads | T8 deferred, Fujiwa read-only | `endpoints.md`, polling MODULE |
| #299 ETL | same parent block | `services/etl/`, data-platform skill |
| #301 sandbox writes | same parent block | sandbox merchant, write validation, tiktok integration |

## Writing caches

### Parent (`parent-cache-issue-<P>.json`)

- `parentScopeBlock` from PRD + handoff confirmed decisions
- Epic `doNotLoad`; fingerprint parent issue + handoff + EXECUTION.md
- `childIssueIds` append on each child completion

### Child (`grill-cache-issue-<n>.json`)

- `parentIssueId`, `parentCachePath` (required)
- `issueLoadProfile` built from **this** issue's AC and files — not siblings
- `harnessUtility` built during Meta for **this** issue only
- `upstreamFingerprints` for **child** issue body — separate from parent

## Authority chain

1. `EXECUTION.md` slice
2. `parent-cache-issue-<P>` (epic constant)
3. **Child** GitHub issue #N acceptance criteria
4. Epic handoff (when not superseded by EXECUTION.md)
5. Legacy — excluded until confirmed

## harnessUtility rule

Populated per child during Meta routing. Same parent block; different child caches:

```json
// #301 — backend integration only
{ "skills": [{ "path": ".cursor/skills/domain/backend/SKILL.md", "purpose": "Sandbox writes" }] }

// #299 — different child, different load
{ "skills": [
    { "path": ".cursor/skills/domain/backend/SKILL.md", "purpose": "ETL services" },
    { "path": ".cursor/skills/domain/data-platform/SKILL.md", "purpose": "Upsert migrations" }
  ]}
```

## Context freshness

| Context | Staleness signal | Action |
|---------|-------------------|--------|
| Child grill cache | Child issue body fingerprint mismatch | Delta grill child only |
| Parent cache | Parent issue or epic handoff changed | Delta grill epic; may affect all children |
| EXECUTION.md / system-design | Rescope PR merged | Reload slices; invalidate fingerprints |

## Cache block fields (child)

| Field | Purpose |
|-------|---------|
| `promptCacheBlock` | Machine-injectable child scope summary |
| `phaseCacheBlocks.scope` | Scope alignment phase output |
| `phaseCacheBlocks.meta` | Meta routing decisions |
| `phaseCacheBlocks.executor` | Executor TDD context |
| `phaseCacheBlocks.review` | Review checklist focus |
| `phaseCacheBlocks.validate` | Validate gate focus |
| `issueLoadProfile` | requiredDocs, requiredModules, acceptanceCriteria, executorDomain |
| `harnessUtility` | skills, rulesTier2, mcps, tools for this child only |
| `cacheStatus` | `valid` \| `stale` \| `partial` |
| `workflowPhase` | Last completed phase |

## Related docs

- [`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md) — phase model
- [`agent-runtime/docs/agent-runtime-artifacts.md`](../../../agent-runtime/docs/agent-runtime-artifacts.md) — artifact taxonomy
- [`agent-runtime/artifacts/README.md`](../../../agent-runtime/artifacts/README.md) — path conventions
